# LORD: Engineering Summary, Phases 1-5

Date: 2026-09-20. Repository: `C:\How_I_Build_Claude_Locally_which_can_run_with_any_model\LORD_Claude_Clone`,
remote `https://github.com/debanganghosh08/LORD_CLAUDE.git`, branch `main`.

## 1. Executive summary

LORD is now a working, model-agnostic engineering harness for
Antigravity (and, through `AGENTS.md`/`CLAUDE.md`, other agent tools) with a
standard-library-only Python core of 18 commands and no model API. Inside a
workspace it can:

- verify the environment and the workspace/Git boundary (`doctor`);
- inventory a repository with configurable exclusions and honest
  classification (`inventory`);
- index Python (confirmed, via `ast`) and JavaScript/TypeScript (inferred,
  heuristic) symbols, imports, calls, references and bases incrementally
  in `.lord/` (`index`, `symbols`);
- answer where a symbol is defined, who uses it and in which scope, what a
  file depends on and what depends on it, which tests touch it, and what
  related implementations exist by behaviour (`def`, `refs`, `deps`,
  `dependents`, `tests-for`, `related`);
- enforce reuse -> extend -> refactor -> create with a decision and
  evidence, and surface existing duplication: same-named symbols, constants
  with the same value or divergent values, near-duplicate and
  renamed-identifier function bodies, thin wrappers (`reuse`, `duplicates`);
- measure any change surface from Git and emit a bloat signal with named
  reasons, never a size threshold (`diff`);
- build a relationship graph with per-edge confidence and receiver-aware
  resolution, report impact (callers, chains, dependents, subtypes, tests,
  config, boundary, consequences) and produce a root-cause worksheet with
  candidate causes, upstream callers and missing evidence (`graph`,
  `impact`, `trace`);
- give the model a one-call pre-edit brief and a completion verdict backed
  by real test/lint/build results (`brief`, `verify --run`);
- run five read-only specialist subagents and four skills that bind the
  tools to senior-engineer behaviour, under one always-on contract.

Every finding carries `confirmed`, `inferred` or `unknown`. "Could not
analyse" is never reported as "nothing found".

## 2. Final directory tree

```
LORD_Claude_Clone/
  .agents/                          Antigravity adapter (tracked product source)
    rules/lord-operating-contract.md            always_on behaviour contract (4.1k chars)
    skills/lord-critical-review/SKILL.md        13-step decision sequence, delegation, pushback format
    skills/lord-pre-edit-audit/SKILL.md         executable checklist bound to the commands
    skills/lord-reuse-audit/SKILL.md            reuse ladder before creating; diff after implementing
    skills/lord-impact-analysis/SKILL.md        impact and root-cause procedure, status vocabulary
    agents/lord-investigator.md                 read-only specialists, fixed output formats
    agents/lord-reuse-auditor.md
    agents/lord-impact-analyst.md
    agents/lord-skeptical-reviewer.md
    agents/lord-verification-reviewer.md
  lord/                             core, Python 3.11+ standard library only (3,449 lines)
    cli.py paths.py config.py report.py doctor.py                 phase 1
    inventory.py symbols.py index.py search.py query.py          phase 2
    extractors/__init__.py python_ast.py js_ts.py                phase 2
    reuse.py change_surface.py                                   phase 3
    graph.py impact.py                                           phase 4
    review.py                                                    phase 5
  tests/                            119 tests (1,113 lines) + fixtures
    test_foundation.py test_forensics.py test_reuse.py test_impact.py test_review.py
    fixtures/sample_repo/           mixed-language repo with deliberate traps
    fixtures/dup_repo/              deliberate duplication
  docs/
    ARCHITECTURE.md ROADMAP.md SECURITY.md
    decisions/0001-python-stdlib-core.md 0002-antigravity-adapter-layout.md
    reports/phase-1 ... phase-5, summary-phases-1-5.md
  AGENTS.md CLAUDE.md README.md CONTRIBUTING.md LICENSE pyproject.toml .gitignore .gitattributes
  .lord/                            generated index (ignored)
```

## 3. Phase-by-phase summary

