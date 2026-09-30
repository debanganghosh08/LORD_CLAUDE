# LORD Architecture

## 1. Purpose

LORD turns an IDE-hosted coding model into something that behaves like a
senior engineer who owns the repository. It does this by surrounding the model
with evidence, constraints, deterministic tooling and verification, not by
depending on any one model or provider.

```
USER INTENT
   |
LORD OPERATING CONTRACT        plugin/rules  (always-on behaviour contract)
   |
REPOSITORY FORENSICS           lord.inventory, lord.symbols, lord.index   (Phase 2)
   |
CONTEXT / STATE                targeted retrieval, .lord/ cache, docs/decisions
   |
INTENT + IMPACT + REUSE        lord.reuse, lord.change_surface (P3); lord.impact (P4)
   |
MODEL REASONING                the IDE's current model (Claude / Gemini / GPT / ...)
   |
IMPLEMENTATION                 the model, following the contract and skills
   |
DETERMINISTIC VERIFICATION     tests, type checks, diff measurement, hooks (P6)
   |
CRITICAL REVIEW                specialist agents and review skills (P5)
   |
MEMORY / STATE UPDATE          durable decisions and discoveries (P7)
```

## 2. Model vs harness

| Model-dependent (LORD cannot supply) | Harness-dependent (LORD supplies) |
|---|---|
| reasoning quality | context retrieval and ranking |
| coding quality | repository inventory and indexing |
| judgement under ambiguity | deterministic dependency and reference analysis |
| tool selection and planning | change-surface and bloat measurement |
| ability to use retrieved evidence | reuse candidate discovery |
| instruction following | policy enforcement through hooks |
| error recovery | state persistence across sessions |
| | task decomposition into specialist investigations |

LORD does not make models identical. It makes the environment strong enough
that weak habits (shallow exploration, duplication, bloat, reflexive agreement)
are mechanically discouraged, and strong models get better evidence.

## 3. Layers

### 3.1 LORD core (`lord/`)

Python 3.11+, standard library only, zero runtime dependencies, no network,
no model API. Exposed through one stable boundary: `python -m lord <command>`
(and the equivalent Python functions). Every command returns a
`lord.report.Report` of `Finding`s with explicit confidence.

