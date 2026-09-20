# Phase 6 Report: Deterministic Enforcement

Date: 2026-09-20

## Objective

Move the most important LORD policies from "the model should do this" to
"the environment can detect whether it was done", using Antigravity's real
hook contract, without turning LORD into a blocker and without letting a LORD
bug prevent the user from editing their own code.

## What was built

```
lord/session.py            transient session state: activity log, per-conversation counters/caches, hook diagnostics
lord/hooks.py              pre-edit gate, completion gate, change-surface advisory; fail-safe dispatch and stdin/stdout entry point
lord_hook.py               launcher (`python -m lord_hook <event>`); identical copy at .agents/lord_hook.py
.agents/hooks.json         PreToolUse (write tools only), PostInvocation, Stop
lord/cli.py                investigation commands record evidence in the activity log
lord/doctor.py             hooks.json schema validation, resolvable commands, launcher copies
lord/extractors/python_ast.py   `from pkg import submodule` now binds the submodule file (found by dogfooding)
lord/index.py              INDEX_VERSION 3 (extractor change forces re-extraction)
.agents/rules/lord-operating-contract.md   states the gate in one bullet
tests/test_hooks.py        32 tests
docs/ARCHITECTURE.md       section 7 "Enforcement"; SECURITY.md, README.md, ROADMAP.md updated
```

## Final folder structure relevant to the phase

```
.agents/hooks.json                 the hook configuration (tracked)
.agents/lord_hook.py               launcher copy for cwd = .agents/ (tracked)
lord_hook.py                       launcher copy for cwd = workspace root (tracked)
lord/hooks.py, lord/session.py     decisions and session state (tracked)
.lord/session/activity.jsonl       investigation evidence (ignored, transient)
.lord/session/hooks.log            one line per hook invocation (ignored)
.lord/session/stop-<conv>.json     continuation counter + cached verification (ignored)
.lord/session/surface-<conv>.json  last bloat level per conversation (ignored)
```

## Hook contract as established

From the official documentation, cross-checked against payloads captured live
from Antigravity CLI 1.2.7 (a scratch workspace with a logging hook, driven
by `agy -p`):

- `hooks.json` maps a hook name to `enabled` plus event arrays. `PreToolUse`
  and `PostToolUse` entries carry a `matcher` and a `hooks` list; the other
  events list handlers directly. Handler: `{"type": "command", "command",
  "timeout"}` (default 30 s).
- stdin is camelCase JSON: `toolCall.name`, `toolCall.args`, `stepIdx`,
  `conversationId`, `workspacePaths`, `transcriptPath`, `modelName`; Stop
  adds `terminationReason`, `fullyIdle`, `executionNum`.
- Tool arguments observed: `view_file {AbsolutePath}`, `run_command
  {CommandLine, Cwd, WaitMsBeforeAsync}`, `replace_file_content {TargetFile,
  TargetContent, ReplacementContent, StartLine, EndLine, AllowMultiple,
  Description, Instruction}`, `write_to_file {TargetFile, CodeContent,
  Overwrite, Description}`. Values arrive as strings.
- stdout: PreToolUse `{"decision": allow|deny|ask|force_ask|
  deny_unless_prior_grant, "reason"}`; PostToolUse `{}`; PostInvocation
  `{"injectSteps": [{"ephemeralMessage": ...}]}`; Stop `{"decision":
  "continue", "reason"}` blocks, anything else allows.
