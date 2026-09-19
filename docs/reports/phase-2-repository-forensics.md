# Phase 2 Report: Repository Forensics / Code Intelligence

Date: 2026-09-20

## Objective

Give any model a deterministic way to answer, with evidence and explicit
confidence: where is this symbol defined, where is it used, who calls it,
what does this file depend on, what depends on it, which tests touch it, and
what related implementations already exist. Start with what can be established
reliably; never fake semantic understanding.

## What was built

```
lord/inventory.py            file walk, configurable exclusions, kind/language classification
lord/symbols.py              Symbol / Import / Ref / Base / Extraction data model
lord/extractors/__init__.py  dispatcher: python -> confirmed, js/ts -> inferred, else -> unknown
lord/extractors/python_ast.py  stdlib AST extractor
lord/extractors/js_ts.py     regex-based JS/TS extractor
lord/index.py                incremental JSON index in .lord/index.json
lord/search.py               whole-identifier search (ripgrep optional, Python fallback)
lord/query.py                def / refs / related / deps / dependents / tests-for / symbols
lord/cli.py                  nine commands behind one interface
tests/fixtures/sample_repo/  mixed-language controlled fixture (18 files)
tests/test_forensics.py      21 tests
```

Adapter and docs updated: `lord-pre-edit-audit` skill and `lord-investigator`
agent now call the real commands; `docs/ARCHITECTURE.md` gained the module
table and the CONFIRMED / HEURISTIC / UNSUPPORTED / FUTURE capability table;
README quick start lists the commands.

## What the code does

**Inventory.** One `os.walk` with directory pruning by name (`node_modules`,
`.venv`, `build`, `dist`, caches, provider runtime dirs, and so on) and glob
exclusions, both overridable in `lord.toml` (`exclude_dirs`,
`extra_exclude_dirs`, `exclude_globs`, `extra_exclude_globs`). Each file gets
a kind (`source`, `test`, `config`, `manifest`, `script`, `docs`,
`generated`, `data`, `other`) and a language. Generated code is detected by
directory name, suffix (`_pb2.py`, `.g.dart`, ...) or a marker in the first
five lines only (a false positive on LORD's own source was found during
dogfooding and fixed). Manifests mark project roots. Symlinks are skipped.

**Extractors.** Python uses `ast`: functions, methods, classes, module-level
constants/variables, route decorators, imports resolved to workspace files
(absolute, relative, `src/`-style layouts), calls, name references and class
bases. Syntax errors produce an `unknown` extraction with the error, not an
empty result. JavaScript/TypeScript uses line-oriented regexes with a brace
depth stack: functions, arrow functions, classes and their methods,
interfaces, types, enums, imports (`import ... from`, `require`, dynamic
import) with relative-specifier resolution, exports including
`export default name`, calls and Express-style routes. All JS/TS results are
labelled `inferred`. Any other language returns `unknown` with the message
"analysis unavailable".

**Index.** `Inventory` plus one `FileEntry` per file (size, mtime, sha1,
extraction) serialised to `.lord/index.json`. Refresh is incremental: a file
is re-read only when size or mtime changed, and re-extracted only when its
sha1 changed. Every query runs `ensure_index`, so results always reflect the
working tree. The index is rejected if its version or root differs.

**Search.** Whole-identifier search over inventoried text files. ripgrep is
used when a real binary is on PATH (it is not on this machine; `rg` there is
a Git Bash shell function). The Python fallback prefilters with a bytes
`in` check before applying a word-boundary regex.

**Queries.** Each returns a `Report`:
- `def`: matching symbols by name, qualname or qualname suffix.
- `refs`: confirmed references from Python AST (names, calls, import
  bindings, with the enclosing scope so callers are known) plus inferred text
  matches everywhere else. Lines that match only as text in a parsed file are
  reported separately as comment/string matches. Files in unsupported
  languages surface as text matches and an `analysis-unavailable` finding.
- `related`: lexical behaviour search. Query and symbol names are tokenised
  (camelCase/snake_case aware, light stemming) and expanded through a small,
  explicit synonym table (validate/check/verify, normalize/sanitize/clean,
  email/mail/address, ...). Scoring favours query coverage and demotes test
  functions. Results are candidates, never proof.
- `deps` / `dependents`: resolved workspace imports in both directions with
  the per-import confidence; external imports listed separately.
- `tests-for`: test files that import the target file or mention the symbol.
- `symbols`: what a file defines, with the extraction's confidence.

## Design decisions

1. **Confidence is structural, not decorative.** Extraction confidence flows
   into every finding; `refs` splits confirmed from inferred; unsupported
   languages produce an explicit `unknown` finding in every report.
