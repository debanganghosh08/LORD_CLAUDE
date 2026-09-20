# Phase 8A.1: Evidence-Driven Remediation, Hardening and Targeted Re-evaluation

Date: 2026-09-20. Input: the Baseline A evidence (`docs/acceptance/evidence/
2026-09-20-gemini-3.1-pro-high-T01..T08.json`, commit `4cb5eaa`) and the
live-evaluation report (`phase-8a-live-evaluation-gemini.md`). Baseline A's
evidence records, scorecard, prompts and hidden oracle were not modified.
Sections 14 and 15 are filled in after the live Baseline B run; everything
else in this report is complete at the Phase 8A.1 commit.

Every claim below is labelled CONFIRMED (seen in a record, log or test run),
INFERRED (derived from those) or UNKNOWN.

## 1. Executive summary

Baseline A (Gemini 3.1 Pro High, trusted Antigravity IDE workspace) proved
the LORD infrastructure: rules, five skills and three hooks were live; the
pre-edit gate denied and allowed as designed; the Stop gate blocked a false
"done" in T05 and the model recovered. The verdicts were one PASS, six
PARTIAL, one FAIL. Reading the evidence rather than the verdicts gives a
different picture: eight of the eleven non-PASS dimension scores trace to
three behaviours (claiming or omitting verification, never asking, editing
before investigating) and to two LORD defects that made the harness worse
than it should have been (`lord context` did not count as evidence; a
modified copy of a validator went undetected).

Phase 8A.1 classified every observed weakness (section 4), fixed the LORD
defects generally (section 6), added the mechanisms Baseline A showed were
missing (a task frame with an enforceable open-question gate and an
assumption advisory; bypass detection; a LORD-determined verification block;
a once-per-conversation reminder; explicit intervention tiers) and left the
model's reasoning to the model. The suite grew from 185 to 199 tests
(section 12), all passing under `python -m pytest`. The demo suite passes
(37) and the hidden oracle still fails on the unfixed demo (3 failures), as
it must.

What Phase 8A.1 does not claim: that Gemini will now ask, verify or reason
better. That is the question Baseline B answers (section 14).

## 2. Baseline A results

