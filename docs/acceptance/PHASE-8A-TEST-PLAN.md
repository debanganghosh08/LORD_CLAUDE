# LORD Acceptance Test Plan (Phase 8A)

Evaluation environment: the `demo/` ledger application inside the LORD
workspace. The agent under test works in the LORD workspace (so the rules,
skills, agents and hooks in `.agents/` apply) and is told to work inside
`demo/`. Every scenario has a paste-ready prompt (`python -m lord acceptance
prompts`), observable expectations, failure conditions, and an oracle: the
engineering ground truth LORD itself established (`docs/acceptance/baseline/`).

Do not show this document, the baseline, or `docs/acceptance/oracles/` to
the agent under test. `lord.toml` keeps the oracles out of LORD's index.

Methodology for every scenario:

1. Reset: `git checkout -- demo && git clean -fd demo`, rebuild the index,
   clear `.lord/session/*.jsonl` and `*.log` (see `evidence/README.md`).
2. Paste the prompt exactly. Answer clarification questions only as the
   scenario says. Do not coach.
3. When the agent declares completion (or stops to ask), run
   `python -m lord acceptance record --test <ID> --model <label> --transcript <id>`.
4. Score the required dimensions from `SCORECARD.md` using the transcript
   and the evidence file; commit the evidence file.

Demo facts every scenario relies on (verified by `tests/test_acceptance.py`):

| Fact | Where |
|---|---|
| shared text helper `normalize_text` (trim + collapse whitespace), used only by `slugify`/`truncate_note` and its test | `demo/app/utils/text.py:13` |
| shared money helper `format_amount(cents, currency) -> "12.34 EUR"`, used by `ReportService.render` and `handlers.monthly_report`; `ExportService.monthly_csv` formats inline and does not import it | `demo/app/utils/money.py:30`, `demo/app/services/export.py` |
| shared constants `DEFAULT_PAGE_SIZE`, `MAX_NOTE_LENGTH`, `CURRENCY`, `CATEGORIES`, `KINDS` with 12 dependent files | `demo/app/config.py` |
| validators `validate_transaction` and `require_description` (description required, length limit) used by `TransactionService.add` and, through it, the API | `demo/app/validation.py` |
| shared date helper `month_bounds` used by `TransactionService.in_month`, which serves `ReportService.monthly_summary`, `ExportService.monthly_csv` and `handlers.monthly_report`/`export_csv` | `demo/app/utils/dates.py:18` |
| verification command | `cd demo && python -m pytest` (37 tests); LORD detects it as `demo: pytest` |

## T01

SCENARIO: existing implementation discovery under a different name.

USER PROMPT:

> In demo/, descriptions entered by users sometimes contain leading/trailing spaces and runs of multiple spaces. Add a function that cleans a description (trim the ends, collapse repeated whitespace to one space) and make TransactionService.add use it when storing the description.

EXPECTED LORD/GEMINI BEHAVIOR: investigates before writing, discovers that
`normalize_text` already does exactly this, says so, and wires it into
`TransactionService.add` instead of adding a new function.

EXPECTED FILE INVESTIGATION: `demo/app/services/transactions.py`,
`demo/app/utils/text.py` (or a `lord reuse`/`brief` call whose decision is
EXTEND with `normalize_text` first).

EXPECTED REUSE BEHAVIOR: `from app.utils.text import normalize_text` in
`transactions.py`; `description=normalize_text(payload["description"])`.

EXPECTED ARCHITECTURAL WARNING: none required; a one-line note that the
helper exists is the expected form.

EXPECTED DIFF CHARACTERISTICS: 1 source file (+2/-1 lines) and optionally 1
test file; no new symbol in `demo/app/`.

EXPECTED VERIFICATION: demo suite run; `test_add_assigns_ids_and_stores_cents`
still passes (it already expects "Bus" from "  Bus  ").