2. **No parser dependency.** Python's `ast` gives confirmed results for the
   language LORD is written in; JS/TS heuristics are honest about being
   heuristics. A tree-sitter extractor can be added behind the same
   `Extraction` contract when justified (ADR 0001).
3. **JSON index, not a database.** The index is a few hundred KB for a
   medium repository, reproducible, inspectable and diff-able. SQLite would
   add nothing at this scale.
4. **Queries auto-refresh.** Stale indexes are the classic failure of code
   intelligence tools; incremental refresh on every query removes the failure
   mode at the cost of a stat per file.
5. **Fixture with deliberate traps.** Excluded `node_modules/` and `build/`
   directories contain a competing `validate_email`; `generated/` contains
   another; `native/main.rs` mentions it in an unsupported language;
   `pkg/broken.py` does not parse; `pkg/users.py` mentions it in a comment.
   The tests assert that each trap is handled the right way.

## What was reused

`lord.paths`, `lord.config`, `lord.report` and the CLI skeleton from Phase 1,
unchanged in contract. The `Finding` model carried the confidence vocabulary
without modification.

## What was new

The seven modules listed above, the fixture, and the tests.

## Tests

`tests/test_forensics.py` (21 tests) plus the Phase 1 suite: **75 passed in
1.96s**. Coverage by behaviour:

- inventory classification for every kind; exclusion of vendor/build dirs;
  configurable exclusions; generated detection by header marker; regression
  test that a marker mentioned in code (outside the header) is not generated;
- Python extractor: symbols, docstrings, methods with parents, bases,
  absolute and relative import resolution, external imports as inferred,
  calls with scopes, constants vs variables, exports, syntax error -> unknown,
  route decorators;
- JS/TS extractor: functions, classes, methods, constants, arrow functions,
  routes, bases, named/default/aliased imports with resolution, exports,
  calls with scope; TypeScript interfaces/types/enums;
- unsupported language -> unknown;
- index build, persistence under `.lord/`, parse-error and
  unsupported-language findings, reload, incremental reuse (exactly one file
  re-extracted after one edit), excluded/generated definitions absent;
- search: word-bounded, exclusions respected, no partial matches;
- queries: definition (exact, qualified, missing -> warn); references split
  by confidence with callers and comment matches; related ranking for
  "email normalization" and "check that an e-mail address is valid";
  deps/dependents across Python and JS; tests-for symbol and file;
  symbols-in with parse error -> unknown;
- CLI JSON contract for inventory, index, def, refs, dependents, symbols
  (with a Windows-style path) and related.

Development failures fixed along the way: JS `export default name` was not
captured and class methods leaked into exports; `related` ranked a test
function above the implementation (fixed with a precision term and a test-file
demotion); the generated-marker probe matched LORD's own marker list.

## Manual validation (dogfooding on LORD itself)

| Command | Result |
|---|---|
| `inventory` | 50 files; python 22, javascript 2, rust 1, shell 1; project roots `.` and the fixture; 7 excluded dirs |
| `index --rebuild` | 0.16 s; incremental refresh 0.12 s |
| `def Report` | `lord/report.py:49 class Report` (confirmed) |
| `refs find_identifier` | 7 confirmed uses in `lord/query.py` (scopes `references`, `tests_for`); 3 text matches in tests |
| `related "workspace root path safety"` | `find_workspace_root`, `index_path`, `ROOT_MARKERS` |
| `deps lord/query.py` | index, report, search, symbols resolved; 4 external |
| `dependents lord/report.py` | 9 importers with the exact names imported, test marked `[test]` |
| `tests-for safe_join` | `tests/test_foundation.py` |

## Git

Commit: `fd0373c` "Phase 2: repository forensics and code intelligence" on `main`.
Push: succeeded (`80e60af..fd0373c main -> main`).

## Known limitations

- `related` is lexical. It finds candidates by name, docstring and file
  terms; it cannot prove behavioural equivalence.
- Python calls are matched by name, not type: `service.create` matches every
  `create`. Scope evidence lets the reader disambiguate.
- JS/TS extraction is regex-based and will miss or misread unusual
  formatting, multi-line declarations and decorators.
- Only Python and JS/TS have extractors. Everything else is inventory plus
  text search, reported as `unknown`.
- Very large repositories: the Python search fallback reads every text file
  per query; ripgrep, when installed as a real binary, is used automatically.
- No LSP or type information.

## Next phase readiness

Phase 3 (reuse-first / anti-bloat) can build on `related`, `definition`,
`symbols_in` and the index's symbol stream for duplicate detection, and on
Git for change-surface measurement, without changing any Phase 2 contract.