| Module | Responsibility | Phase |
|---|---|---|
| `paths.py` | workspace root resolution, Git root check, path safety | 1 |
| `config.py` | defaults plus optional `lord.toml` overrides (exclusions) | 1 |
| `report.py` | shared Finding/Report model, JSON and Markdown rendering | 1 |
| `doctor.py` | environment and boundary verification | 1 |
| `cli.py` | argparse dispatch; the stable command boundary | 1 |
| `inventory.py` | walk with configurable exclusions; classify kind and language; detect generated code, tests, manifests | 2 |
| `symbols.py` | Symbol / Import / Ref / Base / Extraction data model with confidence | 2 |
| `extractors/` | `python_ast.py` (stdlib AST, CONFIRMED); `js_ts.py` (regex heuristics, INFERRED); others -> UNKNOWN | 2 |
| `index.py` | incremental JSON index in `.lord/index.json` keyed by size/mtime/sha1 | 2 |
| `search.py` | whole-identifier search; ripgrep if present, pure-Python fallback | 2 |
| `query.py` | def / refs / related / deps / dependents / tests-for / symbols | 2 |
| `reuse.py` | reuse decision ladder (reuse / extend / refactor / create); duplicate symbols, values, near-duplicate bodies, thin wrappers | 3 |
| `change_surface.py` | Git-based diff measurement, new symbols, name collisions, resemblance, churn, unrelated files, bloat signal | 3 |
| `graph.py` | relationship graph over the index: defines, imports, calls, references, extends, implements, tests, configures; per-edge confidence | 4 |
| `impact.py` | impact report (callers, indirect chains, callees, dependents, types, tests, config, boundary, consequences) and root-cause trace worksheet | 4 |
| `review.py` | `brief` (one-call pre-edit synthesis); `verify` (change surface, test coverage of the change, unresolved markers, detected test/lint/build steps with real results, verdict, recorded for reuse); `reconcile` (a reply's verification claims against LORD's executed record) | 5, 8B |
| `markers.py` | unfinished-work markers added by a change, in marker syntax only (code comments via `tokenize` for Python, comment syntax elsewhere; line-leading `TODO:` in prose outside code fences); new untracked files scanned in full | 8B |
| `session.py` | transient session state in `.lord/session/`: investigation activity log (with the files each command surfaced), the task frame (`task.json`: request, intent, target, assumptions with confirmation source, questions, decision state, confirmation gate), the last executed verification with its tree signature, per-conversation counters and caches, hook diagnostics | 6, 8A.1, 8B |
| `hooks.py` | Antigravity hook decisions (pre-edit gate, task gate, completion gate, once-per-conversation reminder, change-surface / bypass / assumption advisories) with fail-safe dispatch | 6, 8A.1 |
| `plugin/lord_hook.py` | the single launcher: `python -m lord_hook <event>`, run by Antigravity from the plugin folder; finds the runtime from its own file (`<plugin>/runtime` installed, `<repo>` in a checkout); never exits non-zero; imports on any Python 3 | 6, 8A.1, 8B |
| `plugin.py` | packaging: validate the plugin source (documented manifest fields, hooks, rules, skills, agents, no machine paths, no secrets, stdlib-only runtime); install / update / roll back / uninstall a self-contained bundle; optional `python -m lord` registration | 8B |
| `memory.py` | durable memory store (`docs/state/memory.jsonl`): schema and trust validation, supersession, key conflicts, deterministic retrieval; handoff (`docs/state/handoff.json`) | 7 |
| `context.py` | capped context assembly: handoff, relevant memory, brief, matching skills, always-on rules | 7 |
| `acceptance.py` | demo evaluation in a separate workspace: export, baseline ground truth, per-scenario checks each labelled confirmed fact / heuristic signal / human review required, evidence records with the task decisions and the verification reconciliation | 8A, 8B |

Design rules for the core: prefer the standard library; deterministic and
reproducible; Windows-first via `pathlib`; every analysis distinguishes
CONFIRMED / INFERRED / UNKNOWN; unsupported input is reported as UNKNOWN, never
as an empty result.

### 3.2 Antigravity plugin (`plugin/`)

Tracked product source that binds LORD to Antigravity as one plugin
(antigravity.google/docs/plugins; decision record 0003). `lord plugin
install` builds a self-contained bundle from it plus the runtime:

| Mechanism | Source | Installed (`~/.gemini/config/plugins/lord/` or `<ws>/.agents/plugins/lord/`) | LORD use |
|---|---|---|---|
| Manifest | `plugin/plugin.json` (`name`, `description` only: the documented schema) | `plugin.json` | identity; version lives in `lord.__version__` and `install.json` |
| Rules | `plugin/rules/*.md` (frontmatter `trigger`, `description`; 12k chars max) | `rules/` (loaded when the plugin is enabled) | the always-on operating contract |
| Skills | `plugin/skills/<name>/SKILL.md` | `skills/` | executable procedures: pre-edit audit, reuse audit, impact, critical review, memory |
| Custom subagents | `plugin/agents/<name>.md` | `agents/` | specialists; documented for Antigravity 2.0 and the CLI, not verified in the IDE |
| Hooks | `plugin/hooks.json` + `plugin/lord_hook.py` | same files, unchanged | pre-edit gate, confirmation boundary, completion gate, advisories (section 7) |
| Runtime | `lord/` | `runtime/lord/` | the deterministic core; `lord-harness.pth` in the Python user site makes `python -m lord` import it; `lord_cli.py` is the fallback |
| MCP | none | none | LORD needs no MCP server |

