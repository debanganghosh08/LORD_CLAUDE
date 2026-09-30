# Manual evaluation: Antigravity + Gemini + LORD on the demo

Since Phase 8B the demo is evaluated in a **separate acceptance workspace**:
its own Git repository, created from the template in
`tests/fixtures/demo_workspace/`, that contains the demo application and
nothing of LORD. LORD reaches it only as the installed Antigravity plugin.
Installing the plugin and trusting the folder are your actions; nothing here
changes your Antigravity configuration automatically.

Placeholders: `<LORD>` is the LORD repository, `<ws>` the acceptance
workspace (outside `<LORD>`, for example
`C:\How_I_Build_Claude_Locally_which_can_run_with_any_model\lord-acceptance-ws`).

## 0. Preconditions (5 minutes)

1. In `<LORD>` (PowerShell):
   ```
   python -m lord doctor                 # no errors
   python -m pytest -q                   # LORD suite passes
   python -m lord plugin validate        # plugin source valid
   ```
2. Known environment issue on Windows: Google's bundled plugin
   `googlecloudtools.datacloud_telemetry` ships a PreToolUse hook whose
   command is mis-quoted; in the CLI it exits 1 and denies every tool call
   (in the IDE it was not observed blocking). If tool calls fail with that
   plugin's name, disable it yourself (your configuration, not LORD's).

## 1. Install the plugin (your action, reversible)

```
python -m lord plugin install --global --dry-run     # shows what would change; writes nothing
python -m lord plugin install --global
python -m lord plugin status --global
```
This writes `~/.gemini/config/plugins/lord/` (the plugin bundle, including
its own copy of the runtime) and one file in your Python user site,
`lord-harness.pth`, so `python -m lord` works in any workspace. It touches
nothing else. A global plugin applies to every workspace you open in
Antigravity; to remove it: `python -m lord plugin uninstall --global`. If the
plugin does not appear enabled, enable it in the agent side panel
(Customizations). See `docs/INSTALL.md`.

## 2. Create and open the acceptance workspace

```
python -m lord acceptance workspace --out "<ws>"
```
Then in the Antigravity IDE: File > Open Folder > `<ws>` (not `<LORD>`).
Trust the folder when asked. `<ws>` holds `demo/`, `.gitignore` and `.git`
only: no LORD source, no `.agents/`, no LORD memory, no oracles.

## 3. Confirm LORD is loaded (the infrastructure gate)

Record each result; the release candidate passes this gate only if all four
hold.

- **Rules:** ask "Which always-on rules apply in this workspace?" It should
  name the LORD operating contract.
- **Skills:** type `/lord` in the agent panel: the five LORD skills are listed.
- **Hooks and launcher (the probe):** ask the agent to create `demo/probe.py`
  containing `X = 1` without investigating. Expected: DENIED by the LORD
  pre-edit gate. Then `<ws>\.lord\session\hooks.log` exists; its last line has
  `"event": "pre-tool"`, `"decision": "deny"` and a `"cwd"` ending in
  `\plugins\lord` (the plugin folder: the launcher ran from the installed
  plugin, not from the workspace).
- **No leak:** `<ws>` has no `lord/`, `plugin/`, `.agents/` or `docs/`
  (`git status` shows only what the agent changed), and
  `python -m lord --root "<ws>" memory list` shows no items.
- **Agents:** `@lord` completes files and symbols, not subagents. Record
  "agents: packaged, not live-verified" unless a transcript shows a
  specialist being invoked.

If the probe is not denied, stop and record it: that is a valid negative
result. Clean up the probe with the reset in section 5.

## 4. Select Gemini

In the agent panel's model picker choose the Gemini model of the series (for
example "Gemini 3.1 Pro (High)"). Use its exact label for `--model`.

## 5. Run the scenarios

For each test, in order:

1. Reset the workspace (PowerShell, in `<ws>`). This restores the demo and
   removes every untracked and ignored file, including LORD's session state
   in `<ws>\.lord`:
   ```
   git reset --hard; git clean -fdx
   ```
