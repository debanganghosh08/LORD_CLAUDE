# LORD: Engineering Summary, Phases 6-7

Date: 2026-09-20. Builds on `summary-phases-1-5.md`. Repository
`LORD_Claude_Clone`, remote `https://github.com/debanganghosh08/LORD_CLAUDE.git`,
branch `main`.

## 1. Current capabilities

Everything from Phases 1-5 (boundary, inventory, index, forensics, reuse
and anti-bloat, graph, impact, trace, brief, verify, five specialists, four
skills) plus:

- **Enforcement** through `.agents/hooks.json`: a pre-edit gate on code-file
  writes (allow / ask / deny from session evidence), a bounded completion
  gate that blocks "done" while a detected test step fails, and a
  change-surface advisory injected when the bloat signal rises.
- **Durable memory** in `docs/state/memory.jsonl` with seven categories, a
  trust model (evidence requirements, expiry, supersession, key conflicts),
  deterministic retrieval and a `check` that surfaces invalid, stale,
  conflicting and open items.
- **Handoff** in `docs/state/handoff.json` for unfinished work.
- **Context assembly** (`lord context`) composing handoff, memory, brief,
  matching skills and rules with per-section caps.

21 commands: doctor, inventory, index, symbols, def, refs, related, deps,
dependents, tests-for, reuse, duplicates, diff, impact, trace, graph, brief,
verify, context, memory, handoff. Core: 4,697 lines of standard-library
Python across 21 modules; tests: 1,761 lines, 170 tests.

## 2. Final directory tree

```
LORD_Claude_Clone/                       99 tracked files
  .agents/
    hooks.json                            PreToolUse (write tools), PostInvocation, Stop
    lord_hook.py                          launcher copy (cwd = .agents/)
    rules/lord-operating-contract.md      always-on contract (names the gate, context, memory, handoff)
    skills/lord-critical-review, lord-pre-edit-audit, lord-reuse-audit, lord-impact-analysis, lord-memory
    agents/lord-investigator, lord-reuse-auditor, lord-impact-analyst, lord-skeptical-reviewer, lord-verification-reviewer
  lord/
    cli paths config report doctor                 phase 1
    inventory symbols index search query extractors/  phase 2
    reuse change_surface                           phase 3
    graph impact                                   phase 4
    review                                         phase 5
    session hooks                                  phase 6
    memory context                                 phase 7
  lord_hook.py                            launcher copy (cwd = workspace root)
  tests/  test_foundation test_forensics test_reuse test_impact test_review test_hooks test_memory; fixtures/sample_repo, dup_repo
  docs/
    ARCHITECTURE.md ROADMAP.md SECURITY.md decisions/ reports/ (phase-1 ... phase-7, two summaries)
    state/memory.jsonl state/handoff.json  durable engineering memory (tracked)
  AGENTS.md CLAUDE.md README.md CONTRIBUTING.md LICENSE pyproject.toml .gitignore .gitattributes
  .lord/                                  index, session evidence, hook logs (ignored)
```

## 3. Phase 6 implementation

`lord/session.py` records every investigation command in
`.lord/session/activity.jsonl` and keeps per-conversation counters and
caches. `lord/hooks.py` makes three decisions from that evidence plus the
existing `verify` and `diff`, with fail-safe dispatch: every path emits
valid JSON and exit 0, internal errors default to allow and are logged.
`lord_hook.py` (root and `.agents/`) starts it from either working
directory. `doctor` validates the hooks configuration, command
resolvability and launcher copies. Dogfooding found and fixed a duplicated
constant and an extractor gap (`from pkg import submodule`), the latter
forcing an index version bump.

## 4. Phase 7 implementation

`lord/memory.py`: item schema and validation, a store that loads, validates
(rejecting invalid lines), saves sorted one-per-line, adds, updates,
supersedes (history kept, subject inherited), detects key conflicts, checks,
and queries deterministically; handoff read/write/clear/render.
`lord/context.py`: capped composition of handoff, memory, brief, skills and
rules. CLI: `memory`, `handoff`, `context`. LORD's own memory was seeded
with 13 evidence-backed items from the phase reports.

## 5. Enforcement behaviour

| Situation | Decision |
|---|---|
| read-only tool, non-code file, edit of at most 3 lines, path outside the workspace | allow (audited) |
| code file investigated this session (path, stem or a defined symbol named by a LORD command within 45 minutes) | allow |
| code file, only task-level investigation | ask, reason names the file and the command |
| code file, no LORD investigation at all | deny, reason gives `python -m lord brief <file> --intent ...` |
| new code file without `reuse`/`brief` this session | deny, reason gives `python -m lord reuse ...` |
| stop while a detected verification step failed | continue with the failing output, at most twice per conversation, then allow |
| stop with advisory issues only (untested change, TODO, bloat) | allow, logged |
| bloat signal HIGH, or first rise to ELEVATED, after a model turn | ephemeral message with the reasons |
| any internal error, disabled flag, recursion, malformed stdin | permissive default, logged |

## 6. Hook architecture

`hooks.json` (documented schema, no quotes in commands, timeouts 20/30/600
s) -> `python -m lord_hook <event>` -> launcher locates the `lord` package
from its own file -> `lord.hooks.main` reads stdin JSON -> `handle()`
resolves the workspace from `workspacePaths` (fallback: the launcher's
repository) -> decision function -> JSON on stdout, exit 0, one line in
`.lord/session/hooks.log`. Hooks never write user files; they read
`.lord/session/` and call `verify`/`measure`.

