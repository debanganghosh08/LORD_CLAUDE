# Installing LORD (Antigravity plugin)

LORD ships as one Antigravity plugin built from this repository. Installing
it is your action: it changes your user-level Antigravity customisations.
Nothing in LORD installs itself, and nothing needs an API key or network
access.

Requirements: Python 3.11+ on `PATH` as `python` (the hooks run
`python -m lord_hook ...`), Git, a local clone of this repository.

## What is installed where

| Where | What | Written by |
| --- | --- | --- |
| `~/.gemini/config/plugins/lord/` (global) or `<workspace>/.agents/plugins/lord/` | `plugin.json`, `hooks.json`, `lord_hook.py` (the one launcher), `lord_cli.py`, `rules/`, `skills/`, `agents/`, `runtime/lord/` (the runtime, copied), `install.json` (version, source commit, file hashes), `.rollback.zip` (previous version, after an update) | `lord plugin install` |
| Python user site: `lord-harness.pth` | one line: the path of the installed `runtime/`, so `python -m lord` works in every workspace | `lord plugin install` (skip with `--no-cli`) |
| `<workspace>/.lord/` | index, session state, task frame, hook log; machine-local, ignores itself (`.lord/.gitignore`) | LORD at run time |
| `<workspace>/docs/state/` | durable memory and handoff, only if the agent or you run `lord memory add` / `lord handoff write` | LORD at run time |

Global = the product (rules, skills, launcher, runtime, agents). Workspace =
the project's own state. One repository's memory never reaches another: the
bundle contains no memory, and every state path is relative to the workspace
the hook payload names.

## Install

In the LORD repository:
```
python -m lord plugin validate                     # the source is packageable
python -m lord plugin install --global --dry-run   # what would change; writes nothing
python -m lord plugin install --global
python -m lord plugin status --global              # version, integrity, where `python -m lord` resolves
```
Then in Antigravity, open a workspace and trust it. If the plugin is not
enabled, enable it in the agent side panel (Customizations). Run the probe in
`docs/acceptance/MANUAL-ANTIGRAVITY-GEMINI.md` section 3 to confirm the hooks
fire.

One workspace only (instead of global): `--workspace <dir>` installs into
`<dir>/.agents/plugins/lord/`. The workspace then contains LORD's runtime;
add `.agents/plugins/lord/` to its `.gitignore` if it should not be
committed. Do not install both ways at once: Antigravity merges hook
configurations and every gate would fire twice (`lord doctor` warns).

## Update, roll back, uninstall

```
git pull; python -m lord plugin install --global   # reports +added ~changed -removed; idempotent
python -m lord plugin rollback --global            # swap back to the previous version (run again to undo)
python -m lord plugin uninstall --global           # removes the plugin folder and lord-harness.pth
```
The installer refuses to overwrite a `lord` plugin folder it did not create,
never creates `~/.gemini/config` itself, and writes nothing on `--dry-run`.

## If `python -m lord` does not resolve

`lord plugin status` shows where `python -m lord` resolves. If your terminal
uses another interpreter or a virtual environment (no user site), either run
the installer with that interpreter or call the plugin's fallback:
`python "<plugin>/lord_cli.py" <command>`. The once-per-conversation reminder
names the fallback when it detects this.

## Disable temporarily

Set `LORD_HOOKS_DISABLED=1` in the environment Antigravity is started from,
or disable the plugin in Customizations.
