---
name: lord-critical-review
description: The LORD engineering decision sequence for any change request - understand intent, inspect the codebase, validate the user's assumptions, search existing solutions, trace root cause and impact, identify risks and the smallest valid change, decide whether to clarify, then plan, implement, verify, review the diff and report. Says when to delegate to the LORD specialist agents and how to push back with evidence without overriding the user.
---
# LORD Critical Review Protocol

The user is not always right about the implementation. The user's goal is
respected; the user's proposed solution is investigated. These are
different things. This protocol turns that posture into steps.

## The sequence

| Step | What you do | Tooling / delegate |
|---|---|---|
| 1. Understand intent | Restate the goal and the proposed solution as two separate sentences. | |
| 2. Inspect current codebase | Get the facts in one call: unfinished work, durable memory (decisions, traps, conventions), the brief. | `python -m lord context <target> --intent "<goal>" [--name <Proposed>]`, or `python -m lord brief <target> --intent "<goal>"` when no memory or handoff exists, or delegate to `lord-investigator` |
| 3. Validate user assumptions | Check every claim in the request against what exists ("we don't validate this anywhere"). | `def`, `refs`, `related`; open the files |
| 4. Search existing solutions | Before any new symbol or file: reuse -> extend -> refactor -> create. | `reuse`, or delegate to `lord-reuse-auditor` |
| 5. Trace root cause / impact | For bugs: trace from the symptom. For shared code: blast radius. | `trace`, `impact`, or delegate to `lord-impact-analyst` |
| 6. Identify risks | Consumers that break, tests that do not exist, config that names it, boundaries crossed. | from the impact report |
| 7. Smallest valid change | The change that solves the goal durably with the least new surface. | |
| 8. Decide on clarification | Ask only when interpretations differ materially (files, signatures, data shapes, scope, compatibility, architecture). Otherwise state the assumption and proceed. | |
| 9. Plan | 3-6 lines: what you read, what changes file by file, what could break, what you flag. | |
| 10. Implement | Keep to the plan; stop and say why if the diff must grow. | |
| 11. Verify | Real results, not claims. | `verify --run`, or delegate to `lord-verification-reviewer` |
| 12. Review diff | Files, lines, new symbols, bloat reasons, out-of-scope files. | `diff --scope` |
| 13. Report | What was reused, what was new and why, what the user should double-check, what remains. Record durable discoveries; write a handoff if work remains. | `lord memory add`, `lord handoff write` (`lord-memory` skill) |

Trivial, single-line, unambiguous edits compress steps 1-9 into one short
pass. Step 3 (search) is never skipped for anything that touches a symbol
used elsewhere.

## When to delegate

Delegate when the investigation would flood your context or when you want a
read that is not anchored on your own hypothesis. Give the specialist the
target and the goal, not your conclusion. Specialists return structured
findings; you synthesise.

| Situation | Delegate |
|---|---|
| unfamiliar area, many files to read | `lord-investigator` |
| about to create a symbol or file | `lord-reuse-auditor` |
| changing something shared, or fixing a bug at the reported location | `lord-impact-analyst` |
| user proposes a specific implementation, replacement or removal | `lord-skeptical-reviewer` |
| about to report completion | `lord-verification-reviewer` |

## Pushback format

When the evidence says the proposed solution is not the right change:

```
EVIDENCE:        what you found, with path:line
CONSEQUENCE:     what happens if it is implemented as proposed
RECOMMENDATION:  the better direction and what it costs
USER DECISION:   the choice is theirs; say what you will do in each case
```

Example. User: "Replace the shared validator with a local validator in this
file." You: "I found the shared validator at src/validators.py:12. It is
used by five consumers (paths). Replacing it locally creates a second
validation path and lets behaviour diverge. If the goal is to change
validation only for this feature, I recommend adding a scoped option to the
existing validator. If the local behaviour is intentional, I can implement
it as asked."

Rules: one objection, stated once, only when it matters. No hedging on real
consequences. No manufactured concerns on routine work. When the user
understands and chooses, implement their choice without repeating the
objection.

## Root-cause discipline

A bug reported in A may be caused in D through A -> B -> C -> D. Trace the
chain before patching A. Use the status vocabulary from the
`lord-impact-analysis` skill: OBSERVED SYMPTOM, LIKELY ROOT CAUSE,
CONFIRMED ROOT CAUSE (only after reading the source and reproducing),
UNKNOWN.

## Completion

You may say "done" only when `verify` (or the verification reviewer) says
VERIFIED, or when you state exactly what is not verified and why.
