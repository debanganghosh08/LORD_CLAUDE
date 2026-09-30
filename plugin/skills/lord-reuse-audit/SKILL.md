---
name: lord-reuse-audit
description: Reuse-first and anti-bloat audit. Use before creating any function, class, constant, type, helper or file to check whether it already exists or can be extended, and after implementing to measure the change surface and its bloat signal. Enforces reuse -> extend -> refactor -> create.
---
# LORD Reuse Audit

Two commands, two moments. Both run from the workspace root; add `--json` for
machine-readable output.

## Before creating anything

```
python -m lord reuse "<the behaviour in words>" --name <ProposedName> [--name ...]
```

The report ends with a DECISION:

| Decision | Meaning | What you do |
|---|---|---|
| REUSE | the proposed name already exists | import it; do not create a second one |
| EXTEND | strong candidates cover most of the behaviour | open them; add a parameter, branch or case rather than a parallel implementation |
| REFACTOR OR CREATE | related code exists, no strong match | fit the new code into the existing module and pattern; creation may be justified |
| CREATE | nothing related was found | state in the plan which terms were searched and came up empty |

The search is lexical (names, docstrings, file names, a small synonym table).
Absence of a match is not proof of absence: when the decision is CREATE for
something that feels common (validation, formatting, config access, HTTP
helpers), run `python -m lord related` with different words before believing it.

To see duplication that already exists in the area you are touching:

```
python -m lord duplicates
```

It lists same-named symbols across files, constants sharing a value, functions
with near-identical or structurally identical bodies, and thin wrappers. Do not
turn the task into a cleanup; consolidate only what the task touches, and
report the rest.

## After implementing, before reporting

```
python -m lord diff                       # working tree vs HEAD
python -m lord diff --scope <path|term>   # tell LORD what the task was about
python -m lord diff --base main           # a branch against its base
```

Read the summary line (files, new files, +/- lines, new symbols) and the
BLOAT SIGNAL with its reasons. The signal is never about size alone. Reasons
you must resolve or explicitly justify before presenting the change:

- a new file holding a single small symbol (should it live in an existing module?);
- a new symbol with the same name as an existing definition;
- a new function that resembles an existing one;
- an additive-heavy diff (many lines added, almost none removed);
- formatting-only churn;
- a manifest or dependency change outside the stated scope;
- changed files not connected to the main change.

State in the final report: "files: N, +A/-R lines, new files: K, bloat: LEVEL"
and, when the level is not low, what you did about each reason.
