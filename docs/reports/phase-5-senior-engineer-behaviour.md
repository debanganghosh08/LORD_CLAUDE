# Phase 5 Report: Senior-Engineer Behaviour / Critical Review / Specialists

Date: 2026-09-20

## Objective

Convert the deterministic information from Phases 2-4 into behaviour:
narrowly scoped specialist agents that investigate deeply and return
structured findings, a critical-review protocol that turns "the user is not
always right about the implementation" into an evidence-based sequence, and
a verification step that makes "done" mean verified.

## What was built

```
lord/review.py                         `brief` (one-call pre-edit synthesis) and `verify` (completion check)
lord/cli.py                            `brief`, `verify` commands (17 commands in total)
.agents/agents/lord-reuse-auditor.md          reuse ladder decision with evidence
.agents/agents/lord-impact-analyst.md         blast radius and root-cause tracing
.agents/agents/lord-skeptical-reviewer.md     at most one objection, evidence -> consequence -> recommendation -> user decision
.agents/agents/lord-verification-reviewer.md  real results, verdict VERIFIED / NOT VERIFIED
.agents/skills/lord-critical-review/SKILL.md  the 13-step decision sequence, delegation table, pushback format
.agents/rules/lord-operating-contract.md      now names the skills and specialists and the `brief` entry point
.agents/skills/lord-pre-edit-audit/SKILL.md   step 2 starts with `brief`
tests/test_review.py                   15 tests
```

## What the code does

**`lord brief <target> --intent "<goal>" [--name <Proposed>]`** collapses
the pre-edit investigation into one call: definition (with ambiguity),
direct and indirect callers, related types, tests, configuration, boundary
and consequence statements from the impact engine; a reference summary
(confirmed vs text-only files, callers); the reuse decision for the intent;
the current uncommitted workspace state; and a closing reminder that the
brief says where to look, not what the code means. Output is capped per
finding kind so it stays around 30 lines.

**`lord verify [--run] [--scope ...] [--base REF] [--staged]`** is the
deterministic backbone of "verify before completion":
- change surface summary and bloat signal with reasons, plus any
  resemblance, name-collision or unrelated-file findings;
- test files that import each changed code file, and an explicit
  `untested-change` warning for changed files no test imports;
- TODO/FIXME/XXX/HACK markers added by the diff (from `git diff -U0`);
- verification steps detected from manifests: pytest (tests or config
  present), ruff and mypy (configured), npm test/lint/typecheck/build
  (real scripts only; npm's placeholder is ignored), tsc, cargo test,
  go test, each marked available or not with the reason;
- with `--run`: each step executed with a timeout, exit code, duration and
  the last lines of output on failure;
- a verdict: `verified` only when every available step passed and nothing
  is outstanding; otherwise `not verified` with the list of what remains.
  Failing steps make the report an error (exit code 1) so a hook can gate
  on it.

**Specialists.** Five read-only subagents (`view_file`, `grep_search`,
`run_command`; no write tools), each with a genuine responsibility, the
LORD commands it runs, a fixed output format of about 25-40 lines, and the
rules that keep it honest (confidence labels, cite paths and lines, never
edit, never repeat an objection after the user decides).

**Critical-review protocol.** The `lord-critical-review` skill lays out
USER REQUEST -> UNDERSTAND INTENT -> INSPECT -> VALIDATE ASSUMPTIONS ->
SEARCH EXISTING -> TRACE CAUSE / IMPACT -> RISKS -> SMALLEST VALID CHANGE ->
CLARIFY? -> PLAN -> IMPLEMENT -> VERIFY -> REVIEW DIFF -> REPORT, maps each
step to a command or specialist, defines when to delegate (and to give the
specialist the goal, not the conclusion), states the pushback format with
the shared-validator example, and forbids "done" without a verdict.

## Design decisions

1. **Specialists are backed by commands, not prose.** Each role exists
   because a deterministic capability exists for it (reuse, impact/trace,
   brief, verify). No decorative agents; the test suite asserts the exact
   set of five.
2. **Context protection through shape.** Specialists return fixed
   structures with line caps; `brief` caps findings per kind. The primary
   agent synthesises, it does not receive dumps.
3. **The verdict is data.** `verify` exposes `meta.verdict`,
   `meta.outstanding` and `meta.step_results` for the Phase 6 stop hook.
4. **Honest verification.** `verify` never reports a step it did not run;
   unavailable tools are reported as unavailable, and a failing step is
   quoted, not summarised away.
5. **Rules stayed short.** The always-on contract gained four lines naming
   the skills, specialists and entry point; the protocol lives in a skill.

## What was reused

Every earlier phase: `measure`, `git_changes`, `impact_report`,
`resolve_target`, `references`, `reuse_report`, the index, the report
model. No new dependencies.

## What was new

`review.py`, two commands, four agents, one skill, the tests.

## Tests

`tests/test_review.py` (15) plus earlier suites: **119 passed in ~34s**
(the verification tests run real pytest subprocesses). Behaviours covered:
- brief: definition first, impact kinds present, reference summary,
  reuse decision and tests in meta, compact (<= 40 findings); unknown target
  still yields the reuse decision;
- step detection from manifests: pytest, ruff, npm lint, cargo; npm's
  placeholder test script ignored; nothing configured -> no steps;
- verify without `--run`: steps listed, markers detected with the exact
  line, verdict not verified with reasons;
- verify with `--run` on a real temporary Git repository: pytest PASS with
  exit code, tests-to-run and no uncovered files -> `verified` (confirmed);
  then a deliberately broken implementation -> pytest FAIL quoted in the
  evidence, verdict not verified, report has errors;
- untested changed file flagged as inferred;
- adapter structure: exactly the five planned specialists; each has the
  right frontmatter, no write tools, an output format, LORD commands and a
  never-edit rule; the critical-review skill names every step, every
  specialist, the pushback format and the tools;
- CLI JSON contract for `brief` and `verify`.

## Manual validation (dogfooding on LORD)

| Command | Result |
|---|---|
| `brief measure --intent "add a check that flags new files with no tests" --name flag_untested_files` | 32 findings; 8 direct callers (cli.run, review.verify, six tests); tests `tests/test_reuse.py`; reuse decision EXTEND; overall confidence inferred (some callers reached by name) |
| `verify --run --scope review --scope agents` (this phase's tree) | pytest PASS (exit 0, 13.4 s); verdict NOT VERIFIED: bloat signal elevated (additive new-feature phase) and `lord/cli.py` imported by no test file |

The second row is correct and useful: the CLI is exercised through
subprocess calls in the tests, which import-based coverage cannot see, so
the agent must say so in its report rather than claim full coverage.

## Git

Commit: Phase 5 commit on `main` (see `git log`). Push result: see the
final engineering report.

## Known limitations

- Test coverage of a change is import-based; tests that exercise code
  through subprocesses, fixtures or dynamic imports are not credited.
- Step detection covers common Python, Node, Rust and Go setups; other
  ecosystems produce "no automated verification detected".
- The specialists' behaviour depends on the model following their
  instructions; LORD supplies the structure, commands and evidence, not
  the judgement. This is the model-dependent part by design.
- Antigravity's subagent mechanism was implemented from its public
  documentation; the adapter has not yet been exercised in a live session.

## Next phase readiness

Phase 6 (enforcement) has everything it needs as data: `reuse
meta.decision`, `diff meta.bloat_level`, `verify meta.verdict` and exit
codes, all callable through `python -m lord ... --json` from a
`.agents/hooks.json` command handler.