- Observed, not documented: a PreToolUse handler that exits non-zero denies
  the tool call ("JSON hook ... failed: command failed: exit status 1" on
  every tool call in the transcript). Public issue trackers report the same
  for malformed or empty output. The command string is tokenised by
  Antigravity itself on Windows, keeping literal quotes; plugin hooks run
  with the hooks.json folder as working directory. Workspace hooks load only
  in a trusted workspace (CLI changelog: "workspace-local hooks ... not
  loading after trusting a folder"). Antigravity caps consecutive Stop
  continuations (changelog).

## What the code does

**Evidence (session).** Every investigation command (`brief`, `reuse`,
`impact`, `trace`, `refs`, `def`, `related`, `symbols`, `deps`,
`dependents`, `tests-for`, `graph`, `duplicates`, `diff`, `verify`) appends
`{t, command, target}` to `.lord/session/activity.jsonl`. `evidence_for(file,
symbols, window)` returns `target` (the file, its stem or one of its symbols
was named), `task` (a task-level command ran for something else) or `none`.

**Pre-edit gate (PreToolUse, write tools only).** Resolve `TargetFile`
against the workspace (relative or absolute, backslashes accepted); allow
anything outside it. Classify the path with the inventory rules: docs,
config, tests, data are allowed. Compute the edit shape from the arguments:
new file, rewrite, edit of N lines (max of target/replacement lines), or
unknown. Edits of at most 3 lines are allowed (audit). Otherwise: new code
file needs a `reuse` or `brief` in the last 45 minutes (deny with the exact
command); existing code file with target-level evidence is allowed, with
task-level evidence only is `ask`, with none is `deny`. Every decision is
logged with its reason and timing.

**Completion gate (Stop).** Only when `fullyIdle` is not false and code
files changed. Per conversation, a counter caps blocking at 2 consecutive
continuations. The working tree is signed (git status plus mtimes); if the
signature is unchanged, the cached verification is reused, otherwise
`verify(run=True)` executes the project's detected steps within a budget
passed from hooks.json (`--timeout 540` under a 600 s hook timeout). Only a
FAILED step (exit code non-zero, for example pytest) produces `{"decision":
"continue"}`, with the failing output tail in the reason. Untested changes,
TODO markers, bloat and unavailable tools are logged, never blocked. A
verification that exceeds the budget does not block.

**Change-surface advisory (PostInvocation).** When code files changed and
the tree changed since the last check, `measure` runs; on HIGH, or on the
first rise to ELEVATED, an ephemeral message with the summary line and the
reasons is injected. Unchanged trees and steady levels produce nothing.

**Fail-safe dispatch.** `handle()` wraps every decision in try/except and
returns the permissive default on error, logging the exception. `main()`
tolerates missing, malformed or non-object stdin and unknown events, honours
`LORD_HOOKS_DISABLED=1` and the `LORD_HOOK_ACTIVE=1` recursion guard, and
always writes JSON and returns 0. The launcher locates the `lord` package
from its own file, passes its repository as the fallback root, and prints
the default if even the import fails.

## Why it was designed this way

- Hard gates only on facts (no investigation command ran; a test step
  failed); heuristics are advisory. A gate that fires on a heuristic is a
  gate the agent learns to route around.
- The gate reuses the command boundary that already exists instead of
  re-implementing analysis: hooks read `.lord/session/` and call `verify`
  and `measure`; nothing is duplicated.
- Fail-open by construction, because a failing PreToolUse hook is a
  denial of every write in the workspace. Google's own bundled hook
  demonstrates the failure mode on this machine.
- Two identical launchers rather than an absolute path: hooks.json is
  tracked and must work on any machine, and the working directory is
  undocumented. The launcher logs its cwd so the first live session settles
  the question; Phase 8 can then drop the unused copy.
- No quotes in commands (Windows tokenisation), bounded timeouts, an
  internal budget below the hook timeout, and a continuation cap in addition
  to Antigravity's own.

## What was reused

`verify`, `measure`, `git_changes`, `classify`, `language_of`,
`PROBE_BYTES`, `find_workspace_root`, `is_within`, the index (symbols of the
target file), the report model, the doctor. No new dependencies.

## What was new

`session.py`, `hooks.py`, the launcher, `hooks.json`, activity recording in
the CLI, hook validation in the doctor, and the tests.

## What was deliberately not built

- No PostToolUse hook: it can only return `{}` and cannot carry a message.
- No PreInvocation injection of state (Phase 7 decides what, if anything,
  to inject).
- No blocking on bloat, resemblance, unrelated files or missing tests.
- No absolute paths or machine-specific configuration in hooks.json.
- No modification of the user's Antigravity configuration (trust, plugins).

## Tests

`tests/test_hooks.py` (32) plus earlier suites: **151 passed** (about 90 s;
the completion-gate tests run real pytest subprocesses). Behaviours covered:

- shipped hooks.json valid, bounded timeouts, no quotes, exactly the three
  events; invalid configurations rejected (missing hooks list, timeout out
  of range, unknown event, wrong type, empty command); launcher copies
  identical; doctor flags broken JSON and unresolvable commands;
- matcher semantics for every write tool, read tools, regex and wildcard;
- pre-edit gate: non-write tools, docs/config/tests allowed; trivial edit
  allowed and audited; meaningful edit with no evidence denied with the
  command to run; task-level evidence asks; target-level evidence (symbol
  name, Windows path, absolute path) allows; new code file denied until a
  `reuse`/`brief` exists (`refs` alone is not enough); evidence expires
  after the window; paths outside the workspace not gated;
- completion gate: nothing changed or not idle allows; failing pytest
  blocks with the output, twice, then the cap allows; passing verification
  allows and the unchanged tree reuses the cache; advisory-only outstanding
  items allow and are logged; a slow verification beyond the budget allows;
- advisory: HIGH injects once per tree state; ELEVATED injects on the
  transition only;
- safety: injected internal errors default to allow/`{}` and are logged
  with the exception; `LORD_HOOKS_DISABLED` and `LORD_HOOK_ACTIVE`; malformed,
  empty and non-object stdin, unknown and missing events; the workspace tree
  hash is identical after every hook ran;
- launcher contract as a subprocess from both the workspace root and
  `.agents/`, with a backslash `TargetFile`, for pre-tool, stop and
  post-invocation, including garbage stdin; the logged cwd matches;
- CLI investigation commands record evidence with targets and names.

## Manual validation (dogfooding on LORD with real payload shapes)

| Scenario | Result |
|---|---|
| read-only `view_file` | allow, 0 ms |
| `write_to_file` of a new `lord/helpers.py`, no evidence | deny: "no `lord reuse` or `lord brief` ran in this session" |
| same after `lord reuse "helper for hook decisions" --name helper` | allow |
| 5-line `replace_file_content` on `lord\hooks.py`, task-level evidence only | ask: "was not itself investigated this session (only `reuse ...`)" |
| same after `lord brief lord/hooks.py --intent ...` | allow, 32 ms |
| 1-line replacement | allow (trivial edit) |
| payload without `workspacePaths` | falls back to the launcher's repository; decided normally |
| PostInvocation on the Phase 6 working tree | HIGH injected: additive-heavy diff, launcher copies resembling each other, 3 files outside the main change |
| Stop on the Phase 6 tree | ran the real suite (39.7 s): pytest PASS; verdict "not verified" for advisory reasons only; allowed; second call 0.2 s from cache |

Dogfooding found two defects in the phase's own code, both fixed: `hooks.py`
redefined `PROBE_BYTES` instead of importing it, and `from lord import hooks`
resolved to `lord/__init__.py`, so `verify` reported the hook modules as
untested. The second fix lives in the Python extractor and required an
index version bump, which is now documented at the constant.

## Live Antigravity validation

Executed:
- Antigravity CLI `agy` 1.0.12 (auto-updated to 1.2.7 during the session)
  and the Antigravity IDE are installed; the IDE was running.
- A scratch workspace with a logging hook was driven with
  `agy --dangerously-skip-permissions -p='...'`. Note: `-p` must carry the
  prompt (`-p='...'`), otherwise the CLI takes the next flag as the prompt.
- The model attempted `view_file`, `run_command`, `replace_file_content` and
  `write_to_file`; the conversation database recorded every call and every
  denial. This produced the exact argument schemas above and the observed
  fail-closed behaviour of a broken PreToolUse hook.
- `agy -p="/hooks"` lists active hooks non-interactively (with
  `MSYS_NO_PATHCONV=1` under Git Bash).

Blocked, with the reason:
1. Workspace `.agents/hooks.json`, rules and skills are loaded only in a
   trusted workspace. Neither the scratch workspace nor the LORD repository
   is in the CLI's `trustedWorkspaces`, print mode never prompts for trust,
   and granting trust means editing the user's Antigravity settings, which
   this run is not allowed to do. Consequently `/hooks` and `/skills` show
   only built-in and plugin customisations in both workspaces.
2. Google's bundled `googlecloudtools.datacloud_telemetry` plugin ships a
   PreToolUse hook whose Windows command is mis-quoted; on this machine it
   exits 1 and denies every tool call in the CLI (`MODULE_NOT_FOUND`). Even in
   a trusted workspace, no file write could succeed until that plugin is
   disabled or fixed, which is again the user's configuration.

Scenarios 1-7 of the required matrix were therefore executed locally through
the real launcher with live-captured payload shapes (table above and the
test suite), not inside a trusted Antigravity session.

Manual test plan for the user (IDE or CLI, 10 minutes):
1. Open the LORD workspace in Antigravity and accept the trust prompt (CLI:
   start an interactive `agy` session in the folder and trust it).
2. If tool calls are denied with a `googlecloudtools.datacloud_telemetry`
   error, disable that plugin (`agy plugin disable
   googlecloudtools.datacloud_telemetry`, or move it out of
   `~/.gemini/config/plugins/`), which is the forum-documented workaround.
3. Ask the agent to add a function to `lord/hooks.py` without investigating:
   expect the deny reason naming `python -m lord brief lord/hooks.py`.
4. Ask it to run the brief and retry: expect the edit to proceed.
5. Ask it to create `lord/new_helper.py`: expect deny until `lord reuse` ran.
6. Break a test and ask the agent to finish: expect the Stop reason with the
   pytest failure, at most twice.
7. Paste a copy of an existing function into a new file: expect the HIGH
   change-surface message after the next model turn.
8. Read `.lord/session/hooks.log`: the `cwd` field settles which launcher
   copy Antigravity uses.

## Failures / limitations

- Not yet exercised inside a trusted Antigravity session (above).
- The working directory for workspace hooks and the exact handling of
  `ask` in print mode are unconfirmed; both are hedged.
- Import-based coverage cannot credit tests that exercise code through
  subprocesses (the launcher and the CLI show as untested).
- The evidence window (45 min) and trivial-edit threshold (3 lines) are
  judgement constants.
- `multi_replace_file_content`'s argument schema was not observed live; its
  edit size is treated as unknown (meaningful).
- The dual launcher is deliberate duplication and shows up in `duplicates`.

## Git

Commit: `26b779a` "Phase 6: deterministic enforcement through Antigravity
hooks" on `main`. Push: succeeded (`837e3fb..26b779a main -> main`).

## Next-phase readiness

Phase 7 can rely on: the session directory and its helpers for transient
state; a stable evidence record format; hook entry points that can later
inject durable memory (PreInvocation) without changing the safety model.