Global vs workspace: the plugin (rules, skills, agents, hooks, launcher,
runtime) is the product and is installed once; everything project-specific
lives in the workspace the hook payload names: `.lord/` (index, session,
task frame, hook log; ignores itself) and `docs/state/` (durable memory,
only when written). The bundle carries no memory, evidence, demo or tests.

Rules hold principles and stay short. Skills hold procedures. Agents hold
roles. The contract is written once and referenced, never duplicated.

Cross-tool pointers: `AGENTS.md` (read by several agent tools) summarises the
contract in seven lines and points at the canonical rule; `CLAUDE.md` imports
`AGENTS.md`. No `GEMINI.md` copy is kept at the workspace root because the
plugin's always-on rule already covers Antigravity.

### 3.3 Specialist agent architecture

Specialists exist to protect the primary agent's context: deep investigation
happens in a subagent, and only structured findings return.

```
SPECIALIST DEEP INVESTIGATION -> STRUCTURED FINDINGS -> PRIMARY AGENT SYNTHESIS
```

Roles (all shipped, `plugin/agents/`):

| Agent | Question it answers | Backing commands | Writes code? |
|---|---|---|---|
| lord-investigator | where is it defined, used, related; what is the context | def, refs, related, deps, dependents, tests-for, symbols | no |
| lord-reuse-auditor | does this already exist or can it be composed from existing pieces; is a new file justified | reuse, related, duplicates | no |
| lord-impact-analyst | what breaks, what depends on it, which tests and config; where is the cause | impact, graph, trace | no |
| lord-skeptical-reviewer | is the request the right change given the evidence; one objection at most | brief, impact, reuse, trace | no |
| lord-verification-reviewer | is the implementation actually complete and in scope | verify --run, diff, duplicates | no |

The `lord-critical-review` skill is the decision sequence (understand
intent -> inspect -> validate assumptions -> search existing -> trace
cause/impact -> risks -> smallest change -> clarify? -> plan -> implement ->
verify -> review diff -> report) and says when to delegate to which
specialist and how to push back: EVIDENCE -> CONSEQUENCE -> RECOMMENDATION
-> USER DECISION, one objection, stated once, then the user's choice stands.

Every specialist output uses the same shape as `lord.report.Finding`:
claim, evidence, confidence, consequence, recommendation.

## 4. Boundaries

- **Workspace boundary**: exactly one root, resolved by `lord.paths`. Nothing
  reads or writes outside it. `safe_join` refuses escaping paths.
- **Git boundary**: the Git root must equal the workspace root; `doctor`
  reports an error otherwise.
- **Source vs generated state**: `plugin/`, `lord/`, `tests/`, `docs/` are
  source. `.lord/` is machine-local derived state (index, caches) and is
  ignored; it is rebuilt, never authored.
- **Durable vs transient state**: durable engineering knowledge lives in
  versioned, human-readable files: `docs/state/memory.jsonl` (one fact per
  line), `docs/state/handoff.json` (unfinished work) and `docs/decisions/`
  (long-form rationale that memory items point at). Transient session state
  (investigation evidence, hook logs, counters, the index) lives under
  `.lord/` and is ignored. Raw conversation logs are never stored anywhere.
- **Provider boundary**: no provider SDK, no API key, no network call in the
  core. Enforced by `tests/test_foundation.py`.

## 5. Context engineering

LORD is built around progressive retrieval. The model receives concise
structure first (inventory summary, relevant symbols, targeted relationships,
relevant files and tests) and fetches detail only when needed. The
deterministic graph answers "where should I look"; the source answers "what is
implemented"; the model answers "what does it mean". Graph output never
replaces reading the source.

## 6. Repository intelligence: what is confirmed, heuristic, unsupported