FAILURE CONDITIONS: a new `clean_description`/`normalize_description`/similar
function or regex anywhere in `demo/app/`; `normalize_text` never mentioned;
edit without opening `text.py` or running a LORD command.

ORACLE (ground truth): baseline `reuse-T01.json` decision `extend`, first
strong candidate `normalize_text`; `refs-normalize_text.json` shows no use
in `transactions.py` before the run; `acceptance check T01` requires a
confirmed reference from `transactions.py` afterwards and no new cleaning
symbol.

## T02

SCENARIO: import/reuse of a shared helper that a module does not import yet.

USER PROMPT:

> In demo/, the CSV export shows amounts like 650.00 while the monthly report shows 650.00 EUR. Make the export's amount column use the same formatting as the report.

EXPECTED LORD/GEMINI BEHAVIOR: finds that the report formats through
`format_amount`, imports it into `export.py`, updates the export test.

EXPECTED FILE INVESTIGATION: `demo/app/services/export.py`,
`demo/app/services/reports.py`, `demo/app/utils/money.py`,
`demo/tests/test_export.py`.

EXPECTED REUSE BEHAVIOR: `from app.utils.money import format_amount`;
replace the inline f-string.

EXPECTED ARCHITECTURAL WARNING: none required.

EXPECTED DIFF CHARACTERISTICS: 2 files (`export.py`, `test_export.py`),
about +3/-2 lines; no new symbol.

EXPECTED VERIFICATION: demo suite run and passing after the test update.

FAILURE CONDITIONS: a second formatter (new function, inline
`f"{...:.2f} EUR"`, or duplicated `CURRENCY` literal); `format_amount` not
referenced from `export.py`.

ORACLE: baseline `refs-format_amount.json` confirmed callers exclude
`export.py`; `reuse-T02.json` decision `extend` with `format_amount` first;
`acceptance check T02` requires the confirmed reference and no new
formatting symbol.

## T03

SCENARIO: root cause several layers below the symptom.

USER PROMPT:

> In demo/, the monthly report for February 2026 includes a transaction dated 2026-03-02 (Rent March). Please fix this. You can reproduce it with: python scripts/seed.py then GET /api/report?year=2026&month=2 (or call ReportService.monthly_summary(2026, 2) with the seeded data).

EXPECTED LORD/GEMINI BEHAVIOR: traces report -> `ReportService.monthly_summary`
-> `TransactionService.in_month` -> `month_bounds`, recognises that
`first + timedelta(days=30)` is only right for 31-day months, fixes
`month_bounds` (for example the day-28-plus-4-days idiom, or
`calendar.monthrange`), adds tests for February/April/December, and notes
that the export shares the fix.

EXPECTED FILE INVESTIGATION: `handlers.py`, `reports.py`,
`transactions.py`, `utils/dates.py`, `tests/test_dates.py` (or `lord trace
ReportService.monthly_summary` / `lord impact month_bounds`).

EXPECTED REUSE BEHAVIOR: none; no new date helper.

EXPECTED ARCHITECTURAL WARNING: mention that `ExportService.monthly_csv`
and the API share `in_month`, so the fix must live in the shared helper.

EXPECTED DIFF CHARACTERISTICS: `demo/app/utils/dates.py` (+2 to +6 lines)
and `demo/tests/test_dates.py`; `reports.py` untouched.

EXPECTED VERIFICATION: demo suite run; the evaluator runs the oracle
(`python -m pytest docs/acceptance/oracles -q -p no:cacheprovider`) which
must pass.

FAILURE CONDITIONS: a month filter added in `ReportService` or the handler
(symptom patch); `month_bounds` unchanged; fix only for February (for
example special-casing 28 days) so April still includes 1 May; export still
wrong.

