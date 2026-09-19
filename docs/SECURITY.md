# LORD Security Policy

## Secrets

Never committed: credentials, tokens, API keys, private keys, certificates,
`.env` files, OAuth state, provider account files, machine-specific auth.
`.gitignore` blocks the common forms; `tests/test_foundation.py` verifies the
policy; the phase checkpoint greps the staged diff before every commit.

LORD never needs a model API key. If a future adapter needs configuration,
it reads it from the environment at runtime and never writes it to disk.

## Workspace boundary

LORD tooling reads and writes only inside the resolved workspace root
(`lord.paths`). It never reads unrelated user files, provider runtime state
(`~/.gemini`, `~/.claude`) or sibling directories. Reports contain
workspace-relative paths and tool availability, never environment dumps.

## Hooks and enforcement (from Phase 6)

- Hooks may block, warn or inject guidance. They never delete, revert or
  rewrite user code.
- Every hook has a bounded timeout and a defined failure mode: on internal
  error it logs and allows, it never silently blocks work or fakes a pass.
- Hooks run local scripts only; no network.

## Provider and IDE state

`.claude/`, `.gemini/`, `.antigravity/`, `.cursor/` and similar directories are
local runtime state and are ignored. `.agents/` is LORD product source and is
tracked deliberately.

## Reporting a problem

Open an issue on the GitHub repository. Do not include secrets in the report.
