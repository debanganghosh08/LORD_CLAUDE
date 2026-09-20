# Phase 7 Report: Durable Engineering Memory

Date: 2026-09-20

## Objective

Give LORD persistent, versioned, high-signal engineering memory across
sessions, with an explicit trust model, a way to change knowledge without
losing history, a compact handoff for unfinished work, and a context
assembly interface, without building a transcript database, embeddings, a
service, or a second source of truth.

## What was built

```
lord/memory.py                     Item schema and validation; Store (load/save/add/update/supersede/conflicts/check/query); handoff read/write/clear/report
lord/context.py                    assemble(): handoff + relevant memory + brief + matching skills + always-on rules, capped per section
lord/cli.py                        `memory` (query|add|supersede|update|check|list), `handoff` (show|write|clear), `context <target>`
.agents/skills/lord-memory/SKILL.md   recall, write policy, changing knowledge, handoff
.agents/rules/lord-operating-contract.md   entry point is now `lord context`; record durable discoveries; leave a handoff
.agents/skills/lord-critical-review/SKILL.md  steps 2 and 13 bound to context/memory/handoff
docs/state/memory.jsonl            LORD's own memory: 13 items seeded from the phase reports (dogfooding)
docs/state/handoff.json            LORD's own handoff at the end of this phase
tests/test_memory.py               19 tests
docs/ARCHITECTURE.md section 8, README, ROADMAP updated
```

## Final folder structure relevant to the phase

```
docs/state/memory.jsonl     versioned; one item per line, sorted by id
docs/state/handoff.json     versioned; one compact document, cleared when work completes
docs/decisions/*.md         versioned; long-form rationale that memory items point at (not duplicated)
.lord/session/              ignored; transient evidence, counters, hook logs (Phase 6), never memory
```

## High-level architecture and what the code does

**Schema.** An item is `{id, category, statement, status, created, updated,
evidence[], paths[], symbols[], tags[], key, supersedes, superseded_by,
expires, context}`. Seven categories: `decision`, `fact`, `discovery`,
`trap`, `convention`, `unresolved`, `verification`. The handoff category
from the brief was not added: unfinished work is one document, not a stream
of items. Statements are one line and at most 300 characters; rationale
goes to `docs/decisions/`.

**Trust.** Statuses `confirmed` and `evidenced` require evidence (rejected
otherwise); `inferred` is allowed but retrieval labels it and `check` flags
inferred facts and conventions; `temporary` requires an expiry date and is
hidden after it; `unresolved` maps to confidence `unknown`; `superseded` and
`deprecated` are terminal and hidden by default. Invalid lines are reported
by `check` and never loaded, so a malformed or unsupported claim cannot
pose as current truth.

**Change without loss.** `supersede` creates the successor (inheriting key,
paths, symbols and tags unless overridden) and marks the predecessor
`superseded` with `superseded_by`; both stay in the file. `update` changes
status or adds evidence on a current item only. An optional `key` names the
subject; two current items with one key are a `conflict` finding until one
supersedes the other.

**Retrieval.** `Store.query` is deterministic: exact symbol match scores 10,
path equality 6, path containment 4 (a directory-level item applies to files
beneath it), tag 4, category 2, each shared statement term 1 (using the
Phase 2 tokenizer), ties broken by most recent update then id. Filters by
category, status, tag, path, symbol and text; `--all` includes hidden items.
Findings explain why they matched. Semantic retrieval can later sit behind
the same method.

**Handoff.** `write_handoff` merges fields (lists append unique entries,
strings replace) or replaces, stamps the date, branch and commit, and
`--from-verify` attaches the current verdict and outstanding items.
`handoff show` renders it; `handoff clear` removes it when work is done.

**Context.** `assemble` composes, with caps: the handoff (1), relevant memory
(6, by symbol or path plus intent terms; for a symbol without direct hits,
the files that define it), the Phase 5 brief (18), skills whose frontmatter
descriptions share terms with the intent (3), and the always-on rules. Each
section names the command for more. It is the interface for later context
engineering, not an engine.

## Why it was designed this way

- JSON lines in `docs/state/` because the requirements are durability,
  traceability, small size, versionability and human inspection: one line
  per fact makes Git history the audit log and keeps merges local.