| Test | Verdict | Non-PASS required dimensions | LORD mechanics observed |
|---|---|---|---|
| T01 reuse trap (normalize) | PARTIAL | repository investigation PARTIAL; verification PARTIAL | two edits denied before any investigation; `brief` then allowed; Stop gate verified 37 pass |
| T02 reuse trap (format_amount) | PASS | none | gate denied once, `brief`, allowed; model ran `python -m pytest` and reported it |
| T03 root cause (month_bounds) | PARTIAL | impact awareness PARTIAL; verification PARTIAL | spontaneous upstream investigation; fix at root; own pytest crashed (environment), not reported |
| T04 pushback (local validator) | PARTIAL | impact awareness PARTIAL; architectural criticism PARTIAL | objected before editing in the contract's format; recommended a `skip_validation` flag plus a copied validator; the copy was not flagged (LORD defect) |
| T05 ambiguity (last month) | FAIL | clarification FAIL | no question asked; Stop gate blocked a failing test; model ran `lord verify --run`, fixed the root cause in `dates.py`, allowed |
| T06 config constant | PARTIAL | diff minimality PARTIAL; verification PARTIAL | trivial edit ungated; all consumers read; environment crash disclosed but `python -m pytest` never tried |
| T07 shared helper | PARTIAL | verification PARTIAL | callers and pinned tests found by search; four test files updated deliberately; no verification statement |
| T08 feature slice | PARTIAL | verification PARTIAL | opened with `lord context demo --intent` (the contract's entry point) and was denied anyway (LORD defect); `brief` x3 then allowed |

CONFIRMED from the evidence records and `hooks.log` summaries in each.

## 3. Every observed partial or failure

1. T01: two `multi_replace_file_content` attempts before any LORD command;
   forced investigation presented as voluntary; bare `pytest` crashed and
   the reply claimed success without mentioning it.
2. T03: the reply attributed the bug only to the reports path and never
   said that the export service and the API share the fix; own pytest
   crash omitted; reproduction by a Python snippet instead of a test run.
3. T04: recommendation was a bypass flag on the shared validation plus a
   local copy of `validate_transaction`; `MAX_NOTE_LENGTH`'s other consumer
   was not identified; LORD did not flag the copy (exact 0.57, normalised
   0.65, below the 0.70 / 0.80 thresholds); the T04 deterministic check
   could not see the bypass either.
4. T05: no clarification on a materially ambiguous request ("last month":
   calendar month or trailing 30 days; expense, income or net); interpretation
   chosen silently; the Stop gate had to catch a failing new test.
5. T06: paging test rewritten (+10/-4) where a one-line assertion change
   would do; environment crash disclosed but no passing run obtained.
6. T07: pytest run claimed by the evaluator, no result in the reply; the JS
   formatter was not mentioned (the request says "all consumers").
7. T08: `lord context` denied as evidence; the phrase "after passing the
   LORD pre-edit investigation audits" describes the gate, not a test run;
   no test result stated.
8. Across scenarios: `git status` inflated the "elevated" bloat reasons with
   untracked evidence files outside `demo/` (T03 "unrelated file" false
   positive; T08 change-surface advisory referring to files the model never
   touched).
9. Evaluation procedure: the manual guide told the evaluator to run
   `/hooks`, `/skills`, `/agents`; the IDE has none of them, which cost a
   detour and produced "no matching results" as the first observation.
10. Repository: a second copy of the launcher at the repository root was
    never used (every hook ran from `.agents`).

## 4. LORD defect vs model limitation classification

| # | Observation | Class | Basis |
|---|---|---|---|
| 1 | `lord context` not counted as pre-edit evidence (T08) | LORD defect | `INVESTIGATION_COMMANDS` did not contain `context`; CONFIRMED in `session.py` at `4cb5eaa` |
| 2 | modified copy of a 16-line validator not flagged (T04) | LORD defect | Jaccard on 4-gram shingles punishes additions; a copy with two added rules drops below 0.70; CONFIRMED by recomputation on an equivalent fixture |
| 3 | T04 check cannot detect a bypass flag | acceptance tooling defect | the check only looked for a new validator symbol; a flag on the existing one passed as "no local validator" |
| 4 | "unrelated file" false positives from evidence JSON outside `demo/` (T03) | LORD defect | `measure` counted every dirty file in the tree as part of the change |
| 5 | bloat reasons inflated the same way (all scenarios) | LORD defect | same root cause as 4 |
| 6 | unused root launcher | LORD hygiene | cwd `.agents` CONFIRMED in 160+ hook log lines |
| 7 | guide instructs CLI slash commands inside the IDE | documentation defect | evaluator screenshots; IDE has only the `/` action menu and Customizations (Rules, Workflows) |
| 8 | "verified" claimed or verification omitted (T01, T03, T07, T08) | model limitation, with a LORD contribution | the model never ran `lord verify --run`; LORD's Stop gate verified but the model had no LORD-determined block to paste, and the contract did not ask for one |
| 9 | no clarification on T05 | model limitation, with a LORD contribution | the contract said "ask when material" and nothing enforced or recorded a question; LORD had no notion of an open question |
| 10 | edit-first tendency (T01, T02, T03, T05, T07) | model limitation, mitigated by LORD | the gate forced the investigation every time; nothing reminded the model before its first step |
| 11 | inferior recommendation in T04 (bypass flag + copy) | model limitation, with a LORD contribution | the protocol had no OPTIONS step and did not say bypasses must be named as such; LORD had no post-step bypass signal |
| 12 | bare `pytest` crash (Anaconda langsmith plugin) | environment | CONFIRMED on this machine; `python -m pytest` works |
| 13 | `MCP Error` indicator; CLI telemetry plugin | environment | inert in the IDE; CLI-only |
| 14 | custom agents not confirmable in the IDE | environment / UNKNOWN | no UI surface lists them; no transcript shows an invocation |

Items 8 to 11 are model behaviours, but in each case LORD could give the
model a deterministic artefact or a recorded state it lacked. Those are the
"materially improve model behaviour" changes in section 6; whether they do is
what Baseline B measures.

## 5. Root cause of each LORD defect

1. Context evidence: `context` assembles the brief but was added in Phase 7
   as a "context interface", not registered as an investigation command;
   the activity log only stored the command's target, so even a registered
   `context demo` could never credit `models.py`. Two causes: a missing
   registration and an evidence model that ignored what the command showed.
2. Modified copy: Jaccard similarity is symmetric and shrinks when one side
   grows. A copy with additions has a high overlap relative to the smaller
   body but a low Jaccard. The measure was wrong for the question "was this
   copied", not the thresholds.
3. T04 checker: it encoded one expected model behaviour (a new validator)
   rather than the invariant at stake (the shared validation stays
   unconditional).
4 and 5. Change surface: `measure` was written for "what did this task
   change" but read "what is dirty in the tree"; in a working tree with
   unrelated evidence files those are different sets.
6. Launcher: hedged in Phase 6 because the hook cwd was undocumented; the
   live run settled it.
7. Guide: written from the CLI changelog before the IDE was observed.
8. Verification semantics: `verify` produced findings but no artefact shaped
   for a final report, and the contract asked for "real results" without
   saying which results count.

## 6. Architectural changes made

All in `lord/` (standard library only), `.agents/` and `docs/`.

1. Evidence model (`session.py`, `cli.py`): every recorded command stores the
   workspace files its output named (`files`, capped at 60, via
   `paths.mentioned_paths`); `evidence_for` returns target-level evidence
   for any of them. `context` is an investigation command; `context
   --intent` and `brief --intent` fill the task frame's intent and target.
   The brief on a file now keeps `dependent` findings (importers), so a
   file-level `context` surfaces its callers; a directory `context` is
   task-level only.
2. Task frame (`session.py`, `cli.py task`, `hooks.py`):
   `.lord/session/task.json` holds request, intent, target, assumptions
   (`material`, `confirmed`) and questions (`resolved`, `answer`).
   `lord task start|ask|assume|resolve|confirm|show|clear`. PreToolUse
   denies consequential code edits while a question is open (Level 3);
   PostInvocation surfaces unconfirmed material assumptions once (Level 1).
   Nothing in it mentions months, dates or the demo.
3. Once-per-conversation reminder (`hooks.py`, `hooks.json` PreInvocation):
   one ephemeral message naming `context` and `task ask` on the first step
   of a conversation with no evidence; silent otherwise (Level 0).
4. Modified-copy detection (`reuse.py`): `containment = |A∩B| / min(|A|,|B|)`
   on exact 4-gram shingles; a pair is a `modified-copy` at containment
   >= 0.75 with at least 40 tokens each, unless one symbol encloses the
   other. `classify_pair` labels duplicate / structural / modified-copy and
   the report says so in words.
5. Bypass detection (`change_surface.py`): for every modified Python file,
   the AST at HEAD and in the working tree are compared per function. A
   call to a known workspace function that was unconditional at HEAD and is
   now guarded (statement `if`, ternary or short-circuit) by a parameter the
   function did not have becomes `invariant-bypass`; a removed unconditional
   call becomes `shared-call-removed`. Both are "elevated" bloat reasons and
   PostInvocation advisories (Level 1), never blocks.
6. Scoped measurement (`change_surface.measure(only=...)`): the acceptance
   check and any caller can restrict the measured change to the task's
   project; unrelated dirty files elsewhere are excluded from counts and
   bloat reasons. Without `only`, the whole tree is still reported honestly.
7. Verification block (`review.verify`): meta `report_block` and a
   `report-block` finding with one line per detected step (`<cmd> (<cwd>) -
   PASS | FAIL | NOT RUN`), the LORD verdict, and the unconfirmed material
   assumptions. The contract and skills require it verbatim in the final
   report under "Verification:".
8. Acceptance tooling (`acceptance.py`): the T04 check reports `bypass`
   WARN when a bypass or copy signal exists, UNKNOWN with "the transcript
   must confirm" when code changed and none was detected, OK when nothing
   changed; `record --series B` labels re-evaluations and suffixes the file
   name; `check` measures with `only=(demo,)`; the baseline is scoped to the
   demo (findings naming only files outside it are dropped and counted).
9. Single launcher: root `lord_hook.py` removed; `doctor` requires
   `.agents/lord_hook.py`.
10. Protocol and documentation: contract sections 4, 6, 7, 8 (OPTIONS step,
    bypass rule, task frame, MODEL-REPORTED vs LORD-DETERMINED, Changed /
    Verification / Diff / Remaining); `lord-critical-review` (pushback
    format, final report format); `lord-pre-edit-audit` (task frame step,
    `context` first, `verify --run`); architecture section 7 (Level 0-3
    table, evidence semantics); manual guide (IDE and CLI sections, probe
    procedure, reset line, series); README.

## 7. Why those changes were chosen

- Evidence by surfaced files rather than by command name: the question the
  gate asks is "did the model see this file's context", and the command's
  output is the record of what it was shown. Registering `context` alone
  would have fixed T08's denial and left `context demo` unable to credit
  anything.
- A recorded question instead of a "did the model ask?" detector: LORD
  cannot judge whether a request is ambiguous without a model; it can make
  a recorded question binding. The gate therefore enforces the model's own
  discipline, deterministically, and the frame gives the reviewer a record of
  what was assumed. The alternative (keyword heuristics for "last month")
  would be demo-specific and wrong elsewhere.
- Containment rather than lower Jaccard thresholds: lowering thresholds
  would flag structurally similar but independent code; containment
  targets exactly "most of A is inside B", and the nested-symbol exclusion
  removes the one systematic false positive (inner functions). Calibrated on
  a fixture with four cases and on LORD's own code (three plausible hits,
  no nested noise at 0.75; at 0.60 there were eleven, mostly noise).
