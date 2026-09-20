# LORD Architecture

## 1. Purpose

LORD turns an IDE-hosted coding model into something that behaves like a
senior engineer who owns the repository. It does this by surrounding the model
with evidence, constraints, deterministic tooling and verification, not by
depending on any one model or provider.

```
USER INTENT
   |
LORD OPERATING CONTRACT        .agents/rules  (always-on behaviour contract)
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
| `review.py` | `brief` (one-call pre-edit synthesis) and `verify` (change surface, test coverage of the change, unresolved markers, detected test/lint/build steps with real results, verdict) | 5 |
| `session.py` | transient session state in `.lord/session/`: investigation activity log, per-conversation counters and caches, hook diagnostics | 6 |
| `hooks.py` | Antigravity hook decisions (pre-edit gate, completion gate, change-surface advisory) with fail-safe dispatch | 6 |
| `lord_hook.py` (root and `.agents/`) | identical launchers: `python -m lord_hook <event>` from either working directory; never exits non-zero | 6 |
| `memory.py` | durable memory store (`docs/state/memory.jsonl`): schema and trust validation, supersession, key conflicts, deterministic retrieval; handoff (`docs/state/handoff.json`) | 7 |
| `context.py` | capped context assembly: handoff, relevant memory, brief, matching skills, always-on rules | 7 |

Design rules for the core: prefer the standard library; deterministic and
reproducible; Windows-first via `pathlib`; every analysis distinguishes
CONFIRMED / INFERRED / UNKNOWN; unsupported input is reported as UNKNOWN, never
as an empty result.

### 3.2 Antigravity adapter (`.agents/`)

Tracked product source that binds LORD to Antigravity's current customisation
mechanisms (documented at antigravity.google/docs):

| Mechanism | Location | LORD use |
|---|---|---|
| Rules | `.agents/rules/*.md` (frontmatter `trigger`, `description`; 12k chars max) | the always-on operating contract |
| Skills | `.agents/skills/<name>/SKILL.md` (+ `scripts/`, `resources/`) | executable procedures: pre-edit audit, later reuse audit, impact, verification |
| Custom subagents | `.agents/agents/<name>.md` (frontmatter `name`, `description`, `tools`, `model`, `subagent`) | narrowly scoped specialists returning structured findings |
| Hooks | `.agents/hooks.json` (`PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop`; command handlers with JSON on stdin/stdout) | pre-edit gate, completion gate, change-surface advisory (section 7) |
| Plugins | `.agents/plugins/<name>/plugin.json` or `~/.gemini/config/plugins/` | Phase 8 portable distribution |

Rules hold principles and stay short. Skills hold procedures. Agents hold
roles. The contract is written once and referenced, never duplicated.

Cross-tool pointers: `AGENTS.md` (read by several agent tools) summarises the
contract in seven lines and points at the canonical rule; `CLAUDE.md` imports
`AGENTS.md`. No `GEMINI.md` copy is kept at the workspace root because the
`.agents/rules` always-on rule already covers Antigravity.

### 3.3 Specialist agent architecture

Specialists exist to protect the primary agent's context: deep investigation
happens in a subagent, and only structured findings return.

```
SPECIALIST DEEP INVESTIGATION -> STRUCTURED FINDINGS -> PRIMARY AGENT SYNTHESIS
```

Roles (all shipped, `.agents/agents/`):

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
- **Source vs generated state**: `.agents/`, `lord/`, `tests/`, `docs/` are
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

| Hook | Situation | Evidence | Tier | Decision |
|---|---|---|---|---|
| PreToolUse on `write_to_file`, `replace_file_content`, `multi_replace_file_content` | non-code file (docs, config, tests); edit of at most 3 lines; path outside the workspace | file kind and edit size from the tool arguments | audit | `allow` |
| | code file whose path or symbols were named by a LORD investigation command in the last 45 minutes | `.lord/session/activity.jsonl` | audit | `allow` |
| | code file, only task-level investigation (`reuse`, `brief`, `impact` on something else) | activity log | soft | `ask` (user decides; the reason names the file) |
| | code file, no LORD investigation at all in the window | activity log | hard | `deny` with the exact command to run |
| | new code file without a `reuse` or `brief` in the window | activity log | hard | `deny` (reuse -> extend -> refactor -> create) |
| Stop (fully idle, code files changed) | a detected verification step FAILED, for example pytest exit 1 | `verify --run` with real exit codes, cached per working-tree signature | hard, bounded | `continue` with the failing output, at most 2 consecutive times per conversation |
| | untested change, TODO markers, bloat signal, unavailable tools | heuristic or advisory | audit | allow, logged |
| PostInvocation (code files changed, tree changed since last check) | bloat signal HIGH, or the first rise to ELEVATED | `diff` reasons | soft | `injectSteps` ephemeral message asking whether the change became larger than the task |

Why these tiers: a `deny` is issued only when the evidence is a plain fact
(no investigation command ran; the test suite failed). Everything heuristic
(resemblance, unrelated files, import-based coverage) is surfaced, never
enforced, because hard gates that fire on heuristics train agents to ignore
them.

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
literal quotes (observed), so hook commands contain no quotes. The working
directory is undocumented and plugin hooks demonstrably run from their
hooks.json folder, so the launcher exists at both the workspace root and
`.agents/` and locates the `lord` package from its own file, never from the
cwd. The launcher logs the cwd it was started from.

Trust: workspace `.agents/hooks.json` (and rules, skills, agents) load only in
a trusted workspace. CLI print mode never trusts, so `agy -p` cannot exercise
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

## 9. Current limitations (after Phase 7)

- Call resolution is name-based across files (inferred); only import
  bindings and same-file definitions are confirmed. Dynamic dispatch,
  reflection and string-based lookups are invisible.
- Duplicate detection is token-based (exact and identifier-normalised
  shingles); it finds copies and renamed copies, not semantic equivalents.
- The `related` search and memory retrieval are lexical; they find
  candidates, they do not prove equivalence or bridge synonyms.
- Hooks are validated locally against live-captured payload shapes; they
  have not yet fired inside a trusted Antigravity session (the Phase 6
  report lists the exact blockers and the manual test plan). The launcher
  working directory is hedged with two copies.
- Import-based test coverage cannot credit tests that drive code through
  subprocesses.
- Nothing writes memory automatically; the write policy is a judgement
  guided by the `lord-memory` skill, and the schema enforces only structure
  and evidence.
