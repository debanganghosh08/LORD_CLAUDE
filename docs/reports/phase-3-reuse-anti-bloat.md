# Phase 3 Report: Reuse-First / Anti-Bloat Engine

Date: 2026-09-20

## Objective

Attack the user's most painful failure mode: agents that write 500 lines
where 50 would do, re-implement what already exists, add wrappers and
parallel abstractions, and touch unrelated files. Enforce the decision order
REUSE -> EXTEND -> REFACTOR -> CREATE with evidence, detect existing
duplication, and measure every change surface with a bloat signal that is
about shape, never about size alone.

## What was built

```
lord/reuse.py               reuse decision ladder; duplicate symbols, values, bodies, thin wrappers
lord/change_surface.py      Git-based change measurement and bloat signal
lord/cli.py                 `reuse`, `duplicates`, `diff` commands
lord/extractors/python_ast.py  constants now carry their value (for duplicate-value detection)
lord/extractors/js_ts.py    symbols now carry end lines (for body comparison)
lord/query.py               prefix stemming + more stopwords for behaviour search
.agents/skills/lord-reuse-audit/SKILL.md    the procedure (before creating; after implementing)
.agents/skills/lord-pre-edit-audit/SKILL.md steps 5 and 8 now call `reuse` and `diff`
tests/fixtures/dup_repo/    fixture with deliberate duplication (11 files)
tests/test_reuse.py         16 tests
```

## What the code does

**`lord reuse "<behaviour>" --name <Proposed>`** answers "before I create
this, what exists?" It checks each proposed name for an indexed definition
(REUSE, confirmed) or a text-only presence (possibly an unsupported
language), runs the behaviour search from Phase 2, splits candidates into
strong (score >= 6: reuse-or-extend) and partial, drops noise below score 3,
and ends with one DECISION finding: `reuse`, `extend`, `refactor-or-create`
or `create`. The decision always states which terms were searched and that
absence of a match is not proof of absence.

**`lord duplicates`** reports candidate duplication already in the
repository, code files only by default:
- same-named functions, classes, constants, types across files (same-named
  methods on different classes are normal and excluded);
- constants with the same name but DIFFERENT values (a divergence trap);
- constants with the same value under different names;
- near-duplicate function bodies: token 4-gram shingles compared with
  Jaccard similarity, both exact (>= 0.70: duplicated logic) and
  identifier-normalised (>= 0.80: same structure with renamed identifiers).
  An inverted index over shingles keeps this far below O(n^2);
- thin wrappers: Python functions whose entire body is `return other(<same
  params in the same order>)`, excluding builtins such as `bool(x)`.

**`lord diff [--base REF] [--staged] [--scope ...]`** measures the change
surface from Git (`--numstat`, `--name-status`, untracked files, `-w` for
whitespace-only lines) and the index:
- summary line for the self-check: files, new/deleted, +/- lines, net
  growth, new symbols;
