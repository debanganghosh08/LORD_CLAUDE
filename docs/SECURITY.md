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

## Hooks and enforcement

- Hooks may deny, ask, warn or inject guidance. They never delete, revert or
  rewrite user code; they read state and append diagnostics under
  `.lord/session/`.
- Every hook has a bounded timeout (20 s pre-edit, 30 s advisory, 600 s
  completion with an internal budget) and a defined failure mode: on any
  internal error it prints the permissive default, exits 0 and logs the
  exception. A LORD bug must never prevent the user from editing.
- `LORD_HOOKS_DISABLED=1` turns decisions off; `"enabled": false` in the
  installed plugin's `hooks.json`, disabling the plugin in Customizations, or
  `lord plugin uninstall` turns the hooks off entirely.
- Hooks run local Python only; no network, no credentials.
- Hard denials fire only on plain facts (no investigation ran; tests
  failed). Heuristic signals are advisory.

## Provider and IDE state

`.claude/`, `.gemini/`, `.antigravity/`, `.cursor/` and similar directories are
local runtime state and are ignored. `plugin/` and `lord/` are LORD product
source and are tracked deliberately.

## Plugin installation

- `lord plugin install` validates the source first: only documented manifest
  fields, no secret-like files or content, no machine paths, a runtime that
  imports only the Python standard library. It writes only the target plugin
  folder and, unless `--no-cli`, one `lord-harness.pth` in the Python user
  site; it refuses a `lord` folder it did not create and never creates
  Antigravity's config folder. Global installation is the user's action.
- The bundle contains no memory, evidence, demo, tests or local state, and
  no provider configuration. `install.json` records file hashes;
  `lord plugin status` reports any drift.

## Reporting a problem

Open an issue on the GitHub repository. Do not include secrets in the report.