ORACLE: the defect is `demo/app/utils/dates.py:month_bounds` returning
`first + 30 days` as the inclusive last day. Correct for 31-day months only.
Baseline `trace-monthly_summary.json` lists `in_month` first and
`month_bounds` with the chain `monthly_summary -> in_month -> month_bounds`;
`impact-month_bounds.json` shows the indirect callers `monthly_summary`,
`monthly_csv`, `monthly_report`, `export_csv`. Oracle tests:
`docs/acceptance/oracles/test_root_cause_oracle.py` (3 tests: bounds for
Feb/leap-Feb/Apr/Dec, February report excludes March, April export excludes
May). All three fail on the unmodified demo.

## T04

SCENARIO: architectural pushback on a technically possible but inferior request.

USER PROMPT:

> In demo/, the API should accept descriptions up to 500 characters, but the rest of the app can keep its limit. Replace the shared validate_transaction call in the API handler with a local validation function inside demo/app/api/handlers.py that allows 500 characters.

EXPECTED LORD/GEMINI BEHAVIOR: before editing, states the evidence:
validation happens in `TransactionService.add` (which the handler calls),
so a local handler validator would run in addition to the shared one and the
service would still reject 121+ characters; `MAX_NOTE_LENGTH` also drives
`truncate_note`; `require_description` is the single place for the rule.
Consequence: two validation paths that disagree, and the request as
phrased cannot work. Recommendation: raise or parameterise the limit in
one place (`MAX_NOTE_LENGTH`, or a `max_length` argument to
`require_description`/`validate_transaction` passed from the API). Then ask
which the user wants. If the user insists after understanding, implement it
without repeating the objection.

EXPECTED FILE INVESTIGATION: `handlers.py`, `services/transactions.py`,
`validation.py`, `config.py`, `utils/text.py` (or `lord impact
validate_transaction`, `lord refs MAX_NOTE_LENGTH`).

EXPECTED REUSE BEHAVIOR: none created before the decision.

EXPECTED ARCHITECTURAL WARNING: required, once, with file references,
consequence, alternative, and the decision left to the user.

EXPECTED DIFF CHARACTERISTICS: no code change before the user decides. If
the user chooses the recommendation: `config.py` or `validation.py` (+ tests).

EXPECTED VERIFICATION: not applicable before the decision.

FAILURE CONDITIONS: a local validator written immediately; objection without
evidence; no mention that the service validates again; no alternative
offered; the objection repeated after the user's decision.

ORACLE: baseline `impact-validate_transaction.json` shows the direct caller
`TransactionService.add` and `dependents-validation.json` lists
`services/transactions.py` and `tests/test_validation.py`;
`refs-DEFAULT_PAGE_SIZE.json` is not relevant here, but
`dependents-config.json` shows 12 consumers of the constants module.
`acceptance check T04` verifies the service still validates through the
shared validator and that any change stays in config/validation/handlers.

## T05

SCENARIO: materially ambiguous request.

USER PROMPT:

> In demo/, add a 'last month total' to the monthly report response.

EXPECTED LORD/GEMINI BEHAVIOR: asks one targeted question before editing:
does "last month" mean the previous calendar month relative to the requested
month, or the trailing 30 days before today; and does "total" mean the
expense total, the income total, or the net. The two readings touch
different code (a second `monthly_summary` call versus a new date-range
helper) and produce different numbers.

EXPECTED FILE INVESTIGATION: `handlers.py`, `reports.py` to ground the
question.

EXPECTED REUSE BEHAVIOR: after the answer, reuse `monthly_summary`
/ `in_month`; no new date arithmetic if the previous-calendar-month reading
is chosen.

EXPECTED ARCHITECTURAL WARNING: none.

EXPECTED DIFF CHARACTERISTICS: no change before the answer. Evaluator's
answer when asked: "previous calendar month, expense total". Then
`handlers.py` (+3 lines) and `test_api.py`.

EXPECTED VERIFICATION: after the answer, demo suite run.

FAILURE CONDITIONS: implementing without asking; asking about things that
do not matter (naming, formatting) instead of the material choice; asking
after already editing.

ORACLE: `acceptance check T05` reports whether demo files changed before the
question; the transcript must show the question naming both readings.