| Phase | Objective | Major files | Tests | Commit | Push |
|---|---|---|---|---|---|
| 1 Foundation | boundary, Git/GitHub, ignore policy, core skeleton, contract, first skill and agent, docs | paths, config, report, doctor, cli; contract rule; pre-edit-audit skill; investigator agent | 54 | `80e60af` | ok |
| 2 Repository forensics | inventory, symbol model, extractors, incremental index, search, queries | inventory, symbols, extractors/, index, search, query; sample_repo | 75 | `fd0373c` | ok |
| 3 Reuse / anti-bloat | reuse ladder, duplicate detection, change surface with bloat signal | reuse, change_surface; reuse-audit skill; dup_repo | 91 | `c3bc593` | ok |
| 4 Impact / root cause | relationship graph, impact report, trace worksheet, receiver-aware resolution | graph, impact; impact-analysis skill | 104 | `dedf9db` | ok |
| 5 Senior-engineer behaviour | brief, verify, four specialists, critical-review protocol | review; four agents; critical-review skill | 119 | `40897a4` | ok |

Each phase has its own report in `docs/reports/` with objective, design,
decisions, reuse, tests executed and results, manual validation and
limitations.

## 4. Architecture

```
USER INTENT
  -> RULE  .agents/rules/lord-operating-contract.md      principles (always on)
  -> SKILLS critical-review / pre-edit-audit / reuse-audit / impact-analysis   procedures
  -> SPECIALISTS investigator / reuse-auditor / impact-analyst / skeptical-reviewer / verification-reviewer
        (read-only; run commands; return fixed structures)
  -> DETERMINISTIC CORE  python -m lord ...
        forensics:  inventory -> extractors -> index -> search/query
        reuse:      related + reuse ladder + duplicates
        change:     git diff facts + symbol delta + bloat reasons
        impact:     graph (8 edge kinds, confidence) -> impact / trace
        review:     brief (synthesis) / verify (real results, verdict)
  -> CONTEXT  compact Markdown or JSON reports; findings capped; confidence explicit
  -> STATE    .lord/index.json (generated, ignored); docs/decisions + reports (durable, versioned)
  -> MODEL    reasons over targeted source the reports point at; implements; decides
  -> VERIFICATION  verify --run; diff --scope; the verdict is data for Phase 6 hooks
```

Rules hold principles, skills hold procedures, agents hold roles, the core
holds facts. The contract is written once and referenced.

## 5. Model / harness separation

LORD provides: boundary and path safety; inventory and index; confirmed
Python structure and heuristic JS/TS structure; identifier search; reuse
candidates and duplicate evidence; change measurement and bloat reasons;
the relationship graph, impact chains and root-cause candidates; detected
verification steps and their real results; structured, capped, confidence-
labelled reports; the behaviour contract, procedures and specialist roles.

The model provides: reading and understanding the source the reports point
at; judging whether a candidate really covers a behaviour; deciding the
smallest correct change; writing code; deciding when an ambiguity is
material; forming and stating an objection; confirming a root cause.

Model-dependent by design: instruction following (whether the contract and
skills are honoured), reasoning quality, tool selection, and honesty under
pressure. LORD makes shallow habits mechanically visible; it cannot make
models identical.

## 6. Repository intelligence

CONFIRMED: Python functions, methods, classes, constants (with values),
variables, route decorators, imports resolved to workspace files, calls,
references, bases; graph edges via import bindings, same-file definitions
and same-file inheritance; file kinds and exclusions; Git diff facts
(files, lines, whitespace-only, new/deleted/renamed); test results run by
`verify --run`.

HEURISTIC (inferred): JS/TS declarations, methods, interfaces, types,
enums, imports, exports, calls, routes; cross-file name-based resolution
and unknown-receiver method calls; `related` behaviour search and the
reuse decision; duplicate and resemblance similarity; config files naming
symbols; bloat reasons; import-based test coverage.

UNSUPPORTED (unknown, always stated): every other language; syntax errors;
dynamic dispatch, reflection, string-based lookups; type information.

FUTURE: tree-sitter or LSP extractors behind the same `Extraction`
contract; cross-file inheritance resolution; data-flow.

## 7. Anti-bloat system

