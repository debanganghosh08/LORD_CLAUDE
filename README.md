# LORD

**MODEL + LORD = senior-engineer-style coding behaviour.**

LORD is a portable, model-agnostic engineering harness for IDE-hosted coding
agents. Its job is to make whichever model is currently running inside the IDE
(Claude, Gemini, GPT, or a future model) behave like a careful, experienced
engineer who is invested in the long-term health of the repository: explore
before editing, reuse before creating, keep diffs minimal, trace root causes,
push back with evidence, and verify before claiming completion.

The primary target environment is [Google Antigravity](https://antigravity.google/docs/home/),
through its rules, skills, custom subagents, hooks and plugins. The core is
kept separate from that adapter so other environments can be supported later.

## What LORD is

- an engineering behaviour contract (rules) with an executable checklist (skills);
- deterministic, standard-library-only repository tooling (`python -m lord`);
- a repository-forensics and code-intelligence layer (Phase 2);
- a reuse-first / anti-bloat engine and change-surface analysis (Phase 3);
- an impact and root-cause analysis layer (Phase 4);
- narrowly scoped specialist agents that return structured evidence (Phase 5);
- durable engineering state kept apart from transient runtime state;
- a distributable adapter for Antigravity.

## What LORD is not

- not an LLM API wrapper, SDK or cloud service: **LORD never calls a model API
  and never needs an API key**;
- not an IDE, a chatbot or a giant system prompt;
- not a hard-coded imitation of any vendor's internals;
- not a claim that every model becomes identical. Reasoning quality remains
  model-dependent; LORD makes the surrounding environment strong enough that
  model differences do less damage and strong models do better work.

## Model vs harness

| Model supplies | LORD supplies |
|---|---|
| reasoning, judgement under ambiguity | workspace boundary and path safety |
| code generation quality | repository inventory, symbol index, relationships |
| planning and tool selection | reuse candidates and duplicate detection |
| instruction following, error recovery | change-surface / bloat measurement |
| | impact traversal and root-cause chains |
| | structured findings with explicit confidence |
| | verification steps and durable state |

## Quick start

Requirements: Python 3.11+ and Git. ripgrep is recommended but optional.

```
python -m lord doctor                    # verify environment and workspace boundary
python -m lord inventory                 # repository shape: kinds, languages, exclusions
python -m lord index                     # build/refresh .lord/index.json (incremental)
python -m lord def validate_email        # where is it defined
python -m lord refs validate_email       # who uses it (confirmed vs text matches, callers)
python -m lord related "validate email"  # existing implementations by behaviour
python -m lord deps src/users.py         # what a file imports; `dependents` for the reverse
python -m lord tests-for validate_email  # tests that touch it
python -m lord reuse "validate email" --name EmailChecker   # reuse -> extend -> refactor -> create
python -m lord duplicates                # duplicate symbols, values, bodies, thin wrappers
python -m lord diff --scope <path|term>  # change surface + bloat signal (never size alone)
python -m lord impact validate_email     # callers, dependents, subtypes, tests, config, boundary, consequences
python -m lord trace UserService.create --observed "..."   # root-cause worksheet: candidate causes + upstream
python -m lord graph pkg/users.py        # inspect one node's edges
python -m lord brief validate_email --intent "..."   # one-call pre-edit synthesis
python -m lord verify --run --scope <path>            # completion check with real test results
python -m lord context validate_email --intent "..."  # handoff + memory + brief + skills + rules, capped
python -m lord memory query --path src/users.py       # durable decisions, traps, conventions for an area
python -m lord memory add --category trap --statement "..." --evidence "file:line"   # record what must outlive the session
python -m lord handoff write --doing "..." --remaining "..." --from-verify           # resume point for unfinished work
python -m lord acceptance prompts                     # demo evaluation scenarios; also baseline | check --test T03 | record --test T03 --model <label>
python -m lord --help                    # all commands; add --json for machine output
python -m pytest                         # run the LORD test suite (needs pytest)
```

Every result carries a confidence: `confirmed` (parsed source), `inferred`
(heuristic or text match) or `unknown` (analysis unavailable for that
language). LORD never turns "could not analyse" into "nothing found".

Inside Antigravity, opening this workspace activates
`.agents/rules/lord-operating-contract.md` (always on), the skills
`lord-critical-review`, `lord-pre-edit-audit`, `lord-reuse-audit` and
`lord-impact-analysis`, and five read-only specialist subagents:
`lord-investigator`, `lord-reuse-auditor`, `lord-impact-analyst`,
`lord-skeptical-reviewer`, `lord-verification-reviewer`. In a trusted
workspace `.agents/hooks.json` also installs three hooks: a pre-edit gate on
code-file writes (denies when no LORD investigation ran, asks when only a
task-level one did), a completion gate that blocks "done" while a detected
test step fails, and a change-surface advisory when the bloat signal rises.

## Repository layout

```
.agents/            Antigravity adapter: rules/, skills/, agents/ (tracked product source)
lord/               LORD core, Python standard library only
tests/              pytest suite and fixtures
docs/               architecture, roadmap, security, decisions, phase reports
docs/state/         durable engineering memory (memory.jsonl) and handoff (handoff.json), versioned
docs/acceptance/    evaluation: test plan, scorecard, manual Antigravity/Gemini guide, baseline ground truth, evidence records
demo/               small ledger application used as the evaluation environment (reuse traps, a planted root-cause bug)
AGENTS.md           cross-tool pointer to the contract; CLAUDE.md imports it
lord.toml           optional per-project configuration (exclusions)
lord_hook.py        hook launcher (identical copy in .agents/); docs/ARCHITECTURE.md section 7
.lord/              generated machine-local state (index, caches); ignored by Git
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md): layers, boundaries, interfaces, state model, limitations
- [Roadmap](docs/ROADMAP.md): phases 1-9
- [Security policy](docs/SECURITY.md)
- [Contributing and Git policy](CONTRIBUTING.md)
- [Decision records](docs/decisions/)
- [Phase reports](docs/reports/)

## Status

Early stage. See the phase reports for what is built, tested and known to be
missing. LORD is honest about its limits: it does not claim semantic
understanding it cannot back with evidence.

## License

MIT. See [LICENSE](LICENSE).
