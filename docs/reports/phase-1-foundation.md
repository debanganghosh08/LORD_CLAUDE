# Phase 1 Report: Foundation

Date: 2026-09-20

## Objective

Establish the architectural foundation of LORD: the workspace and Git
boundary, the GitHub remote, the ignore policy, a standard-library-only core
with a stable command boundary, the Antigravity adapter structure (rules,
skills, agents), documentation, decision records and meaningful tests.

## Reconnaissance findings

- Workspace `LORD_Claude_Clone` was empty; no Git repository existed in it or
  in any parent directory. Sibling reference folders were read, not touched.
- The GitHub remote already had one commit (`dbeba9b`, MIT `LICENSE` only).
  The local repository was initialised on top of that history, so no rewrite
  or force-push was needed.
- Tooling: Python 3.13.5, Git 2.43, Node 24.4, pytest 8.4. No tree-sitter,
  ast-grep, semgrep or `gh`. `rg` exists only as a Git Bash shell function,
  not as a binary on the system PATH, so Python and PowerShell cannot call
  it. Phase 2 therefore needs a pure-Python reference search with ripgrep as
  an optional accelerator.
- Antigravity's documented customisation surface (fetched from
  antigravity.google/docs): `.agents/rules/*.md` (frontmatter `trigger`,
  `description`, 12,000-char limit), `.agents/skills/<name>/SKILL.md`,
  `.agents/agents/<name>.md` (frontmatter `name`, `description`, `tools`,
  `model`, `subagent`, `mainAgent`), `.agents/hooks.json` (`PreToolUse`,
  `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop`; JSON on
  stdin/stdout), and plugins (`plugin.json` with `skills/`, `agents/`,
  `rules/`, `hooks.json`, `mcp_config.json`). Global scope is
  `~/.gemini/config/{skills,agents,plugins,hooks.json}`.
- Anthropic's harness guidance (initializer/coding agent split, progress
  files, feature lists as JSON, Git as recoverable state, verify before
  finishing) informed the state model and the phase checkpoint.

## What was built

```
.gitignore, .gitattributes, pyproject.toml
lord/__init__.py, __main__.py, cli.py, paths.py, config.py, report.py, doctor.py
.agents/rules/lord-operating-contract.md
.agents/skills/lord-pre-edit-audit/SKILL.md
.agents/agents/lord-investigator.md
AGENTS.md, CLAUDE.md, README.md, CONTRIBUTING.md
docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/SECURITY.md
docs/decisions/0001-python-stdlib-core.md, 0002-antigravity-adapter-layout.md
docs/reports/phase-1-foundation.md
tests/test_foundation.py
```

## What the code does

- `lord.paths`: resolves the workspace root (markers `lord.toml`, `.agents`,
  `.git`), finds the Git top level, refuses paths that escape the root, and
  produces the canonical workspace-relative POSIX path used in every report.
- `lord.config`: built-in exclusion defaults (vendor, build, caches, virtual
  environments, provider runtime dirs) with optional `lord.toml` overrides
  read through `tomllib`.
- `lord.report`: the shared `Finding`/`Report` model. Every finding carries a
  severity and a confidence (`confirmed`, `inferred`, `unknown`). Renders to
  JSON for tools and to compact Markdown for a model's context.
- `lord.doctor`: verifies Python version, Git and ripgrep availability, Git
  root equals workspace root, config source, adapter presence, state
  directory writability, and provider independence.
- `lord.cli`: `python -m lord <command> [--json] [--root]`; the one stable
  boundary that later phases extend. `--json` and `--root` work before or
  after the subcommand. Exit code 1 signals an error finding.

## Design decisions

1. **Python standard library only** (ADR 0001). Zero install, Windows-safe,
   no provider dependency. Python analysis will be CONFIRMED quality via
   `ast`; other languages start as heuristic and are labelled INFERRED.
2. **One contract, referenced not copied** (ADR 0002). A single always-on
   rule holds the principles; the skill holds the procedure; the agent holds
   the role. `AGENTS.md` is a seven-line pointer; `CLAUDE.md` imports it. The
   v0.1 pattern of three identical master files was rejected because copies
   drift.
3. **Source vs generated state.** `.agents/`, `lord/`, `tests/`, `docs/` are
   tracked. `.lord/` is machine-local derived state and ignored. Durable
   knowledge goes in versioned human-readable files (`docs/decisions/` now,
   structured `docs/state/` in Phase 7).
4. **Confidence is mandatory.** The report model rejects unknown confidence
   values, so no later analysis can silently present a guess as a fact.
5. **No placeholders.** No empty hooks.json, plugin manifest or stub
   specialist agents. Each future mechanism is documented with its phase.

## What was reused

- The v0.1 seed ideas (exploration first, diff discipline, critical review,
  ask-don't-assume, pre-edit audit) were condensed into the contract and the
  skill. Their content was rewritten, not copied, and consolidated from six
  files into two.
- The existing remote history and MIT license.

## What was new

Everything else: the core package, report model, doctor, adapter files,
documentation, decision records and tests.

## Tests

`tests/test_foundation.py`, 54 test cases (parametrised), covering:

- workspace root resolution and Git root equality;
- `safe_join` rejecting paths that escape the root;
- config defaults and `lord.toml` override/extend semantics;
- report model validation, JSON and Markdown rendering with confidence;
- `doctor` on LORD itself (no errors) and the CLI JSON contract;
- required structure; rule frontmatter validity and 12,000-char limit; skill
  and agent frontmatter; contract referenced not duplicated;
- `.gitignore` policy through `git check-ignore`: 11 secret/runtime paths
  ignored, 10 LORD source paths (including `.agents/hooks.json` and a plugin
  manifest) not ignored;
- provider independence: empty `dependencies`, no provider or network
  imports, no API key references in `lord/`.

Result: `54 passed in 0.53s` (Python 3.13.5, pytest 8.4.2, Windows 11).

Two failures during development were fixed: `--json` was not accepted after
the subcommand (argparse default-override gotcha, fixed with `SUPPRESS`), and
the Markdown renderer used a non-ASCII separator that the Windows console
mangled (replaced; stdout is now reconfigured to UTF-8).

## Manual validation

- `python -m lord doctor` on the LORD workspace: all OK except a WARN that
  `rg` is not on PATH (accurate; see reconnaissance).
- `git rev-parse --show-toplevel` resolves to the LORD directory.
- `git check-ignore -v` confirmed `.agents/**` is tracked and `.lord/`,
  `.env`, `*.pem`, `.claude/`, `.gemini/` are ignored.

## Git

Commit: see `git log` (Phase 1 commit on `main`, on top of `dbeba9b`).
Push: recorded in the section below after the push attempt.

## Known limitations

- Rules and the skill reference `python -m lord` commands that only
  `doctor` currently provides; Phases 2-4 add the rest.
- Enforcement is advisory until Phase 6 hooks exist.
- The adapter follows Antigravity's public documentation and has not yet
  been exercised inside a live Antigravity session.
- ripgrep is unavailable to Python on this machine; performance of the
  fallback scanner on very large repositories is untested until Phase 2.

## Next phase readiness

Phase 2 can build directly on `lord.paths`, `lord.config` (exclusions),
`lord.report` (findings with confidence) and `lord.cli` (subcommand
registration). No foundation rewrite is expected.