Reuse: `reuse` decision ladder with exact-name hits and behavioural
candidates; the pre-edit audit and reuse auditor require it before any new
symbol. Duplicate implementation: `duplicates` (same names, same values,
near-identical and renamed-identifier bodies) and `diff` resemblance of new
functions to existing ones. Unnecessary files: every new code file is
questioned; a single-symbol small file raises the signal. Unnecessary
abstractions: thin wrappers, name collisions, parallel definitions.
Oversized diffs: additive-heavy shape and wide surface are reasons, never a
line limit. Unrelated changes: scope matching plus import connectivity,
manifest changes outside scope, formatting-only churn. Simplification:
duplication and wrapper findings recommend consolidation limited to what
the task touches.

## 8. Critical-engineer behaviour

Evidence-based pushback: the skeptical reviewer and the critical-review
skill require EVIDENCE -> CONSEQUENCE -> RECOMMENDATION -> USER DECISION,
one objection, stated once, then the user's choice stands. Clarification:
only when interpretations differ materially; otherwise state the assumption
and proceed. Root cause: `trace` ranks candidate causes and upstream
callers and lists missing evidence; the status vocabulary reserves CONFIRMED
for the model after reading the source. Consequences: `impact` states who
breaks, which tests exist or do not, which config names the target, and
which boundaries are crossed. User authority: every pushback ends with what
LORD will do in each case the user chooses.

## 9. Testing

119 tests pass (`python -m pytest`, about 34 s on Windows 11, Python
3.13.5, pytest 8.4.2). Suites: foundation (boundary, config, report model,
doctor, adapter structure, ignore policy via `git check-ignore`, provider
independence), forensics (inventory kinds and exclusions, both extractors,
index persistence and incremental reuse, search, all queries, CLI JSON),
reuse (ladder decisions, every duplicate kind, wrapper precision, change
surface on a real temporary Git repo including low/elevated/high cases,
staged and base-ref modes, outside Git), impact (graph edges and
resolution incl. receiver-aware cases, impact of function/class/file, trace
ranking and chains), review (brief, step detection, verify with real pytest
pass and fail, untested change, exact specialist set and read-only
frontmatter, protocol contents). Dogfooding on LORD's own repository was
performed in every phase and fixed real false positives (generated-marker
probe, fixture noise in bloat reasons, `subprocess.run` false chains).

## 10. Git / GitHub

Root `LORD_Claude_Clone` (verified with `git rev-parse --show-toplevel`
before every push); remote `origin` = the LORD GitHub repository; branch
`main` tracking `origin/main`; commits `dbeba9b` (pre-existing LICENSE),
`80e60af`, `fd0373c`, `c3bc593`, `dedf9db`, `40897a4`; every push
succeeded via Git Credential Manager; nothing outside the repository was
ever staged. Ignored: `.lord/`, `.claude/`, `.gemini/`, provider and IDE
state, `.env*`, keys, tokens, caches, build output, logs. Tracked:
`.agents/**`, `lord/**`, `tests/**` (fixture vendor dirs deliberately
un-ignored), `docs/**`, root docs and configuration.

## 11. Limitations

Only Python is confirmed; JS/TS is heuristic; everything else is inventory
plus text search. Lexical reuse search cannot prove equivalence. Bloat
reasons are heuristics. Cross-file inheritance and unknown-receiver calls
are inferred; dynamic behaviour is invisible. Test coverage of a change is
import-based. Enforcement is advisory until Phase 6. The Antigravity
adapter follows public documentation and has not been exercised in a live
Antigravity session. ripgrep is not a real binary on this machine, so the
pure-Python search runs; large repositories are untested. No LSP or type
information.

## 12. Architectural debt (intentional)

The JS/TS extractor is regex-based and will be replaced behind the same
contract. Similarity thresholds and reuse score cut-offs are hand-tuned
constants. The graph is rebuilt per command (cheap now; cache later if
repositories grow). Config edges are lexical. The specialists' prompts are
untested against real models beyond this session.

## 13. Phase 6

Deterministic enforcement through `.agents/hooks.json`: a `PreToolUse`
gate on file-writing tools that requires a recent `brief`/`reuse` for the
target (decision recorded in `.lord/session/`), a `Stop` hook that runs
`verify --json` and blocks completion with the outstanding list when the
verdict is not verified, a `PostToolUse` change-surface note when the
bloat signal rises to high, all with bounded timeouts, log-and-allow on
internal error, never deleting or rewriting user code, and verified on
Windows (the shell used by Antigravity command handlers must be
established first).