- No embeddings, database or service: the store is 5 KB for LORD itself and
  retrieval by symbol, path, tag and terms answers the questions the brief
  lists. Evidence for semantic search does not exist yet.
- No automatic writing. Turning heuristic findings into permanent facts is
  exactly the failure the trust model prevents; the write policy is a
  judgement the model or user makes, with the schema enforcing evidence.
- History is kept by design; `check` makes staleness and conflict visible
  instead of deleting.
- Decision records were not migrated into memory; memory items point at
  them, avoiding a duplicate source of truth.

## What was reused

`tokenize` from the query layer, `brief` and `verify` from the review layer,
the `Report`/`Finding` model with its confidence vocabulary, the
frontmatter conventions of the adapter, Git for handoff provenance. No new
dependencies.

## What was new

`memory.py`, `context.py`, three commands, one skill, the seeded state files
and the tests.

## What was deliberately not built

- No vector database, embeddings or semantic retrieval.
- No automatic capture of session events into memory.
- No PreInvocation injection of memory into every model call (the
  `context` command is the entry point; injection can be added in Phase 8
  once hooks are exercised live).
- No migration of ADRs into memory items; no per-item Markdown files.

## Tests

`tests/test_memory.py` (19) plus earlier suites: **170 passed** (about 2
minutes). Behaviours covered:

- every schema rule (id format, category, status, evidence requirement for
  confirmed/evidenced, expiry for temporary, superseded_by, length, single
  line, dates, evidence type); invalid lines reported and not loaded;
  bad writes rejected; saved file sorted, one line per item, LF;
- supersession keeps history, hides the predecessor by default, shows it
  with `--all`, inherits the subject, refuses a second supersession and
  edits to superseded items; conflicts on one key reported by `check`;
- temporary items expire on the date and cannot pose as current; status to
  confidence mapping; weak facts and open items flagged; `update` resolves
  with evidence and rejects `confirmed` without evidence;
- retrieval ranking symbol > path > text, directory containment, filters by
  category/tag/status, recency tie-break, identical output across reloads,
  no-criteria listing newest first, matched-term explanations;
- durable vs runtime: memory under `docs/state/` and tracked, session state
  under `.lord/` and ignored;
- handoff merge, replace, render (remaining as a warning, verification
  verdict), clear, compact LF JSON;
- context: section caps, handoff first, memory before the brief, file
  targets use path memory, skills matched by intent, rules reflect the
  analysed workspace;
- CLI: add, rejected add, query, supersede, check, list, handoff write with
  `--from-verify`, show, context, clear.

## Dogfooding on LORD

Seeded `docs/state/memory.jsonl` with 13 items drawn from the phase reports:
two decisions (ADR pointers), two conventions (confidence reporting; index
version bump on extractor change), two traps (CRLF on Windows; failing
PreToolUse hooks deny), three facts (trust requirement, rg as a shell
function, write-tool argument names), one verification item, two unresolved
items (hooks not yet live-validated; the broken telemetry plugin), one
discovery (subprocess coverage blind spot). `memory check`: 13 valid, no
conflicts, 2 open. `memory query --path lord/hooks.py` returns the hook
trap first. `context lord/hooks.py --intent "make the stop gate respect a
budget"`: 18 findings (5 memory, 11 brief, 1 rules), the hook trap at the
top. `handoff write --from-verify` recorded this phase's state at commit
`26b779a`. Store size: 5.3 KB; handoff: 0.6 KB.

## Failures / limitations

- Retrieval is lexical; synonyms are not bridged beyond the tokenizer's
  prefix stemming.
- Nothing prevents a model from recording low-value items; the policy is in
  the skill, the schema only enforces structure and evidence.
- `key` conflicts are only detected when items carry a key.
- The Phase 6 enforcement section was found missing from
  `docs/ARCHITECTURE.md` during this phase (an edit anchor had drifted) and
  is restored in this commit.

## Git

Commit: `4e20959` "Phase 7: durable engineering memory, handoff and context
assembly" on `main`. Push: succeeded (`26b779a..4e20959 main -> main`).

## Next-phase readiness

Phase 8 (distribution) can package `.agents/` plus `lord/` and the launcher
as a plugin; memory and handoff are per-repository files with no
machine-specific content; `context` gives a single entry point to bind into
PreInvocation once hooks are exercised in a trusted workspace.