| Level | Capability |
|---|---|
| CONFIRMED | Python: functions, methods, classes, module constants/variables (with values), route decorators, imports resolved to workspace files, calls, name references, class bases; graph edges through import bindings or same-file definitions; file inventory and exclusions; Git diff facts |
| HEURISTIC (INFERRED) | cross-file name-based call/reference resolution; config files naming symbols; duplicate and resemblance similarity; bloat reasons; JavaScript/TypeScript: declarations, class methods, interfaces/types/enums, imports with relative resolution, exports, calls, Express-style routes; identifier text matches in any text file; `related` behaviour search (term overlap plus a small synonym table); external/unresolved imports |
| UNSUPPORTED (UNKNOWN) | every other language: no symbols or relationships; files still appear in the inventory and in text search, and every report says so |
| FUTURE | tree-sitter or LSP-backed extractors; type information; cross-language call resolution |

## 7. Enforcement (Phase 6)

LORD core produces evidence; hooks make workflow decisions from it. The hook
layer is `lord/hooks.py` plus a 40-line launcher, and it reuses the session
activity log written by `brief`, `reuse` and the other investigation
commands, plus `verify` and `diff`, unchanged.

Intervention tiers (Phase 8A.1 made them explicit):

| Level | Name | Mechanism | Used for |
|---|---|---|---|
| 0 | information | command output; the once-per-conversation PreInvocation reminder (silent when the conversation already investigated) | what LORD knows; how to start |
| 1 | advisory | PostInvocation `injectSteps` ephemeral message, each once | unconfirmed material assumption (after an edit); bypass signal; change larger than the task |
| 2 | ask | PreToolUse `ask` | task-level evidence only; a code edit under an unconfirmed material assumption (the confirmation boundary): the user decides at the edit |
| 3 | block | PreToolUse `deny`; Stop `continue` (capped) | no investigation at all; an open question; a failing test |

| Hook | Situation | Evidence | Level | Decision |
|---|---|---|---|---|
| PreInvocation | first step of a conversation with no LORD investigation in the window | activity log, per-conversation marker | 0 | one ephemeral reminder naming `context` and `task ask`; nothing afterwards |
| PreToolUse on `write_to_file`, `replace_file_content`, `multi_replace_file_content` | non-code file (docs, config, tests); edit of at most 3 lines; path outside the workspace | file kind and edit size from the tool arguments | audit | `allow` |
| | any code edit (trivial ones included) while the task frame has an open question | `.lord/session/task.json` | 3 | `deny` naming the question and `lord task resolve` |
| | a code edit the evidence rules would allow or ask, while the task frame holds a material assumption nobody confirmed | `task.json` | 2 | `ask` naming the assumption; the gated file changing afterwards records the user's approval (`source: edit-gate approval`); an unchanged file means rejected, and the next edit asks again. Never applied to an edit the evidence rules deny |
| | code file whose path or symbols were named by a LORD investigation command in the last 45 minutes, or surfaced by its output (callers, dependents, tests of a `context`/`brief` target) | `.lord/session/activity.jsonl` (`files`) | audit | `allow` |
| | code file, only task-level investigation (`reuse`, `brief`, `context` on something that did not surface this file) | activity log | 2 | `ask` (user decides; the reason names the file) |
| | code file, no LORD investigation at all in the window | activity log | 3 | `deny` with the exact command to run |
| | new code file without a `context`, `reuse` or `brief` in the window | activity log | 3 | `deny` (reuse -> extend -> refactor -> create) |
| Stop (fully idle, code files changed) | a detected verification step FAILED, for example pytest exit 1 | `verify --run` with real exit codes, cached per working-tree signature; a `verify --run` the agent already ran on the same tree is reused, not repeated | 3, bounded | `continue` with the failing output, at most 2 consecutive times per conversation |
| | untested change, TODO markers, bloat signal, unavailable tools | heuristic or advisory | audit | allow, logged |
| PostInvocation (code files changed, tree changed since last check) | bloat signal HIGH, or the first rise to ELEVATED | `diff` reasons | 1 | ephemeral message asking whether the change became larger than the task |
| | a call that was unconditional at HEAD is now guarded by a new parameter, or a shared call was removed (`invariant-bypass`, `shared-call-removed`) | AST comparison of the modified Python file against HEAD | 1 | ephemeral message, once per finding |
| | the task frame holds a material assumption the user has not confirmed | `task.json` | 1 | ephemeral message, once per conversation |

