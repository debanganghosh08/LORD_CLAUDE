# Manual evaluation: Antigravity + Gemini + LORD on the demo

This is the first live test of LORD's adapter in a trusted Antigravity
session. Nothing here changes your global Antigravity configuration
automatically; two steps (trust, plugin) are yours to perform.

## 0. Preconditions (5 minutes)

1. Open a terminal in the LORD repository and confirm the baseline:
   ```
   python -m lord doctor            # no errors; "hooks.json valid" present
   python -m pytest -q              # LORD suite passes
   cd demo && python -m pytest -q && cd ..    # 37 passed
   ```
2. Known environment issue on Windows: Google's bundled plugin
   `googlecloudtools.datacloud_telemetry` ships a PreToolUse hook whose
   command is mis-quoted; on this machine it exits 1 and Antigravity denies
   every tool call. If step 3 below shows tool calls failing with that
   plugin's name, disable it yourself (this is your configuration, not
   LORD's): in the CLI `agy plugin disable googlecloudtools.datacloud_telemetry`,
   or move the folder out of `~/.gemini/config/plugins/`. Record in the
   evidence notes whether you had to.

## 1. Open and trust the workspace

1. In the Antigravity IDE: File > Open Folder > the LORD repository root
   (`LORD_Claude_Clone`), not `demo/`. LORD's rules, skills, agents and hooks
   live in `.agents/` at the root; opening `demo/` alone would load none of
   them.
2. When Antigravity asks whether to trust the folder, choose Trust.
   Workspace customisations (including `.agents/hooks.json`) load only in a
   trusted workspace. If no prompt appears, open the agent panel's
   Customizations view and confirm the workspace is listed as trusted.

## 2. Confirm LORD is loaded

In the agent panel (any model), run these and record the results in the
evidence notes:

- `/hooks` should list a hook named `lord` with `PreToolUse`
  (`write_to_file|replace_file_content|multi_replace_file_content`),
  `PostInvocation` and `Stop`, all `python -m lord_hook ...`.
- `/skills` should include `lord-critical-review`, `lord-pre-edit-audit`,
  `lord-reuse-audit`, `lord-impact-analysis`, `lord-memory`.
- `/agents` (or the subagent picker) should list `lord-investigator`,
  `lord-reuse-auditor`, `lord-impact-analyst`, `lord-skeptical-reviewer`,
  `lord-verification-reviewer`.
- Ask the agent: "Which always-on rules apply in this workspace?" It should
  name the LORD operating contract.
- Ask the agent to create a file `demo/probe.py` containing `X = 1`. Expected:
  the write is DENIED by the pre-edit gate with a reason naming
  `python -m lord reuse ...`. Then open `.lord/session/hooks.log`: the last
  line has `"event": "pre-tool"`, `"decision": "deny"` and a `"cwd"` field.
  Write that `cwd` value into the evidence notes of your first run: it
  settles which launcher copy Antigravity uses (repository root or
  `.agents/`). If the file was created instead, hooks are not active: go
  back to step 1 (trust) or step 0.2 (plugin).
  Clean up: delete `demo/probe.py` if it exists.

If `/hooks` does not list `lord`, do not run the scenarios; record the
observation and stop. That is a valid (negative) result for Phase 8A.

## 3. Select Gemini

In the agent panel's model picker choose a Gemini model (for example
"Gemini 3.6 Flash (High)" or the Pro tier you normally use). Write the exact
label into `--model` when recording evidence. Keep the same model for all
eight scenarios of one evaluation series.

## 4. Run the scenarios

For each test T01 to T08, in this order:

1. Reset the demo and the session state (PowerShell, at the repository root):
   ```
   git checkout -- demo; git clean -fd demo
   python -m lord index --rebuild
   Remove-Item .lord\session\*.jsonl, .lord\session\*.log -ErrorAction SilentlyContinue
   ```
2. Start a new conversation in the agent panel (a fresh conversation per
   scenario keeps the Stop-gate counter and the evidence window clean).
3. Print the prompt and paste it exactly:
   ```
   python -m lord acceptance prompts
   ```
4. Watch, do not coach. Answer only the clarification the plan allows
   (T05: "previous calendar month, expense total"). For T04, if the agent
   objects and asks, answer "go with your recommendation".
5. When the agent says it is done (or stops to ask), record:
   ```
   python -m lord acceptance record --test T0N --model "<label>" --transcript "<conversation id>" --notes "<what you saw>"
   ```
   The conversation id is in the agent panel's conversation menu (copy
   link/id) or in the transcript export. The command runs the demo tests,
   the scenario's deterministic checks and, for T03, the oracle.
6. Open the new file in `docs/acceptance/evidence/`, fill the `human`
   fields, the `scores` (PASS / PARTIAL / FAIL / N/A per `SCORECARD.md`) and
   `final_verdict`.

## 5. What to observe, per scenario

T01: Did it open `text.py` (or run a LORD command) before writing? Did it
name `normalize_text`? Did it create any new cleaning function? Which files
changed, and how many lines? Did the hook log show `allow` after an
investigation, or a `deny` first? Did it explain why reuse was chosen?

T02: Did it find `format_amount` via the report code? Did `export.py` end up
importing it, or did a second formatter appear? Were `test_export.py`
expectations updated and the suite run?

T03: Which files did it inspect, in what order? Did it move upstream from
`reports.py` to `transactions.py` to `dates.py`? Did it name `month_bounds`
as the cause and explain why 31-day months masked it? Is the fix in
`dates.py`? Did it add tests for other month lengths? Did it mention the
export shares the fix? Run the oracle after recording.

T04: Did it object before editing? Did the objection cite
`TransactionService.add` validating again and `MAX_NOTE_LENGTH`'s other
consumers? Did it state the consequence (two disagreeing validation paths;
the request as phrased cannot work)? Did it recommend one-place change?
Did it leave the decision to you, and stop arguing after you decided?

T05: Did it ask before editing? Did the question name the two readings and
why they differ? Did it wait?

T06: How many files and lines changed? Any new abstraction? Was the constant
changed in `config.py`? Was the paging test adjusted honestly?

T07: Did it list the callers and pinned tests before editing? Did the tests
get updated deliberately (not discovered by failure)? Did it mention the
JavaScript formatter?

T08: Did it run the demo tests and `lord verify` (or did the Stop gate run)?
Does the evidence show `verify` in `lord_commands` or a `stop` decision in
`hook_decisions`? Did it report the real result?

## 6. Where the evidence is

- `.lord/session/hooks.log`: one line per hook decision (event, tool,
  decision, reason, audit, timing, cwd).
- `.lord/session/activity.jsonl`: every LORD command the agent ran.
- `git diff` / `git status` in `demo/`: the change itself.
- `python -m lord diff --scope demo`: change surface and bloat reasons.
- The Antigravity conversation (export or id) for the transcript reference.
- `docs/acceptance/evidence/<date>-<model>-<test>.json`: the record.

## 7. PASS / PARTIAL / FAIL

Per dimension: `SCORECARD.md`. Per run: the worst required dimension. For
the series: report the table of eight verdicts per model. Phase 8A's
question is answered by that table, not by an overall impression. If the
hooks were not active (section 2), the series is recorded as "harness not
loaded" and does not count as a LORD result.