## 7. Memory architecture

`docs/state/memory.jsonl` (versioned) with fields id, category, statement
(one line, 300 chars), evidence, status, created, updated, paths, symbols,
tags, key, supersedes, superseded_by, expires, context. Statuses:
confirmed and evidenced (evidence required), inferred, temporary (expiry
required), unresolved, superseded, deprecated. Retrieval: symbol 10 > path
equal 6 > path contains 4 > tag 4 > category 2 > shared terms 1 each, then
recency, then id; hidden items only with `--all`. `docs/state/handoff.json`
is one document with doing, done, remaining, discovered, decided, next,
verification, branch, commit. Transient state stays in `.lord/session/`.

## 8. What is deterministic

File classification and edit size from tool arguments; session evidence and
its window; test step results and exit codes; the tree signature and cache;
continuation counts; memory validation, supersession, conflicts, expiry,
retrieval order; handoff contents; every section cap in `context`.

## 9. What remains model-dependent

Whether the model runs the investigation before editing (the gate can only
force the order, not the quality of reading); what it records as memory and
how truthfully; whether it acts on an `ask` or an advisory; the judgement
in every specialist's output; and instruction following in general.

## 10. Test totals and results

170 tests pass (`python -m pytest`, about 2 minutes on Windows 11, Python
3.13.5): foundation 54, forensics 22, reuse 16, impact 14, review 15, hooks
32, memory 19 (parametrised counts included). Hook tests drive the real
launcher as a subprocess from both working directories with live-captured
payload shapes; memory tests cover every schema rule, staleness and
conflict paths, and reload determinism.

## 11. Live Antigravity test results

Executed: `agy` CLI 1.2.7 driven with a logging hook workspace; the model's
tool calls (`view_file`, `run_command`, `replace_file_content`,
`write_to_file`) were captured from the conversation database with their
exact argument schemas, and the CLI's fail-closed behaviour on a broken
PreToolUse hook was observed on every call. `agy -p="/hooks"` confirmed
which hooks are active.

Blocked, honestly: workspace `.agents` customisations load only in a
trusted workspace, print mode cannot grant trust, and granting it or
disabling Google's broken telemetry plugin would modify the user's
Antigravity configuration, which this run was not permitted to do. The LORD
hooks therefore have not fired inside a trusted session. The Phase 6 report
gives a ten-minute manual plan and the log field (`cwd`) that settles the
remaining launcher question.

## 12. Git / GitHub state

Root verified before every push. Commits: `26b779a` Phase 6, `4e20959`
Phase 7 (plus the docs commit recording these hashes). Both pushed to
`origin/main`; working tree clean; no force pushes.

## 13. Tracked vs ignored

Tracked: `.agents/**` (rules, skills, agents, hooks.json, launcher copy),
`lord/**`, `lord_hook.py`, `tests/**`, `docs/**` including
`docs/state/memory.jsonl` and `docs/state/handoff.json`, root docs and
configuration. Ignored: `.lord/` (index, session evidence, hook logs,
counters), provider and IDE runtime state, `.env*`, keys, tokens, caches,
build output, logs.

## 14. Known architectural debt

The dual launcher copy (to be collapsed once the working directory is
observed). Two constants sharing the value 2,000,000 (`MAX_LINECOUNT_BYTES`,
`MAX_SCAN_BYTES`). `hooks._is_code` and `reuse._is_code_file` are similar
by shape. `multi_replace_file_content` argument schema not observed. The
evidence window and trivial-edit threshold are judgement constants.

## 15. Current limitations

Hooks unexercised in a trusted Antigravity session; `ask` behaviour in
print mode unconfirmed; import-based coverage cannot see subprocess-driven
tests; memory retrieval is lexical; nothing writes memory automatically;
JS/TS remains heuristic and other languages unsupported; no data flow.

## 16. Exactly what Phase 8 should do

1. Package `.agents/` (rules, skills, agents, hooks.json) plus `lord/` and
   the launcher as an Antigravity plugin with `plugin.json`, installable
   with `agy plugin install <path>` and into `~/.gemini/config/plugins/`,
   so any workspace gets LORD without copying files.
2. Solve the launcher location once: plugin hooks run from the plugin
   directory (observed), so the plugin's hooks.json can reference the
   launcher relative to the plugin and the dual copy disappears; keep the
   workspace form as an override.
3. A `lord install`/`lord sync` command that bootstraps a target repository
   (`lord.toml`, `docs/state/`, optional workspace hooks) and reports drift
   between the installed plugin and the repository copy; versioning of the
   adapter and the core together.
4. First live validation in a trusted workspace as the acceptance test of
   the plugin, recording the observed cwd and `ask` behaviour into memory.
5. Optionally bind `lord context` into PreInvocation as an ephemeral
   message, throttled, once hooks are proven live.

## 17. Exactly what remains for Phase 9

A benchmark harness that runs identical tasks under three conditions (raw
model, model with basic instructions, model with LORD) and across models,
using the outputs LORD already produces as metrics: `diff` (lines added and
removed, files and unrelated files touched, new symbols, duplication
introduced), `verify` (completeness, regression rate from test results),
session activity (existing-code discovery, reuse discovery, iteration and
tool counts), `trace` outcomes versus known root causes, and transcript
review for clarification quality and architectural warnings. The task
fixtures, the recording of hook decisions, and the JSON output of every
command are already in place; the runner, task corpus and scoring are not.