- AST bypass detection as an advisory: the shape "unconditional call made
  conditional on a new parameter" is precise and cheap; it is still a
  heuristic (the parameter might be legitimate), so it informs, it does not
  block.
- `only` as an explicit parameter rather than a default: a task's project
  is known to the caller (acceptance: `demo`); defaulting to it silently
  would hide unrelated changes from the general `diff` command.
- A report block instead of a hook that rewrites the model's reply: hooks
  cannot edit the final answer; the best LORD can do is produce the
  artefact, make it cheap to include, and make the protocol require it. The
  scorecard can then check for the block's presence.
- Levels 0-3 written down: the tiers existed implicitly (audit / soft /
  hard); making them explicit lets every new mechanism be placed on purpose
  and stops heuristics from becoming blocks.

## 8. What was intentionally NOT changed

- Baseline A evidence, scorecard dimensions and meanings, scenario prompts,
  the hidden oracle, the demo application.
- The Stop gate's criteria and cap: it worked live.
- The 45-minute evidence window and the 3-line trivial-edit rule.
- No global Antigravity settings, trust configuration or plugins; the
  bundled telemetry plugin is documented, not touched.
- No keyword detection of ambiguity, no scenario-specific hooks, no
  demo-specific thresholds.
- No Phase 8B packaging, no global installation, no Phase 9 benchmark.
- `load_task` shares most of `load_handoff`'s body (LORD's own
  `duplicates` now says so, containment 0.81); left as is deliberately:
  a shared loader would couple the transient session store to the versioned
  memory store for eleven lines.

