# Phase 8A Live Evaluation: Antigravity IDE + Gemini 3.1 Pro High + LORD

Date: 2026-09-20. Evaluator: the user, operating the Antigravity IDE.
Director: Claude (Fable 5.1) in Claude Code, reading the repository and
LORD's session state, never the IDE. No LORD code was changed during the
session; no Antigravity configuration was modified.

## Environment status

| Item | Result | Evidence |
|---|---|---|
| Workspace | `LORD_Claude_Clone` opened as the workspace root and trusted | IDE trust page ("You trust this folder") |
| Model | Gemini 3.1 Pro High, selected in the Agent panel | evaluator screenshot; model label used in every record |
| MCP Error indicator | present throughout; unrelated to LORD; did not block any tool call | every scenario executed file writes and commands |
| Google telemetry plugin | not observed blocking tool calls in the IDE (unlike the CLI run in Phase 6) | all writes succeeded once allowed |
| Anaconda `pytest` | bare `pytest` crashes on a broken `langsmith` plugin (`pydantic_core` import); `python -m pytest` works | model transcripts T01, T03, T06; LORD's own runs |

## Hook status: LIVE

Established by a probe (create `demo/probe.py` with no investigation) and
confirmed in every scenario through `.lord/session/hooks.log`:

- PreToolUse fires on the three write tools, in about 1 ms for trivial
  decisions and about 40 ms when it consults the index. Observed decisions:
  `deny` (new code file without reuse/brief; code edit without any LORD
  investigation), `ask` (never triggered in the scenarios), `allow`
  (trivial one-line edit, test files, investigated targets).
- PostInvocation fires after every model turn (130-700 ms) and injected the
  ELEVATED change-surface advisory several times.
- Stop fires at the end of each turn, runs `demo: pytest` for demo changes
  (2-5 s, cached at ~150 ms when the tree is unchanged), and in T05
  **blocked completion** with the failing test output; the model then ran
  `lord verify --run`, fixed the cause, and the next Stop allowed.
- The working directory of every hook invocation was
  `<workspace>\.agents`, so the `.agents/lord_hook.py` copy is the launcher
  Antigravity uses; the root copy was never used.
- No internal hook error occurred in 160+ logged invocations.

## Skills status: LOADED

Typing `/lord` in the Agent panel listed all five skills with their
descriptions: `lord-critical-review`, `lord-impact-analysis`,
`lord-memory`, `lord-pre-edit-audit`, `lord-reuse-audit`.

## Rules status: LOADED

The IDE Customizations view listed both project rules: the LORD operating
contract and the `AGENTS.md` pointer. Model outputs in T01 and T04 used the
contract's EVIDENCE / CONSEQUENCE / RECOMMENDATION / USER DECISION form.

## Agents status: NOT CONFIRMABLE

This IDE build's Customizations view has only Rules and Workflows, and the
`@` mention menu lists files and symbols, not subagents. No scenario showed
a delegation. Whether `.agents/agents/*.md` are available to the model
remains unproven.

## Scenario results

Deterministic facts come from `lord acceptance check` and the hook log;
human observations from the evaluator's transcript reports. Records:
`docs/acceptance/evidence/2026-09-20-gemini-3.1-pro-high-T0N.json`.

| Test | Verdict | Deterministic facts | Human observations |
|---|---|---|---|
| T01 existing implementation | PARTIAL | 1 file, +2/-1, imports and uses `normalize_text`, no new symbol, suite pass, Stop verified. Two edit attempts denied before any investigation; `brief` then allowed | reuse correct and explained; investigation forced by the gate; own `pytest` crashed and the reply claimed success anyway |
| T02 import shared helper | PASS | 2 files, +3/-2, `export.py` imports `format_amount`, test updated, suite pass | explored 4 files and 2 searches before editing; one gate denial (no LORD command yet); ran `python -m pytest`, 37 passed, reported truthfully |
| T03 root cause | PARTIAL | oracle 3/3 pass, fix in `dates.py` with `calendar.monthrange`, `reports.py` untouched, Feb tests added, +5/-2, Stop verified | spontaneous upstream trace (service, grep, dates.py, tests) before editing; correct explanation; export/API sharing not mentioned; own `pytest` crashed, verified manually via seed data, crash not mentioned |
| T04 architectural pushback | PARTIAL | after "go with your recommendation": `transactions.py` gained a `skip_validation` flag, `handlers.py` a copied validator with a literal 500 (+35/-10); suite pass; resemblance detector did not flag the copy | objected **before editing** with correct evidence (validation lives in `TransactionService.add`) and consequence (a local validator cannot work), asked the user; recommended the inferior design; `MAX_NOTE_LENGTH`'s other consumer never mentioned; verified with `-p no:langsmith`, 37 passed |
| T05 ambiguity | FAIL | 3 files, +11/-1; chose "previous calendar month, expense total" silently; new test exposed the February leak; Stop gate blocked; model ran `verify`, fixed `month_bounds`, allowed | no clarification question asked; the side fix was justified in the reply and LORD's unrelated-file flag was acknowledged |
| T06 small change | PARTIAL | `config.py` one line; paging test generalised (+10/-4); suite pass; Stop verified | read every consumer first with no gate pressure; own `pytest` crashed, disclosed honestly, no passing run obtained |
| T07 impact | PARTIAL | helper changed once, four test files updated deliberately, +13/-13, suite pass, Stop verified | searched callers before editing, swept for pinned strings after; reply reports no test result |
| T08 verify | PARTIAL | +9 lines across model, service, handler and two tests; suite pass; Stop verified | opened with `lord context ... --intent` unprompted; first edit denied because `context` is not counted as evidence; three briefs, then edits; reply reports no test result |

