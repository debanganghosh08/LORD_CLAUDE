# Contributing to LORD

LORD is the first repository whose engineering health LORD cares about. Every
change here must satisfy the same contract LORD imposes on other codebases:
explore first, reuse first, minimal correct diff, verify before completion.

## Project boundary

The only LORD directory is the repository root that contains this file. Nothing
belonging to LORD lives outside it, and LORD tooling never reads or writes
outside it. Sibling directories next to the repository (historical reference
material) are not part of LORD and must not be modified, imported or staged.

## Git and GitHub policy

- Remote `origin` is `https://github.com/debanganghosh08/LORD_CLAUDE.git`.
- The Git root must equal the workspace root. Verify with
  `git rev-parse --show-toplevel` before every commit and push.
- One coherent commit per completed phase or logical change. No mixed commits.
- Never force-push. Never rewrite remote history for convenience.
- Never commit secrets, credentials, tokens, private keys or machine-local
  runtime state. The `.gitignore` enforces this; `tests/test_foundation.py`
  checks the policy.
- `.agents/` is product source and is tracked. `.lord/` is generated state
  and is ignored.

## Phase checkpoint (run at the end of every phase)

1. Run `python -m pytest`.
2. Inspect `git status` and `git diff --stat`.
3. Verify the repository root and that nothing outside it is staged.
4. Verify `.gitignore` still protects secrets and still tracks `.agents/`
   (`git check-ignore -v <path>`).
5. Grep the staged diff for obvious secrets.
6. Write or update `docs/reports/phase-N-*.md`.
7. Commit with a descriptive message, then push.

## Code conventions

- Python 3.11+, standard library only in `lord/`. Adding a runtime dependency
  needs a decision record in `docs/decisions/` explaining why the standard
  library is insufficient.
- Every analysis returns a `lord.report.Report`; every claim carries a
  confidence (`confirmed`, `inferred`, `unknown`). Search failure or an
  unsupported language is reported as `unknown`, never as "no results".
- Windows is the primary platform. Use `pathlib`, avoid shell-specific
  behaviour, and keep scripts runnable via `python -m lord`.
- Tests live in `tests/` and must test behaviour, not coverage.

## Adding Antigravity customisations

- Rules: `.agents/rules/<name>.md`, YAML frontmatter with `trigger`
  (`always_on`, `model_decision`, `glob`, `manual`) and `description`;
  12,000 characters maximum. Keep rules short; put procedures in skills.
- Skills: `.agents/skills/<name>/SKILL.md` with `name` and `description`.
- Agents: `.agents/agents/<name>.md` with `name`, `description`, `tools`,
  `model`, `subagent`. Specialists return structured findings, never dumps.
- Do not duplicate the operating contract across files. Reference it.
