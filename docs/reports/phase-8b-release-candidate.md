# Phase 8B: release-candidate hardening and the portable Antigravity plugin

Date: 2026-09-30. Starting point: `065e257` (Phase 8A.1, Baseline B
4 PASS / 4 PARTIAL / 0 FAIL). Version: `0.2.0rc1`.

**Status: release candidate, infrastructure validated outside the IDE; the
live separate-workspace test in the Antigravity IDE is pending (it needs the
user's global install and IDE session). Release readiness is not claimed
until that test passes its infrastructure gate (section 14).**

## 1. Objective

Harden, package, install in a separate workspace, verify portability. Not
more features, and no Phase 9. Every capability is classified as PROVEN,
PARTIALLY PROVEN, ENVIRONMENT-DEPENDENT, HEURISTIC, MODEL-DEPENDENT or
UNPROVEN (section 17).

## 2. Release audit (before any change)

| Check | Result |
|---|---|
| Git root, branch, state | `LORD_Claude_Clone`, `main`, clean, `065e257` = `origin/main` |
| `python -m pytest` | 205 passed |
| Demo suite | 37 passed |
| `python -m lord doctor` | all OK except `rg not found` (WARN, optional tool) |
| `lord verify --base HEAD~1` | NOT VERIFIED: 6 "markers", all false positives (3 in docs prose, 2 in comments discussing markers, 1 inside a Python test-fixture string) |
| Evidence records | 16 (8 Baseline A, 8 Baseline B), all valid |
| Memory | 37 items, no conflicts |
| `.agents/` | contract, 5 skills, 5 agents, hooks.json, launcher; root `lord_hook.py` already removed in 8A.1 |
| Antigravity plugin docs | researched (section 5) |

Two defects the audit found beyond the known ones: the marker check never
saw untracked new files (a brand-new file with a real `TODO` was invisible:
false confidence), and `lord/acceptance.py` (scenario prompts and expected
answers) would have shipped in any bundle that copied the runtime (found
while listing the first installed bundle; section 11).

## 3. What was built

| Component | What it does |
|---|---|
| `lord/markers.py` (new) | unfinished-work markers by syntax, per file kind |
| clarification boundary (`hooks.py`, `session.py`) | material assumption -> user decision at the next code edit; decision state; confirmation provenance |
| verification contract (`review.py`, `session.py`) | executed result recorded with the tree signature; `reconcile` of a reply against it; `verify --reconcile`; Stop reuses a fresh record |
| `plugin/` (moved from `.agents/`) + `plugin/plugin.json`, `plugin/lord_cli.py` (new) | the plugin source |
| `lord/plugin.py` (new) + `lord plugin validate/install/uninstall/rollback/status` | packaging and a reversible installer |
| separate acceptance workspace (`acceptance.py`) | `lord acceptance workspace --out`, `--workspace` on baseline/check/record, `--reply` |
| acceptance basis labels | every check says confirmed fact, heuristic signal or human review required |
| plugin-aware runtime (`paths.py`, `context.py`, `doctor.py`) | rules and skills found in the plugin; doctor reports runtime origin, product source, every applicable hooks.json, double enforcement, stdlib-only imports |
| self-ignoring state (`paths.state_dir`) | `.lord/.gitignore` = `*` |
| docs | `docs/INSTALL.md`, ADR 0003, rewritten manual guide, ARCHITECTURE, README, SECURITY, CONTRIBUTING, ROADMAP, contract and skills |
| tests | `tests/test_release.py` (38), `tests/test_acceptance.py` rewritten for the separate workspace, layout tests updated |

## 4. What was fixed, and why each change was necessary

**4.1 LORD's own verification (release blocker).** The detector matched the
word `TODO` anywhere on an added line (`\b(TODO|FIXME|XXX|HACK)\b`), so LORD
reported NOT VERIFIED for its own documentation. Chosen semantics, the
smallest robust ones: a marker is marker syntax, never a word.
- Code: a comment whose text starts with the marker (`# TODO: x`,
  `// FIXME(a)`, `/* XXX */`, ` * HACK`). Python comments come from
  `tokenize`, so a marker inside a string (a test fixture) is not one; other
  languages strip quoted strings first. `TODO/FIXME` pairs and `TODO-like`
  are discussion.
- Prose (`.md`, `.rst`, `.txt`, `.adoc`): a line that starts with the marker
  followed by `:` or `(` (after list, heading or checkbox prefixes), outside
  fenced code blocks, or an HTML comment starting with it.
- Never scanned: JSON/CSV/lock/SVG, and files under `fixtures/`,
  `__fixtures__/`, `testdata/`, `test_data/` (test input by convention).
- Added lines only, from `git diff -U0` hunk headers; untracked new files are
  scanned in full (the old detector missed them entirely).
Not chosen: configurable marker lists (no evidence of need), ignoring all
docs or all tests (would hide a real `TODO:` in a doc or an unfinished
test). Fixtures: real TODO in source; TODO in documentation; TODO in a test
fixture string; TODO-like comments; completed code discussing TODO
detection; plus fenced code, fixture dirs, JSON, JS strings, block
comments, untracked files, and a live verdict flip. Result:
`lord verify --base 4cb5eaa` on LORD's own last two phases finds 0 markers
(was 6). While writing the tests the detector flagged two of my own new
comments that genuinely began with `# TODO ...`; they were reworded (they
were marker syntax), and `TODO-` was excluded from marker syntax (it was
prose).

**4.2 Clarification (the remaining behavioural gap).** In 16 live runs
Gemini never asked a question; in Baseline B T05 it recorded a material
assumption and implemented anyway, and LORD only printed an advisory once.
The general mechanism now: the model identifies the ambiguity (LORD cannot
parse natural-language ambiguity and does not pretend to); LORD records it,
surfaces it, and holds the user decision boundary.
- `task ask` (an open question): every code edit is denied, trivial ones
  included (a one-line edit can implement an undecided reading; previously
  edits of up to 3 lines passed), until `task resolve --answer`.
- `task assume --material` (the model proceeds on one reading): the next code
  edit that the evidence rules would allow or ask becomes a Level 2 `ask`
  whose reason names the assumption: the IDE's approval prompt is the user's
  decision. LORD cannot read that decision, but it observes its effect: if
  the gated file changes afterwards, the edit was approved and the
  assumption is confirmed with `source: edit-gate approval`; an unchanged
  file means rejected and the next edit asks again. The boundary never
  turns an investigation `deny` into an `ask`.
- `task confirm` is recorded as `source: model-reported` (the model's word).
- Cosmetic assumptions never gate ("do not require a question for every
  minor choice").
- `decision_state`: `blocked` / `awaiting-confirmation` / `clear`, shown by
  `lord task show`, in `verify` meta, and in the Verification block
  (confirmed and unconfirmed material assumptions, open questions).
- Evidence records carry `task_decisions`; T05's check reports whether the
  ambiguity was recorded at all.
Fixtures unrelated to T05: "remove inactive users" (Python; hard vs soft
delete, what "inactive" means) and "round the prices" (JavaScript; half-up
vs banker's, cents vs units), plus cosmetic and no-evidence cases. The T05
prompt and the phrase "last month" are untouched and appear nowhere in the
mechanism.

**4.3 Verification contract.** Baseline B showed LORD's block is reliable
while Gemini's prose can overclaim ("fully tested" next to an honest block).
- `verify --run` records its executed result with the working-tree signature
  (`.lord/session/verification.json`).
- `reconcile(reply, record)`: VERIFIED / NOT VERIFIED only from LORD's
  executed checks on the current tree; UNVERIFIED CLAIM when LORD has no
  fresh record but the reply claims success; NO VERIFICATION when neither
  exists. A claim is shown beside the status, and a disagreement is listed
  as a contradiction; it never changes the status. Prose such as "all tests
  pass" counts only as a heuristic claim.
- `lord verify --reconcile <file>`; `acceptance record --reply <file>` stores
  the reconciliation in the evidence.
- The Stop gate reuses a fresh `verify --run` record instead of running the
  suite a second time.
- Agent-facing contract (rule section 7): paste the block; on FAIL add
  `Reason: <real output>`; if not run, `Verification: not run - <why>`;
  never write PASS for output you did not see.
Tests: a claim cannot override a failed verification; a LORD pass is
factual with or without a report; a missing report is distinguishable from
a failure, from no verification, from an unverified claim and from a stale
pass; the same tree gives the same block, and LORD's block parses back to
the same results.

**4.4 Demo isolation.** `demo/` moved to `tests/fixtures/demo_workspace/demo/`,
excluded from LORD's index (`lord.toml`). `lord acceptance workspace --out
<dir>` exports it as a new Git repository with one baseline commit, refuses
any location inside the LORD repository and any non-empty directory. The
`demo/` folder name is kept inside the workspace so the scenario prompts are
byte-identical to Baselines A and B. `check`/`record`/`baseline` take
`--workspace`; evidence, baseline and oracles stay in the LORD repository;
the oracle locates the demo through `LORD_ACCEPTANCE_DEMO` (only its locator
lines changed; the assertions did not). Coupling removed: shared Git state,
shared memory (Baseline B T03), shared session state, LORD's index seeing
the demo, and the model reading LORD's source from the workspace.

**4.5 Acceptance precision.** Every check is labelled and its confidence
follows the label: confirmed fact (reuse by confirmed reference, oracle,
fix location, constant changed, callers intact, tests updated and passing,
verify used), heuristic signal (new-helper name match, symptom patch,
bypass/copy detection, change shape, small diff, "a test changed" for T08),
human review required (T04 when nothing was detected; T05 premature edit).
The unrelated-file, bloat, import-coverage and modified-copy signals were
already advisories in `verify` (8A.1); they stay advisories.

**4.6 Duplication.** The root `lord_hook.py` was already gone (8A.1);
`git ls-files '*lord_hook.py'` is now exactly `plugin/lord_hook.py`. The
repository's own `.agents/` adapter was removed: with the plugin installed
globally it would have run every hook twice (doctor now warns if that
happens anywhere).

## 5. Plugin architecture (researched first)

Sources: antigravity.google/docs (plugins, hooks, skills, rules, subagents,
changelog), the shipped `agy-customizations` docs under
`~/.gemini/antigravity-ide/builtin/`, installed Google plugins under
`~/.gemini/config/plugins/` (read only), and LORD's own Phase 6 / 8A
observations.

| Fact | Status |
|---|---|
| Plugin = folder with `plugin.json` (required marker), optional `hooks.json`, `skills/<n>/SKILL.md`, `agents/<n>.md`, `rules/<n>.md`, `mcp_config.json` | documented |
| Manifest schema: `name` (pattern `^[a-zA-Z0-9-_]+$`), `description`; `additionalProperties: false` (Google's own plugins add `version`, `author`, ... anyway) | documented; LORD uses only `name` and `description` |
| Global `~/.gemini/config/plugins/<n>/`, workspace `.agents/plugins/<n>/`; install = copy the folder; enable state in `~/.gemini/config/config.json` | documented |
| Plugin rules load when the plugin is enabled | shipped docs |
| Hook cwd = the folder holding hooks.json | shipped docs; observed for plugin hooks (Phase 6, CLI) and workspace hooks (8A, IDE) |
| `${extensionPath}`/`${PLUGIN_ROOT}` substitution | CLI binary only; not in the IDE (inferred from the binaries) |
| Windows: Antigravity keeps literal quotes in hook commands | observed (Phase 6: Google's quoted telemetry hook fails with MODULE_NOT_FOUND) |
| Plugin `agents/` | documented for Antigravity 2.0 and the CLI; not listed for the IDE |
| Plugin trust requirements | not documented |

Decisions (ADR 0003): plugin source `plugin/` + runtime `lord/`, one copy
each; the installer builds a self-contained bundle; `hooks.json` ships
unchanged as `python -m lord_hook <event>` (no quotes, no absolute path; an
absolute path was rejected for the three reasons above); manifest without
invented fields (version in `lord.__version__` and `install.json`); no MCP.

## 6. Plugin tree

Source (tracked):
```
plugin/
  plugin.json              name, description
  hooks.json               lord: PreToolUse (write tools), PreInvocation, PostInvocation, Stop -> python -m lord_hook <event>
  lord_hook.py             the one launcher (any Python 3; never exits non-zero)
  lord_cli.py              `python -m lord` fallback
  rules/lord-operating-contract.md                  trigger: always_on (7.8k chars)
  skills/lord-{critical-review,pre-edit-audit,reuse-audit,impact-analysis,memory}/SKILL.md
  agents/lord-{investigator,reuse-auditor,impact-analyst,skeptical-reviewer,verification-reviewer}.md
lord/                      the runtime (23 modules + extractors), standard library only
```
Installed bundle (43 files, measured):
```
<plugins>/lord/
  plugin.json  hooks.json  lord_hook.py  lord_cli.py  LICENSE  install.json  [.rollback.zip]
  rules/  skills/  agents/
  runtime/lord/*.py  runtime/lord/extractors/*.py      (acceptance.py excluded)
```
Not in the bundle (tested): docs, tests, demo, evidence, oracles, memory,
handoff, `.lord`, caches, `lord.toml`, `acceptance.py`, and any scenario
prompt or expected answer.

## 7. Installation model

`python -m lord plugin install --global | --workspace <dir> | --dest <dir>
[--dry-run] [--no-cli]`:
1. validate the source: documented manifest fields, hooks schema and
   launcher commands, rule triggers and size, skill and agent frontmatter,
   no secret-like names or content, no machine path (the development
   repository's own path is forbidden text), runtime imports only the
   standard library;
2. validate the target: the anchor must exist (`~/.gemini/config` for
   global, the workspace for `--workspace`, the parent for `--dest`); a
   `lord` folder without LORD's `install.json` is refused, never overwritten;
3. compare hashes: identical -> "nothing changed" (idempotent, no writes);
   otherwise report `+added ~changed -removed`;
4. keep the previous version as `.rollback.zip`, write the bundle, write
   `install.json`; on an I/O error restore the previous version;
5. unless `--no-cli`, write `lord-harness.pth` (one line) in the Python user
   site so `python -m lord` imports the installed runtime.
`plugin rollback` swaps the installed and archived versions (so it can be
undone); `plugin uninstall` removes the folder and the `.pth` only if they
are LORD's; `plugin status` reports version, source commit, integrity drift
and where `python -m lord` resolves. Global installation is the user's
action; this phase installed only into test and scratch directories.

## 8. Global vs workspace state

| Global (the product) | Workspace (the project) |
|---|---|
| rules, skills, agents, hooks, launcher, runtime (plugin bundle) | `.lord/`: index, session activity, task frame, hook log, verification record (ignores itself) |
| `lord-harness.pth` (CLI registration) | `docs/state/`: durable memory and handoff, only when written |
| no memory, no project data | the target project's code and Git history |

Every state path is derived from the workspace the hook payload names
(`workspacePaths`) or `--root`; the bundle contains no state. Tested: a
second workspace does not see the first one's memory; the exported demo
workspace starts with no memory and `lord context` there shows none of
LORD's 44 items.

## 9. Path and launcher model

- Hook command: `python -m lord_hook <event>` resolved in the hook's cwd
  (the plugin folder). This is the only platform contract relied on.
- Launcher: finds the runtime from `__file__` (`<plugin>/runtime`, or
  `<repo>` in a checkout); never from the cwd or an absolute path; the
  workspace comes from `workspacePaths` (used as given, never climbed).
- CLI: `python -m lord` via the `.pth`, or `python "<plugin>/lord_cli.py"`.
  The first reminder of a conversation names the fallback when
  `python -m lord` is not importable.
- Runtime self-location: `paths.plugin_root()` distinguishes an installed
  bundle from a development checkout; skills and rules are found in the
  plugin and in any workspace `.agents/`.
- No file in the plugin source or bundle contains the development path
  (tested; `install.json` holds only the version and hashes).

## 10. Security

No credentials, tokens or provider configuration anywhere in the plugin;
validation rejects secret-like names and content. Hooks run local Python
only, write only under `<workspace>/.lord/`, and fail open with exit 0. The
installer writes only its target folder and one `.pth` file. No network.
Staged diff scanned for secrets before each commit (section 18).

## 11. No-API design

`pyproject.toml` has `dependencies = []`; doctor's provider-independence
check now scans every runtime module's imports (was a static statement);
plugin validation rejects any non-stdlib import (tested with a planted
`import requests`). Nothing calls a model or needs a key.

## 12. Demo / fixture isolation

See 4.4. The oracle remains outside every evaluated workspace; the bundle
excludes `acceptance.py`, which knows the answers (found while listing the
first installed bundle: an agent exploring `~/.gemini/config/plugins/`
could have read the T03 root cause). A test asserts that no scenario prompt
or expected answer string ships.

## 13. Test results

| Run | Result |
|---|---|
| `python -m pytest` | 255 passed in 105 s (was 205 in about 9 minutes: the old tests copied the whole repository into clones and indexed the demo inside LORD) |
| `python -m lord verify --run` (LORD itself) | `python -m pytest -q - PASS`, `LORD verify - VERIFIED`; advisories: bloat signal elevated, 3 changed files without an importing test (justified below) |
| `python -m lord doctor` | all OK except `rg not found` (WARN); hooks: INFO "no hooks.json applies" (the LORD repository no longer has a workspace adapter; the plugin is not installed on this machine yet) |
| `python -m lord plugin validate` | valid |
| demo suite in an exported workspace | 37 passed |
| T03 oracle on the unmodified exported demo | FAIL (3 failures), as it must: the planted defect is live |

Advisories on LORD's own diff, justified: the bloat signal is ELEVATED
because this phase moves 36 files (`.agents/` -> `plugin/`, `demo/` ->
`tests/fixtures/demo_workspace/`) and adds packaging, which is the task;
the "files without an importing test" are `plugin/lord_hook.py` and
`plugin/lord_cli.py` (tested through subprocesses, which import-based
coverage cannot credit) and `lord/__init__.py` (the version string). The
advisories first also reported HIGH with duplicated helpers: a second
frontmatter parser in `plugin.py` and a second `_git` in `markers.py`. Both
were real duplication and now reuse `context.frontmatter` and
`change_surface._git`.

255 tests (205 before): `test_release.py` 38 (markers 16, clarification 5,
verification contract 5, plugin 10, isolation and portability 2),
`test_acceptance.py` 21 (rewritten against an exported workspace, +4
isolation tests), layout tests updated in foundation, hooks, review and
remediation. Four earlier assertions were changed deliberately, each
because the behaviour changed on purpose: trivial edits under an open
question are now denied; marker evidence now carries the line number; the
doctor's adapter finding became runtime/product findings; a workspace
without its own rules now gets the plugin's contract in `lord context`.

## 14. Separate-workspace test

**Automated rehearsal (outside the IDE): 15/15.** A scratch directory held a
workspace exported by `lord acceptance workspace` and a fake
`home/.gemini/config/plugins` with the installed bundle. The launcher was
run exactly as Antigravity runs it (the command string from the installed
hooks.json, tokenised without quotes, cwd = the plugin folder, JSON on
stdin naming the workspace):
workspace exported; bundle installed (+43 files); reminder injected once and
then silent (with the CLI fallback line, since no `.pth` was written);
probe `demo/probe.py` denied; hook log written in the workspace with `cwd` =
the installed plugin folder; `lord_cli.py` ran `context` in the workspace
with the contract and skills served from the plugin; the investigated edit
allowed; PostInvocation ran; Stop ran the demo tests and allowed; garbage
input returned `{}` with exit 0; `git status` in the workspace showed only
the agent's change (LORD state self-ignored); no LORD source, memory or
oracle in the workspace; workspace memory empty; `acceptance check
--workspace` observed the separate repository.

**Live test in the Antigravity IDE: PENDING.** It requires the user to
install the plugin globally (a user-level change), create the workspace,
open and trust it, and run the infrastructure gate (manual guide section 3:
rules, skills, hook probe with `cwd` ending in `\plugins\lord`, no leak)
and then T01, T03, T04, T05, T08 with Gemini in fresh conversations. Until
then: rules/skills/hooks loading from a *plugin* in the IDE, the hook cwd
for plugin hooks in the IDE, and whether the IDE displays an `ask` reason
are unverified.

## 15. Known limitations

- Plugin hooks in the IDE depend on the documented cwd; if that were wrong
  the launcher would not start and PreToolUse would deny writes (the probe
  catches it before any scenario).
- A global plugin gates code edits in every Antigravity workspace; that is
  the intended model and the user's choice (uninstall or disable to undo).
- Confirmation-boundary approval is inferred from the gated file changing;
  a shell command that rewrote the file would read as approval. A model can
  `task confirm` without asking (labelled model-reported). An ambiguity the
  model never records is invisible.
- Whether the IDE shows the `ask` reason text to the user is not verified.
- The marker detector sees marker syntax only (not `# fix later, TODO`, not
  comment styles other than `#`, `//`, `/* */`, `--`, `;`, `<!-- -->`).
- Reuse search is lexical: in the rehearsal, "clean descriptions before
  storing" ranked `require_description` first and did not surface
  `normalize_text` (the T01 prompt's own wording does).
- Bypass detection is Python-only; import-based coverage and the
  unrelated-file component heuristic stay advisories.
- `python -m lord` in the agent's terminal needs the same interpreter the
  installer registered, or the `lord_cli.py` fallback.
- LORD's own repository no longer has workspace hooks; LORD development in
  Antigravity uses the installed plugin like any other project.

## 16. Custom-agent status

The five specialists are packaged in `plugin/agents/` and installed with
the bundle. Antigravity documents plugin agents for Antigravity 2.0 and the
CLI; the IDE's documentation does not list them, and no live run has
invoked one. Status: DOCUMENTED / PACKAGED / NOT LIVE-VERIFIED. No core
behaviour depends on them.

## 17. What is proven and what is not

| Capability | Classification | Basis |
|---|---|---|
| Deterministic core (index, refs, impact, reuse, diff, verify facts) | PROVEN | 255 tests; live Baselines A and B |
| Marker fact by syntax | PROVEN (by fixtures) | 16 marker tests; 0 false positives on LORD's history |
| Verification record and reconciliation | PROVEN (by tests) | 5 contract tests; not yet used in a live run |
| Hooks in a trusted IDE workspace (workspace install) | PROVEN | 8A / 8A.1 live, 288 decisions, no errors |
| Hooks, rules, skills from an installed plugin, in the IDE | UNPROVEN until the live gate | rehearsal 15/15 outside the IDE |
| Plugin hook cwd = plugin folder | ENVIRONMENT-DEPENDENT | shipped docs; observed in the CLI (Phase 6) |
| Installer (validate, idempotency, update, rollback, uninstall, refusal) | PROVEN (in fixture directories) | 10 plugin tests; never run against the real `~/.gemini` |
| Demo isolation and memory isolation | PROVEN | acceptance and release tests, rehearsal |
| Portability to a non-Python workspace | PARTIALLY PROVEN | JS fixture: gate, steps from package.json, plugin skills; no live non-Python run |
| Confirmation boundary as a user decision | PARTIALLY PROVEN | fixture tests; the IDE's display of the ask reason is unverified |
| Clarifying questions asked by Gemini | MODEL-DEPENDENT | 0 of 16 live runs |
| Bypass, copy, bloat, unrelated-file, coverage signals | HEURISTIC | labelled as such everywhere |
| Plugin custom agents in the IDE | UNPROVEN | section 16 |

## 18. Git

See the final phase message for the commit hash(es) and push result.

## 19. Phase 9 readiness

Not ready yet, by the phase's own rule: Phase 9 needs the live
separate-workspace gate to pass (plugin loaded, hooks fire with the plugin
cwd, no leak) and the five scenarios recorded. The engineering side is
ready: evidence records now carry harness version, workspace kind, task
decisions and the verification reconciliation, and the workspace export
makes runs reproducible. Recommended next step: the user runs the manual
guide's sections 1-3; if the gate passes, T01, T03, T04, T05, T08 as
series C; then decide on Phase 9.