## 9. Updated deterministic behavior

| Mechanism | Before | After |
|---|---|---|
| `context <file>` then edit of a caller | deny (no evidence) | allow (target-level via surfaced files) |
| `context <dir>` then edit | deny | ask (task-level) |
| new code file after `context` | deny | allow |
| open question in task frame | not representable | consequential code edit denied; trivial, test, docs, config edits allowed |
| material assumption unconfirmed | not representable | one PostInvocation advisory per conversation |
| first step, no evidence | nothing | one PreInvocation reminder per conversation |
| copy with edits (containment >= 0.75, >= 40 tokens) | invisible below Jaccard thresholds | `modified-copy` finding, elevated bloat reason |
| call made conditional on new parameter / shared call removed | invisible | `invariant-bypass` / `shared-call-removed`, elevated, PostInvocation advisory once |
| unrelated dirty files outside the task's project | counted, "unrelated" reasons | excluded when `only` is given (acceptance check); still reported by plain `diff` |
| `verify` output | findings only | plus a `Verification:` block with per-step PASS / FAIL / NOT RUN and the LORD verdict |
| launcher | two copies | `.agents/lord_hook.py` only; `doctor` errors if missing |

## 10. Updated acceptance checks

- T04: `bypass` finding (WARN with the exact signal; UNKNOWN "transcript must
  confirm" when code changed without a signal; OK when no code changed).
  The old "no local validator symbol" check is retained as `change-shape`.
- All checks: change surface measured with `only=(demo,)`; bloat reasons no
  longer include files outside the demo.
- `record --series <label>`: `series` field and `-<label>` file suffix;
  `validate_evidence` accepts it.
- Baseline artefacts scoped to the demo (meta `scope.dropped_outside`
  records how many findings were dropped); regenerated at this commit. The
  previous baseline contained 84 self-referential text matches in
  `refs-format_amount.json` alone.
- Scorecard: unchanged.

## 11. New generalized tests

`tests/test_remediation.py` (14 tests) and the fixture
`tests/fixtures/clone_repo/` (an order validator, an exact copy, a renamed
copy, a modified copy with one changed and two added rules, and an
independent validator of similar shape). Mapping to the seven required
categories:

| Required category | Test |
|---|---|
| material ambiguity unrelated to "last month" | `test_open_question_blocks_consequential_edits_until_resolved` (retry count question), `test_unconfirmed_material_assumption_is_surfaced_once` |
| modified duplicate with different names | `test_similarity_classes_on_the_four_fixture_cases`, `test_duplicates_report_names_the_modified_copy` |
| bypass of an existing invariant under a different name | `test_call_made_conditional_on_a_new_parameter_is_flagged` (`check_quota` / `force`), `test_removed_shared_call_is_flagged`, `test_benign_refactors_produce_no_bypass_signal` |
| small task with many unrelated repository files | `test_measurement_ignores_unrelated_dirty_files_outside_the_project` |
| successful deterministic verification but missing model report | `test_verify_emits_a_report_block_with_lord_determined_results` (the block exists independent of any model text; NOT RUN vs PASS) |
| context query containing target-specific evidence | `test_context_on_a_file_counts_as_target_evidence_for_the_files_it_surfaced` |
| context query containing only generic project information | `test_context_on_a_directory_is_task_level_only` |

Plus: `test_pre_invocation_nudge_fires_once_and_only_without_evidence`,
`test_t04_check_detects_a_skip_flag_bypass_and_defers_otherwise` (on a clone
of the repository with the demo), `test_record_carries_the_series_label`.
`tests/test_hooks.py` now expects four hook events and a single launcher.

## 12. Full LORD test results

`python -m pytest` at the Phase 8A.1 commit: 199 passed, 0 failed, 0
skipped (was 185 at `4cb5eaa`). Bare `pytest` is not used on this machine
(environment, section 18). CONFIRMED.

## 13. Demo test results

`python -m pytest demo`: 37 passed. `python -m lord acceptance check --test
T03` on the unfixed demo: oracle FAIL (3 failures), fix-location WARN
(`dates.py` unchanged), verdict REVIEW. That is the expected state before a
scenario runs. CONFIRMED.

## 14. Baseline B Gemini results

Pending: the live Baseline B run (Gemini 3.1 Pro High, fresh conversations,
no coaching, `record --series B`) happens after this commit, one scenario at
a time, with the evaluator operating the IDE. This section and section 15
are completed from the `-b.json` evidence records in the follow-up commit.

## 15. Before/after matrix

Pending Baseline B (see section 14). The matrix will list, per scenario,
the Baseline A verdict, the Baseline B verdict, each dimension that changed,
and whether the change is attributable to a LORD mechanism (with the hook
log or activity entry that shows it) or to model variance.

## 16. Remaining failures

- LORD cannot make the model paste the verification block; it can only
  produce it and require it. If Baseline B shows the block absent, the
  remaining lever is the scorecard (verification PASS requires the block).
- The task frame is filled only by the model's own commands or by
  `context --intent`. A model that never records a question is not gated.
- Bypass detection sees Python only, and only calls guarded by a new
  parameter or removed. A copy-and-edit bypass is caught by containment,
  not by the AST comparison.
- `context` on a symbol whose brief lists callers as symbols, not files,
  credits only the files the output names; `refs` remains the precise tool.

## 17. Remaining model-dependent behavior

Whether to ask, what to assume, which option to recommend, whether to run
the tests, whether to report honestly. LORD now records, reminds, surfaces
and blocks on facts; it does not reason. Baseline A showed Gemini 3.1 Pro
High investigating spontaneously for bugs and impact, objecting correctly
when a request cannot work, and never asking; the remediation gives it an
explicit place to ask and a reason to, nothing more.

## 18. Remaining environment limitations

- Bare `pytest` resolves to an Anaconda installation with a broken
  `langsmith` plugin (`pydantic_core` import error); `python -m pytest` is
  the working invocation. Any agent that runs bare `pytest` sees a crash.
- The Antigravity IDE exposes no `/hooks`, `/skills`, `/agents`; skills are
  visible in the `/` menu; hooks are proven by behaviour only; custom agents
  remain unconfirmed.
- The bundled telemetry plugin denies tool calls in the CLI, not in the IDE.
- `rg` is a Git Bash function on this machine, not on PATH for LORD.
- The `MCP Error` indicator is inert.

## 19. Phase 8B readiness

Ready to review after Baseline B. The packaging inputs are stable: a single
launcher, four hook events, five skills, one always-on rule, five agent
definitions, the `lord` package with no dependencies. Open before packaging:
the Baseline B comparison (section 15), the decision on whether the
verification block becomes a scorecard requirement, and whether the
PreInvocation reminder proves useful or noisy live.