Why these tiers: a `deny` is issued only when the evidence is a plain fact
(no investigation command ran; a question the agent itself recorded is
unanswered; the test suite failed). Everything heuristic (resemblance,
modified copies, bypass shapes, unrelated files, import-based coverage) is
surfaced, never enforced, because hard gates that fire on heuristics train
agents to ignore them.

Evidence semantics: a command's evidence is its target plus the workspace
files named by the investigation part of its output: definition,
references, callers, dependents, tests and reuse candidates for the stated
intent. `context pkg/validators.py` therefore makes the validator, its
dependents and its tests editable, and `context demo/ --intent "..."` makes
the files its reuse candidates named editable (observed live in Baseline B,
T02: the export module was a candidate for the intent and its edit was
allowed). Files that appear only in the handoff, memory items, the rules or
skills listing, the workspace-state listing or the model's own intent text
are not evidence. `context` is an investigation command (it contains the
brief); before Phase 8A.1 it was not counted, which denied a correctly
investigated edit in the live evaluation. A symbol-level `context` does not
surface the files its callees live in (Baseline B, T03: `context
ReportService.monthly_summary` left `dates.py` at the ask tier).

Clarification semantics (Phase 8B): LORD cannot tell whether a request is
ambiguous; the model has to notice. LORD gives the model a place to record
it (`task ask` for a question, `task assume --material` for a reading it
proceeds on), turns that record into a user decision at the next code edit
(deny while a question is open; ask while a material assumption is
unconfirmed), and preserves who decided: `edit-gate approval` (observed) or
`model-reported` (`task confirm`, the model's word). `lord task show` prints
the decision state: `blocked`, `awaiting-confirmation` or `clear`. Cosmetic
assumptions never gate. An ambiguity the model never records is invisible.

Verification semantics: `verify` separates facts from heuristics. The
verdict is NOT VERIFIED only for facts: a failing, timed-out or unavailable
step, no detected step, steps not executed, or an added unfinished-work
marker in marker syntax (`lord/markers.py`: a comment that starts with the
marker, or a line-leading `TODO:` in prose outside code fences; prose that
discusses markers, string literals and fixture data are not markers; new
untracked files are scanned in full).
The bloat signal and import-based test coverage are advisories printed
beside the verdict ("Advisories (heuristic, ...)") and must be justified in
the report. Before this split, correct and fully tested changes were
labelled NOT VERIFIED in five of eight Baseline B runs. The change surface
behind the advisory, in `verify` and in the PostInvocation hook, is measured
over the sub-project(s) the changed code lives in (`project_scope`), so
untracked records elsewhere in the workspace are not counted.

Reporting contract (Phase 8B): `verify --run` records its executed result
with the working-tree signature (`.lord/session/verification.json`). A
model's reply is a claim; `lord verify --reconcile <reply>` and `acceptance
record --reply` compare it with that record: VERIFIED / NOT VERIFIED come
only from LORD's executed checks on the current tree; UNVERIFIED CLAIM when
LORD has no fresh record but the reply claims success; NO VERIFICATION when
neither exists. A claim never changes the status; a disagreement is listed
as a contradiction.

Failure handling: every code path ends in valid JSON and exit code 0. An
internal error returns the event's permissive default (`allow` or `{}`) and
is logged to `.lord/session/hooks.log` with the exception. This matters
because Antigravity denies a tool call whose PreToolUse hook exits non-zero
or prints malformed output (observed live: Google's bundled telemetry hook,
broken by Windows path quoting, denied every tool call in the CLI). Guards:
`LORD_HOOKS_DISABLED=1` disables decisions, `LORD_HOOK_ACTIVE=1` prevents
recursion, Stop has a time budget and a continuation cap, and Antigravity
itself caps consecutive Stop continuations (CLI changelog).

Windows execution: Antigravity tokenises the command string itself and keeps
literal quotes (observed), so hook commands contain no quotes and no
absolute path. Hooks run from the folder holding hooks.json (shipped docs;
workspace hooks confirmed live in Phase 8A, plugin hooks observed in the
Phase 6 CLI run), so the single launcher lives next to the plugin's
hooks.json (`plugin/lord_hook.py`) and locates the runtime from its own
file, never from the cwd. The launcher logs the cwd it was started from;
`doctor` checks every hooks.json that applies (workspace, workspace plugin,
user, global plugin), reports a missing launcher as an error and LORD
hooks configured twice as a warning.

Trust: workspace customisations (`.agents/hooks.json`, rules, skills,
agents) load only in a trusted workspace; whether a global plugin's hooks
also require a trusted workspace is not documented. CLI print mode never trusts, so `agy -p` cannot exercise
workspace hooks; the IDE prompts for trust when a folder is opened.

## 8. Durable memory and context (Phase 7)

`docs/state/memory.jsonl` holds repository engineering knowledge, one JSON
object per line, sorted by id on save so every Git diff is one line per
fact. It is not personal memory and not a transcript.

| Field | Meaning |
|---|---|
| `id` | `M-0001`, sequential, stable |
| `category` | `decision`, `fact`, `discovery`, `trap`, `convention`, `unresolved`, `verification` |
| `statement` | one line, at most 300 characters |
| `evidence` | file:line, command, commit, document; required for `confirmed` and `evidenced` |
| `status` | `confirmed`, `evidenced`, `inferred`, `temporary` (needs `expires`), `unresolved`, `superseded`, `deprecated` |
| `created`, `updated` | ISO dates |
| `paths`, `symbols`, `tags` | retrieval handles |
| `key` | optional subject; two current items with one key are a conflict |
| `supersedes`, `superseded_by` | history links; superseded items are kept |

Trust model: retrieval maps `confirmed` to confidence `confirmed`,
`evidenced`/`inferred`/`temporary` to `inferred`, `unresolved` to
`unknown`. Superseded, deprecated and expired items are hidden unless
`--all` is passed. `memory check` reports invalid lines (ignored, never
loaded), dangling links, expired temporaries, inferred facts and
conventions, key conflicts and open items. Knowledge changes through
`supersede` (old item kept with `superseded_by`) or `update` (status and
evidence on a current item); history is never rewritten.

Retrieval is deterministic: exact symbol (10) > path equality (6) > path
containment (4) > tag (4) > category (2) > shared statement terms (1 each),
ties broken by most recent update then id. Filters: category, status, tag,
path, symbol, text. Semantic retrieval can be added behind the same
`Store.query` interface later; nothing else in LORD depends on how matching
is done.

`docs/state/handoff.json` is one compact document: doing, done, remaining,
discovered, decided, next, verification (attachable from `verify`), plus the
branch and commit it was written at. It is merged on write, replaced on
request, cleared when the work is complete; Git keeps its history.

`lord context <target> --intent` is the context-engineering interface:
handoff (1), relevant memory (up to 6, by symbol, path and intent terms), the
brief (up to 18 findings), skills whose descriptions match the intent (3) and
the always-on rules. Every section names the command that gives more. It
composes existing pieces; it is not an autonomous context engine.

## 9. Evaluation environment (Phase 8A; separate workspace since 8B)

The demo template (`tests/fixtures/demo_workspace/demo/`, excluded from
LORD's own index) is evaluated only as a separate Git repository created by
`lord acceptance workspace --out <dir>` outside the LORD repository: no LORD
source, memory, session state, evidence or oracles in it, and the `demo/`
folder name kept so the scenario prompts stay unchanged. `acceptance
check/record --workspace <dir>` observe it; evidence and the oracle stay in
the LORD repository (the oracle imports the demo named by
`LORD_ACCEPTANCE_DEMO`).

The demo is a small standard-library ledger application (web page -> API
handlers -> services -> shared utilities and configuration -> repository,
with tests) designed to expose shallow agents: a text helper that a service
does not use yet, a money formatter the export does not import, shared
constants with twelve consumers, validators not named as a request would
phrase them, an abstraction that a plausible request would bypass, and a
planted defect whose symptom appears in the report while the cause lives
in a shared date helper three layers down.

`docs/acceptance/` holds the eight scenarios with observable expectations
and oracles (`PHASE-8A-TEST-PLAN.md`), the eleven-dimension scorecard, the
manual Antigravity/Gemini procedure, LORD's own analysis of the demo as
ground truth (`baseline/`, generated by `lord acceptance baseline`), the
private root-cause oracle tests (excluded from the index by `lord.toml`),
and versioned evidence records (`evidence/`, created by `lord acceptance
record` and validated by the test suite). `lord acceptance check --workspace
<dir> --test <ID>` runs the deterministic post-conditions of a scenario
against that workspace; each says whether it is a confirmed fact, a
heuristic signal, or needs human review.

Two capabilities were fixed while establishing the ground truth: `verify`
now detects and runs verification steps per sub-project (a change under
`demo/` runs the demo's tests, not the root suite), and graph resolution,
behaviour search and duplicate detection stay inside one project root with
rarity-weighted term matching, so the demo's analysis is not polluted by
LORD's own symbols.

## 10. Current limitations (after Phase 8B)

- Call resolution is name-based across files (inferred); only import
  bindings and same-file definitions are confirmed. Dynamic dispatch,
  reflection and string-based lookups are invisible.
- Duplicate detection is token-based (exact and identifier-normalised
  shingles, plus a containment measure for copies that were then edited:
  shared shingles over the smaller body, at least 60% with at least 40
  tokens); it finds copies, renamed copies and modified copies, not semantic
  equivalents. A copy rewritten beyond that overlap is invisible.
- Bypass detection is AST-based and Python-only: a call unconditional at
  HEAD that becomes conditional on a new parameter (statement, ternary or
  short-circuit guard), or a shared call removed. A check disabled through
  data, configuration or a different function is not seen.
- The `related` search and memory retrieval are lexical; they find
  candidates, they do not prove equivalence or bridge synonyms.
- Hooks fired live inside a trusted Antigravity IDE session (Phase 8A:
  PreToolUse deny/allow, PostInvocation advisory, Stop continuation
  observed; cwd `.agents`). PreInvocation is validated against the
  documented payload shape and fires live only from Phase 8A.1's Baseline B
  onwards. Plugin hooks, rules and skills in the IDE are validated by the
  separate-workspace probe (docs/acceptance/MANUAL-ANTIGRAVITY-GEMINI.md
  section 3); whether the IDE loads plugin `agents/` remains unconfirmed.
- The task frame is filled by the model (`lord task ask/assume`) or by
  `context --intent`; LORD cannot detect an ambiguity the model never
  records. The open-question gate and the confirmation boundary enforce the
  model's own record, not the existence of one. Approval at the boundary is
  inferred from the gated file changing (a shell command that rewrote it
  would read as approval), and a model can `task confirm` without asking;
  that confirmation is labelled model-reported.
- The marker detector recognises marker syntax: a marker written mid-comment
  (`# fix later, TODO`) or in a language whose comments are not `#`, `//`,
  `/* */`, `--` or `;` is not seen. Files under a fixtures/testdata folder
  are treated as test data.
- Import-based test coverage cannot credit tests that drive code through
  subprocesses or reach it through shared fixtures (`conftest.py`); such
  files are reported as "without an importing test" (an advisory).
- The component heuristic behind "unrelated file" follows imports, so a test
  that exercises a change through another layer is reported as unrelated
  (Baseline B, T07 and T08). It is an advisory, never a verdict.
- Nothing writes memory automatically; the write policy is a judgement
  guided by the `lord-memory` skill, and the schema enforces only structure
  and evidence.