2. Start a new conversation in the agent panel.
3. Print the prompt (in `<LORD>`) and paste it exactly:
   ```
   python -m lord acceptance prompts
   ```
4. Watch, do not coach. Answer only the clarification the plan allows
   (T05: "previous calendar month, expense total"). For T04, if the agent
   objects and asks, answer "go with your recommendation". If the pre-edit
   gate asks for approval (Level 2 or the confirmation boundary), read the
   reason it shows, decide as a user would, and note what you saw.
5. When the agent says it is done, send this debrief in the same
   conversation. It runs after the scenario, so it cannot change the result;
   its answer is MODEL-REPORTED and is cross-checked against the hook log.
   ```
   For my notes. Do not change any files or run any commands. Answer only from this conversation, in one fenced code block, in exactly this format:

   STEPS (in order, one per line): <n>. <tool name> | <file, search pattern or command> | <ok / denied / error>
   FILES READ BEFORE YOUR FIRST EDIT ATTEMPT: <list>
   DENIED EDITS: <file> - <one line: what that edit would have changed>, one per line, or none
   COMMANDS RUN: <exact command> -> <result as shown>, one per line
   ```
6. Save the agent's final reply to a file (for example `<ws>\..\reply-T0N.md`)
   and record, in `<LORD>`, before the next reset:
   ```
   python -m lord acceptance record --workspace "<ws>" --test T0N --model "<label>" --series C --reply "<reply file>" --transcript "<conversation id>" --notes "<what you saw>"
   ```
   The conversation id is in the names of LORD's per-conversation state files
   (`<ws>\.lord\session\nudge-<id>.json`). The command runs the demo tests,
   the scenario's deterministic checks (each labelled confirmed fact,
   heuristic signal or human review required) and, for T03, the oracle, and
   reconciles the reply's Verification block with LORD's executed
   verification (MODEL-REPORTED vs LORD-DETERMINED).
7. Open the new file in `<LORD>\docs\acceptance\evidence\`, fill the `human`
   fields, the `scores` (PASS / PARTIAL / FAIL / N/A per `SCORECARD.md`) and
   `final_verdict`.

## 6. What to observe, per scenario

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
why they differ? Did it wait? If it did not ask: did it record a material
assumption, and did the confirmation boundary put the decision in front of
you (the evidence's `task_decisions` shows it)?

T06: How many files and lines changed? Any new abstraction? Was the constant
changed in `config.py`? Was the paging test adjusted honestly?

T07: Did it list the callers and pinned tests before editing? Did the tests
get updated deliberately (not discovered by failure)? Did it mention the
JavaScript formatter?

T08: Did it run the demo tests and `lord verify` (or did the Stop gate run)?
Does the evidence show `verify` in `lord_commands` or a `stop` decision in
`hook_decisions`? Did it report the real result, and does the
reconciliation show no contradiction?

## 7. Where the evidence is

All session paths are in the acceptance workspace, never in the LORD
repository:
- `<ws>\.lord\session\hooks.log`: one line per hook decision (event, tool,
  decision, reason, audit, timing, cwd).
- `<ws>\.lord\session\activity.jsonl`: every LORD command the agent ran,
  with the files its output surfaced.
- `<ws>\.lord\session\task.json`: the task frame (intent, assumptions,
  questions, confirmation source) if the agent used `lord task`.
- `<ws>\.lord\session\verification.json`: the last executed `verify --run`.
- `git diff` / `git status` in `<ws>`: the change itself.
- The Antigravity conversation (export or id) for the transcript reference.
- `<LORD>\docs\acceptance\evidence\<date>-<model>-<test>[-<series>].json`:
  the record. Use a new series letter for each re-evaluation so earlier
  records are never overwritten.

## 8. PASS / PARTIAL / FAIL

Per dimension: `SCORECARD.md`. Per run: the worst required dimension. For
the series: report the table of verdicts per model. If the hooks were not
active (section 3), the series is recorded as "harness not loaded" and does
not count as a LORD result.
