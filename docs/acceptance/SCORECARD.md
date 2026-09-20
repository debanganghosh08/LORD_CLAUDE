# LORD Acceptance Scorecard

Eleven independent dimensions. Each is scored PASS, PARTIAL, FAIL or N/A on
observable criteria. No dimension compensates for another; a run's final
verdict is the worst score among the dimensions the scenario marks as
required (see the test plan). The deterministic parts are prefilled by
`python -m lord acceptance record`; the rest is scored from the transcript.

| Dimension | PASS | PARTIAL | FAIL |
|---|---|---|---|
| Repository investigation | Before editing, the agent read the definition and the direct callers of what it changed (transcript shows the files opened or a LORD command such as `brief`, `refs`, `impact`; `.lord/session/activity.jsonl` has entries). | Read the target file only, or investigated after the first edit. | Edited without opening any related file; no LORD command recorded; the pre-edit hook denied and the agent worked around it without investigating. |
| Existing implementation discovery | Named the existing symbol (file and name) that already covers the request before proposing anything. | Found it only after starting to write, or found a related but not the closest implementation. | Never mentioned the existing implementation. |
| Reuse | Imported or extended the existing symbol; `acceptance check` reuse item is OK; no new symbol with overlapping responsibility. | Reused it but also added a wrapper or partial copy; or extended it with more surface than needed. | Wrote a parallel implementation (new function/constant/class) of behaviour that existed. |
| Root-cause tracing | Moved upstream from the symptom through the call chain and fixed the actual cause; oracle tests pass; the symptom layer is untouched. | Identified the cause but fixed it downstream, or fixed the cause and also patched the symptom. | Patched the symptom only; oracle tests still fail or only the reported case passes. |
| Impact awareness | Listed the callers, dependents and tests of what it changed before changing it, and handled each (updated tests deliberately, kept callers working). | Mentioned impact vaguely, or discovered broken callers only from a failing test run. | Broke a caller or test and did not notice, or changed shared behaviour without mentioning any consumer. |
| Clarification quality | Asked one targeted question naming the two interpretations and their consequences, and waited. | Asked a vague or unnecessary question, or asked after starting to implement. | Silently chose an interpretation on a materially ambiguous request; or asked on a trivial request. |
| Architectural criticism | Stated one evidence-based objection with file references, the consequence, a recommendation, and left the decision to the user. | Objected without evidence, or with evidence but no alternative, or repeated the objection after the decision. | Complied blindly with a request that the repository contradicts; or manufactured an objection on a routine request. |
| Diff minimality | Diff is the smallest coherent change: no new abstraction, no new file unless a genuinely new responsibility, line growth in proportion to the task (`acceptance check` small-diff item OK where applicable). | Somewhat larger than needed (helper extracted, extra parameter) but coherent. | New files, wrappers or layers the task did not need; growth several times the task's size. |
| Unrelated changes | Only files the task requires (plus their tests) changed; `lord diff --scope demo` reports no unrelated files. | One unrelated edit (formatting, rename, comment cleanup) that is clearly incidental. | Drive-by refactors, formatting churn, or dependency/manifest changes the task did not ask for. |
| Verification | Ran the demo tests (and `lord verify` or the Stop gate ran) before declaring completion; reported the real result. | Ran a subset, or ran tests but reported completion despite a failure with an explanation. | Declared completion without running anything, or claimed tests passed when they did not. |
| Correctness | The requested behaviour works; demo suite passes; for T03 the oracle passes. | Works for the stated case but a neighbouring case regressed or is untested. | Does not work, or the suite fails. |

## Scoring rules

- Score every dimension the scenario marks as required; mark the others
  N/A. Do not leave a required dimension blank.
- PASS requires the observable criterion, not an impression. Cite the
  transcript position or the evidence field that shows it.
- The final verdict of a run is the worst required score: any required
  FAIL makes the run FAIL; all required PASS makes it PASS; otherwise
  PARTIAL.
- Record the same scenario for each model/harness pair separately. Never
  merge runs.
- The deterministic checks in the evidence file are inputs to the score,
  not the score. A `REVIEW` deterministic verdict means a human must look;
  it does not by itself mean FAIL.

## Required dimensions per scenario

| Test | Required |
|---|---|
| T01 | investigation, existing implementation discovery, reuse, diff minimality, unrelated changes, verification, correctness |
| T02 | investigation, existing implementation discovery, reuse, diff minimality, verification, correctness |
| T03 | investigation, root-cause tracing, impact awareness, diff minimality, verification, correctness |
| T04 | investigation, architectural criticism, impact awareness, existing implementation discovery |
| T05 | clarification quality, investigation |
| T06 | diff minimality, unrelated changes, verification, correctness |
| T07 | investigation, impact awareness, verification, correctness, diff minimality |
| T08 | verification, correctness, diff minimality, reuse |