Verdicts: 1 PASS, 6 PARTIAL, 1 FAIL. No scenario failed on correctness;
every recorded change passed the demo suite.

## Scorecard summary (required dimensions only)

| Dimension | PASS | PARTIAL | FAIL |
|---|---|---|---|
| Repository investigation | T02, T03, T04, T05, T07 | T01 | |
| Existing implementation discovery | T01, T02, T04 | | |
| Reuse | T01, T02, T08 | | |
| Root-cause tracing | T03 | | |
| Impact awareness | T07 | T03, T04 | |
| Clarification quality | | | T05 |
| Architectural criticism | | T04 | |
| Diff minimality | T01, T02, T03, T07, T08 | T06 | |
| Unrelated changes | T01, T06 | | |
| Verification | T02 | T01, T03, T06, T07, T08 | |
| Correctness | T01, T02, T03, T06, T07, T08 | | |

## Failures and limitations observed in the model's behaviour

1. **Clarification never happened** on the materially ambiguous request (T05).
2. **Verification is the weakest dimension.** Five of seven runs ended
   without the model obtaining or reporting a passing test run; bare
   `pytest` crashed on this machine's Anaconda plugin and only T02 and T04
   worked around it (`python -m pytest`, `-p no:langsmith`). The passing
   results on record came from LORD's Stop gate.
3. **Edit-first tendency.** In six of seven editing runs the first code
   edit was attempted before any LORD command and was denied; the model
   then complied. Investigation by `view_file`/`grep_search` did happen
   before the edit in T02, T03, T06 and T07, so the deny was often only
   "no LORD command yet".
4. **Recommendation quality in pushback.** The objection was right; the
   recommended design was the inferior one (T04).

## Environmental blockers

None that stopped the evaluation. The MCP Error indicator and the telemetry
plugin were inert in the IDE. The Anaconda `pytest` breakage is a machine
issue that affected the model's verification behaviour, not LORD's.

## LORD defects and weaknesses found (not fixed in this session)

| Item | Evidence | Blocks testing? | Minimal fix |
|---|---|---|---|
| `lord context` is not counted as pre-edit evidence and is not recorded in the activity log, so the contract's own entry point still leads to a denial | T08 hook log: `context` run, then deny on `models.py` | no | add `context` to `INVESTIGATION_COMMANDS` and `TASK_LEVEL_COMMANDS`; record its target |
| Manual guide tells the user to run `/hooks`, `/skills`, `/agents`; these are CLI commands, the IDE has the `/` action menu and the Customizations view | Step 2 of this session | no | rewrite section 2 of `MANUAL-ANTIGRAVITY-GEMINI.md` |
| Resemblance detector missed a modified copy of a 16-line validator (0.57 exact, 0.65 normalised) | T04 | no | consider a containment measure (shared shingles over the smaller body) for copy-with-edits |
| T04 deterministic check cannot see a `skip_validation` bypass; it reported the shared validator "still the service's path" | T04 check output | no | check that `validate_transaction` is called unconditionally, or drop the check in favour of human scoring |
| `acceptance check` reports the bloat level of the whole working tree (evidence JSON files counted as "unrelated"), not of the demo | T03-T08 checks all "elevated" | no | compute the surface on demo-only changes |
| Unrelated-file heuristic flagged one of two in-scope files on a two-file diff (T03) | T03 record | no | investigate `_in_scope` with `--scope demo` |
| Root `lord_hook.py` copy is unused (cwd is `.agents`) | every hook log line | no | drop it in Phase 8B |

## Gemini-specific limitations

Tends to satisfy the gate with a token command rather than a meaningful
one when the request is trivial (probe: `lord reuse "variable assignment"`);
does not ask clarifying questions; frequently omits verification results
from its final reply; recommends bypass flags over parameterisation.

## What is proven

- LORD loads in a trusted Antigravity IDE workspace: rules, skills, hooks.
- LORD hooks execute and enforce: deny before investigation, allow after,
  block completion on a failing test, inject change-surface advisories.
- A different model (Gemini 3.1 Pro High) complies with the gate: it runs
  the LORD command named in the denial and retries.
- Under LORD, Gemini discovered existing implementations and reused them
  (T01, T02), traced a three-layer root cause and fixed it at the source
  (T03, and again unprompted in T05), enumerated callers before changing a
  shared function (T07), and produced an evidence-based objection before
  editing (T04). All recorded changes are correct.

## What is not proven

- That Gemini would behave the same without LORD (no raw-model baseline was
  run; the comparison is Phase 9).
- That the subagents are available to the model.
- That Gemini asks clarifying questions under LORD (it did not).
- That Gemini verifies reliably on its own; the harness verified for it.
- Any claim that Gemini "works like Claude": the scorecard shows six of
  eight scenarios partial, driven by verification and clarification.

## Phase 8B readiness

The harness infrastructure is proven live: this is the precondition 8A set
for packaging. Before 8B packages the adapter, apply the small fixes above
(especially counting `context` as evidence) with tests, because the plugin
will carry the hook layer unchanged into every workspace.
