---
name: lord-pre-edit-audit
description: Runs the LORD pre-edit audit before any file is created, edited or deleted. Establishes definitions, references, reuse candidates, blast radius and the smallest valid change with evidence before implementation. Use for every non-trivial change request.
---
# LORD Pre-Edit Audit

The executable form of the LORD operating contract. Run it in order for any
request that will change a file. Compress steps 1-6 into one short pass only for
trivial, single-line, unambiguous edits; never skip step 2 for anything that
touches a symbol used elsewhere.

## 0. Environment
Run once per session in a new workspace:

```
python -m lord doctor
```

It confirms the workspace root, that the Git root matches it, and which tools
are available. If it reports an error, fix or report it before editing.

## 1. Restate the task
One sentence: the outcome actually wanted, not the literal words.

## 2. Search, do not assume
For every symbol you expect to touch, find with evidence:
- the definition (file and line);
- every reference and caller across the repository;
- existing implementations that already do most of the job, searched by
  behaviour and structure as well as by name.

Tooling, in preference order:
1. `python -m lord` commands (repository intelligence; added in later phases);
2. `rg -n "<pattern>"` across the workspace root (respects .gitignore);
3. opening the files the search points at.

Record the trail briefly: searched X, found Y at path:line.

## 3. Blast radius
List every file that could be affected, including indirect consumers: shared
types, configuration, tests, callers of callers.

## 4. Critical review
Compare the request with what you found. Raise now, before planning, if the
request: already exists; contradicts an established pattern; breaks a consumer;
targets a symptom; rests on a misreading. Use EVIDENCE -> CONSEQUENCE ->
RECOMMENDATION -> USER DECISION. One objection, stated once.

## 5. Smallest valid change
Choose in order: reuse -> extend -> refactor into existing architecture -> new.
Justify every new file, symbol and dependency by the absence of an existing one.

## 6. Plan
3-6 lines: what you read, what changes file by file, what could break, what you
flagged. Ask only if the interpretations differ materially or the risk is real.

## 7. Implement
Keep to the plan. If the diff must grow, stop and say why before continuing.

## 8. Verify and self-check
Run tests, type checks, lint and build. State "files: N, +A/-R lines, new
files: K" and explain anything larger than the task warrants. Report what was
reused, what was new and why, and what is unresolved.
