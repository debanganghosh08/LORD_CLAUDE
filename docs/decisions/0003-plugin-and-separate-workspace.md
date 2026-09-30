# ADR 0003: LORD ships as one plugin; the demo is a separate workspace

Status: accepted (Phase 8B, 2026-09-30). Supersedes the `.agents/` layout of
ADR 0002 (the contract/procedures/roles split itself stands).

## Context

- LORD's rules, skills, agents, hooks and launcher lived in the repository's
  own `.agents/`. That works for LORD's repository only; every other project
  would need a copy of every file, and the launcher found the runtime by
  walking up from `.agents/` to the repository.
- The acceptance demo lived in `demo/` inside the LORD repository. It shared
  LORD's Git state, durable memory (Baseline B T03 wrote a demo fact into
  LORD's memory), session state, and LORD's own index saw the demo.
- Antigravity documents plugins (`plugin.json` with `name` and `description`,
  optional `hooks.json`, `skills/`, `agents/`, `rules/`), installed globally
  in `~/.gemini/config/plugins/<name>/` or per workspace in
  `.agents/plugins/<name>/`. Hooks run with the folder holding `hooks.json` as
  their working directory (shipped docs; observed for plugin hooks in Phase 6
  and workspace hooks in Phase 8A). The IDE substitutes no plugin-root
  placeholder, and on Windows Antigravity keeps literal quotes in hook
  commands (observed in Phase 6).

## Decision

1. `plugin/` is the plugin source (manifest, hooks.json, the one launcher,
   `lord_cli.py`, rules, skills, agents); `lord/` is the runtime. One copy of
   each in the repository.
2. `lord plugin install` builds a self-contained bundle: the plugin files
   plus `runtime/lord/`. The launcher finds the runtime from its own file
   (`<plugin>/runtime`, or `<repo>` in a checkout), never from the working
   directory or an absolute path.
3. `hooks.json` ships unchanged: `python -m lord_hook <event>`, no quotes, no
   absolute path. It relies on exactly one platform contract: the working
   directory is the plugin folder. Absolute paths were rejected (no
   placeholder in the IDE; quoted paths break on Windows; unquoted ones break
   on paths with spaces).
4. `python -m lord` in any workspace comes from one `lord-harness.pth` in the
   Python user site pointing at the installed runtime (optional;
   `lord_cli.py` is the fallback). Hooks and CLI therefore always run the
   same version.
5. The manifest carries only documented fields (`name`, `description`); the
   version lives in `lord.__version__` and `install.json`. No MCP: LORD needs
   none.
6. The LORD repository has no workspace adapter (`.agents/`); it gets LORD
   through the plugin like any other project, so hooks never run twice.
7. The demo moves to `tests/fixtures/demo_workspace/` (excluded from LORD's
   index) and is evaluated only as a separate Git repository created by
   `lord acceptance workspace --out <dir>` (refused inside the LORD
   repository). Evidence, baseline and oracles stay in the LORD repository;
   `acceptance check/record --workspace <dir>` observe the separate one. The
   `demo/` folder name is kept inside the workspace so the scenario prompts
   stay byte-identical to Baselines A and B.
8. `.lord/` ignores itself, so a target repository never edits its
   `.gitignore` for LORD.

## Consequences

- Installing is one command and is reversible (dry run, idempotent update,
  rollback archive, uninstall, refuses foreign folders). It is a user-level
  change and therefore the user's action.
- A global plugin gates code edits in every workspace the user opens in
  Antigravity; `lord plugin uninstall --global` or the Customizations toggle
  undoes it.
- If Antigravity ever ran plugin hooks from another working directory, the
  launcher would not start and PreToolUse would deny writes; the acceptance
  probe (hook log `cwd` ends in `\plugins\lord`) checks exactly this.
- Agents are packaged; the IDE's support for plugin agents is documented for
  Antigravity 2.0 and the CLI, not verified in the IDE.
