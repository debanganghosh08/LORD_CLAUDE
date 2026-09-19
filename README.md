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
python -m lord doctor          # verify environment and workspace boundary
python -m lord --help          # list available commands
python -m pytest               # run the LORD test suite (needs pytest)
```

Inside Antigravity, opening this workspace activates
`.agents/rules/lord-operating-contract.md` (always on), the
`lord-pre-edit-audit` skill and the `lord-investigator` subagent.

## Repository layout

```
.agents/            Antigravity adapter: rules/, skills/, agents/ (tracked product source)
lord/               LORD core, Python standard library only
tests/              pytest suite and fixtures
docs/               architecture, roadmap, security, decisions, phase reports
AGENTS.md           cross-tool pointer to the contract; CLAUDE.md imports it
lord.toml           optional per-project configuration (exclusions)
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
