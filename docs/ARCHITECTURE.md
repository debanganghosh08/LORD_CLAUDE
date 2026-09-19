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
| inventory, symbols, extractors, index, query | repository forensics | 2 |
| reuse, change_surface | reuse-first and anti-bloat analysis | 3 |
| graph, impact | relationship graph, impact and root-cause chains | 4 |

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
| Hooks | `.agents/hooks.json` (`PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop`; command handlers with JSON on stdin/stdout) | Phase 6 enforcement and quality gates |
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

Roles (Phase 1 ships the first; Phase 5 completes the set):

| Role | Question it answers | Writes code? |
|---|---|---|
| lord-investigator | where is it defined, used, related; what is the context | no |
| reuse auditor | does this already exist or can it be composed from existing pieces | no |
| impact analyst | what breaks, what depends on it, which tests and config | no |
| skeptical reviewer | is the request the right change given the evidence | no |
| verification reviewer | is the implementation actually complete and in scope | no |

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
- **Durable vs transient state**: durable engineering knowledge (decisions,
  discoveries, unresolved issues, conventions) lives in versioned, human-
  readable files under `docs/decisions/` and, from Phase 7, a structured
  `docs/state/`. Transient session state lives under `.lord/`. Raw
  conversation logs are never stored.
- **Provider boundary**: no provider SDK, no API key, no network call in the
  core. Enforced by `tests/test_foundation.py`.

## 5. Context engineering

LORD is built around progressive retrieval. The model receives concise
structure first (inventory summary, relevant symbols, targeted relationships,
relevant files and tests) and fetches detail only when needed. The
deterministic graph answers "where should I look"; the source answers "what is
implemented"; the model answers "what does it mean". Graph output never
replaces reading the source.

## 6. Current limitations (Phase 1)

- Repository intelligence, reuse analysis and impact analysis are not yet
  built; the rules and skill reference them as future commands.
- Enforcement is advisory: no hooks are installed yet (Phase 6).
- Antigravity behaviour is taken from its public documentation; the adapter
  has not been exercised inside a live Antigravity session in this phase.
- Windows compatibility of Antigravity hooks (shell used for `command`
  handlers) is not documented; Phase 6 must verify it.
