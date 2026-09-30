---
name: lord-memory
description: Durable engineering memory and session handoff. Use at the start of a task to recall decisions, traps, conventions and unresolved issues for the area being changed, when a hard-won discovery or decision should outlive the session, and before stopping with unfinished work. Deterministic, versioned, high-signal; never a transcript.
---
# LORD Memory

Repository engineering knowledge lives in `docs/state/memory.jsonl` (one
item per line, versioned) and unfinished work in `docs/state/handoff.json`.
Transient session state stays in `.lord/session/` and is never memory.

## Recall (start of a task)

```
python -m lord context <symbol|file> --intent "<goal>"     # handoff + memory + brief + skills + rules, capped
python -m lord memory query --path <file> [--text "<terms>"] [--category trap]
python -m lord memory query --symbol <Name>
python -m lord memory check                                # conflicts, expired, invalid, open items
python -m lord handoff show                                # what was left unfinished, and what remains
```

Every item shows its status: `confirmed` (evidence verified), `evidenced`
(has evidence, not re-verified), `inferred`, `temporary` (has an expiry),
`unresolved`. Treat `inferred` and `temporary` as hypotheses.

## Write policy

Record an item only if at least one holds: it affects future engineering
decisions; it is a stable convention; it explains an architectural
decision; it is a hard-won discovery; it prevents a repeated mistake; it is
unresolved work needed to continue. Temporary observations stay temporary
(use `--status temporary --expires YYYY-MM-DD`).

```
python -m lord memory add --category trap --statement "<one line, <=300 chars>" \
  --evidence "<file:line | command | commit | doc>" --paths <dir-or-file> --symbols <Name> --tag <tag> [--key <subject>]
```

Categories: `decision`, `fact`, `discovery`, `trap`, `convention`,
`unresolved`, `verification`. `confirmed` and `evidenced` require evidence.
Long rationale belongs in `docs/decisions/` with the memory item pointing at
it; never paste conversation.

## Changing knowledge

Never edit history away. When a fact changes:

```
python -m lord memory supersede M-0007 --statement "<the current fact>" --evidence "<why>"
python -m lord memory update M-0012 --status confirmed --evidence "<verified how>"
```

Give related items a `--key` (for example `auth.middleware`): two current
items with one key are reported as a conflict by `memory check` until one
supersedes the other.

## Handoff (before stopping with work unfinished)

```
python -m lord handoff write --doing "<what>" --done "<step>" --remaining "<step>" \
  --discovered "<fact>" --decided "<decision>" --next "<action>" --from-verify
python -m lord handoff clear     # when the work is complete
```

Keep it compact: what were we doing, what is complete, what remains, what
was discovered, what was decided, what happens next, what verification is
outstanding. Promote durable discoveries to memory items; the handoff is for
resuming, not for remembering.