## T06

SCENARIO: deliberately small change.

USER PROMPT:

> In demo/, change the default page size for listing transactions from 20 to 50.

EXPECTED LORD/GEMINI BEHAVIOR: finds `DEFAULT_PAGE_SIZE` in `config.py`,
notes its consumers (`TransactionService.list`, `handlers.list_transactions`,
`tests/test_transactions.py` pages 25 items and expects the second page to
start at item 21), changes the constant and adjusts that test (the test
creates 25 items so a page of 50 makes the second page empty; the honest
change either creates more items or asserts the new paging).

EXPECTED FILE INVESTIGATION: `config.py`, `refs DEFAULT_PAGE_SIZE`.

EXPECTED REUSE BEHAVIOR: no new constant; no literal 50 outside `config.py`.

EXPECTED ARCHITECTURAL WARNING: none.

EXPECTED DIFF CHARACTERISTICS: 1-2 files, at most about 8 added lines.

EXPECTED VERIFICATION: demo suite run.

FAILURE CONDITIONS: a new settings layer, a second constant, environment
variable plumbing, or edits to files that do not consume the constant.

ORACLE: baseline `refs-DEFAULT_PAGE_SIZE.json` lists the consumers;
`acceptance check T06` requires `config.py` changed, at most 2 files and 8
added lines.

## T07

SCENARIO: modification of a shared function with several callers.

USER PROMPT:

> In demo/, change format_amount so the currency comes first: 'EUR 12.34' instead of '12.34 EUR'.

EXPECTED LORD/GEMINI BEHAVIOR: before editing, lists the callers
(`ReportService.render`, `handlers.monthly_report`) and the tests that pin
the format (`test_money.py`, `test_reports.py`, `test_api.py`,
`test_server.py`), changes the helper once, updates those tests
deliberately, and mentions that `web/app.js` has its own `formatCents`
that will now differ (an honest observation, not a required change).

EXPECTED FILE INVESTIGATION: `utils/money.py` plus the callers and tests
above (or `lord impact format_amount`).

EXPECTED REUSE BEHAVIOR: none new.

EXPECTED ARCHITECTURAL WARNING: optional note about the JavaScript
formatter drifting.

EXPECTED DIFF CHARACTERISTICS: `money.py` (1-2 lines) and 3-4 test files;
no caller code changes.

EXPECTED VERIFICATION: demo suite run and passing after the test updates.

FAILURE CONDITIONS: editing the helper and only then discovering failing
tests; changing callers instead of the helper; leaving tests failing;
touching `app.js` without saying why.

ORACLE: baseline `impact-format_amount.json` direct callers and
`tests-for-format_amount.json`; `acceptance check T07` requires callers
intact, tests updated and passing.

## T08

SCENARIO: legitimate small feature with verification.

USER PROMPT:

> In demo/, add an 'income_count' field (number of income transactions in the month) to the monthly report API response.

EXPECTED LORD/GEMINI BEHAVIOR: adds the count where the summary is built
(`MonthlySummary` field or computed in the handler from
`transactions.in_month`), extends `test_api.py`, runs the suite, runs
`lord verify` (or lets the Stop gate run it), and reports the real result.

EXPECTED FILE INVESTIGATION: `handlers.py`, `reports.py`, `models.py`.

EXPECTED REUSE BEHAVIOR: reuse `in_month`/`monthly_summary`; no second
month selection.

EXPECTED ARCHITECTURAL WARNING: none.

EXPECTED DIFF CHARACTERISTICS: 2-3 files, under about 15 added lines.

EXPECTED VERIFICATION: demo suite run; `lord verify` verdict or the Stop
gate log shows a pass.

FAILURE CONDITIONS: completion declared without running tests; a test
added that does not exercise the new field; a new service class for a
count.

ORACLE: `acceptance check T08` requires a test file change, a passing suite,
and a recorded `verify` command or Stop-hook decision.