- per new code file: a question ("does this represent a genuinely new
  responsibility?"), and a reason when the file holds a single small symbol;
- new symbols whose names already exist as the same kind in another code
  file (name collision);
- new functions that resemble existing ones (the Phase 3 similarity engine
  applied to the delta only);
- additive-heavy diffs (net growth >= 150 lines with almost nothing removed);
- formatting-only churn (whitespace-only lines >= 20% of added lines and
  >= 5 lines);
- manifest/dependency changes, flagged when outside the stated scope;
- potentially unrelated files: with `--scope`, files that neither match the
  scope nor import/are imported by an in-scope file; without scope,
  changed code files outside the largest import-connected component;
- code changed across four or more top-level directories.
The result is a BLOAT SIGNAL of `low`, `elevated` or `high` with the list of
reasons. A large diff with no reasons is `low` and says "size alone is not
judged".

## Design decisions

1. **A signal with reasons, not a threshold.** Every reason names the file
   or symbol so the agent can act on it; the level is derived from the
   reasons. There is no "100 lines is too much" rule anywhere.
2. **Code files only for bloat reasons.** New tests, docs, and package
   markers (empty `__init__.py`) never raise the signal; test-file symbols
   never count as collisions. This was tuned by dogfooding on LORD's own
   Phase 3 working tree, where the first version produced 24 reasons, most
   of them fixture and test noise; the final version produces 3, all true.
3. **Two similarities.** Exact-token similarity catches copies; normalised
   similarity catches copies with renamed identifiers. Both thresholds are
   named constants with comments, and both are labelled `inferred`.
4. **The decision ladder is data.** `reuse` returns `meta.decision` so a
   Phase 6 hook can gate file creation on it without re-parsing prose.
5. **Windows line endings are a measurement hazard.** Tests write with
   `newline="\n"`; a first version of the tests silently produced CRLF files
   that made every line a whitespace change.

## What was reused

Phase 2's `related`, `symbols_named`, `symbols_in`, `find_identifier`,
`extract` and the index; Phase 1's `Report`/`Finding` model and CLI
skeleton. No new dependencies.

## What was new

The two modules, three commands, one skill, the fixture and the tests; two
small extractor upgrades.

## Tests

`tests/test_reuse.py` (16) plus earlier suites: **91 passed in ~5.5s**.
Behaviours covered:
- constants carry values; JS symbols get end lines;
- reuse ladder: existing name -> `reuse` with an import recommendation;
  strong behavioural match ("check whether an e-mail address is valid") ->
  `extend` with `validate_email` first; unrelated request ("wavelet
  transform") -> `create`, labelled inferred with the proof-of-absence caveat;
- duplicates: same-name constant with different values, same value under
  two names, same-name function and class across files, renamed-identifier
  clone (`validate_email` vs `check_email`) with normalised similarity >=
  0.8, exactly one thin wrapper, tests excluded;
- thin-wrapper precision (extra argument, reordered arguments and builtin
  conversions are not wrappers);
- change surface on a real temporary Git repository: tracked/untracked/
  deleted files with correct line counts and zero whitespace churn; a
  one-line focused edit -> `low`; a copied function in a new file ->
  `resembles-existing` and `high`; name collision + re-indentation churn +
  manifest edit + docs edit with `--scope` -> each finding present and
  `elevated`; without scope, import connectivity isolates the disconnected
  file; `--staged` and `--base HEAD~1` modes; outside Git -> explicit
  `unavailable`;
- CLI JSON contract for `reuse`, `duplicates`, `diff`.

Development failures fixed: CRLF churn from `write_text`; a file absent from
the `-w` numstat was treated as fully non-whitespace (now correctly all
whitespace); `is_valid_email` outranking `validate_email` (prefix stemming
and stopwords); weak lexical matches blocking `create`; `return bool(x)`
reported as a wrapper; empty diffs lacking a bloat level.

## Manual validation (dogfooding on LORD)

| Command | Result |
|---|---|
| `reuse "find where a symbol is defined" --name find_definition` | decision `extend`; `Symbol`, `Index.symbols_named`, `query.symbols_in` among the candidates |
| `duplicates` | no duplicate candidates in LORD's own code |
| `diff --scope reuse --scope change_surface` (this phase's tree) | 22 files, +1068/-12, 82 new symbols; bloat `elevated` for three true reasons: additive-heavy (a new feature), a fixture manifest outside the lexical scope, 14 files outside the lexical scope (docs, extractors, query, fixtures) |

The last row is the intended behaviour: a new-feature phase is additive,
and the agent is expected to justify each listed reason rather than have it
hidden.

## Git

Commit: Phase 3 commit on `main` (see `git log`). Push result recorded in
the Phase 4 report.

## Known limitations

- Similarity is token-based. It finds copies and renamed copies, not
  semantic equivalents written differently.
- Thin-wrapper detection is Python only and only for positional forwarding.
- `--scope` matching is lexical (path prefix or substring in paths and new
  symbol names) plus one hop of import connectivity.
- Unrelated-change detection without scope depends on resolved imports; in
  unsupported languages every changed file looks disconnected, and the
  report says the analysis is heuristic.
- Deletion/simplification opportunities are surfaced only through
  `duplicates` and `thin-wrapper`; there is no automatic "delete this"
  suggestion beyond those.

## Next phase readiness

Phase 4 (impact / root cause) needs a relationship graph over the index
(imports, calls, bases, tests) and traversal. All inputs exist in the
`Extraction` records; no Phase 3 contract needs to change.
