---
name: lord-pre-edit-audit
description: Runs the LORD pre-edit audit before any file is created, edited or deleted. Establishes definitions, references, reuse candidates, blast radius and the smallest valid change with evidence before implementation. Use for every non-trivial change request.
---
# LORD Pre-Edit Audit

The executable form of the LORD operating contract. Run it in order for any
request that will change a file. Compress steps 1-6 into one short pass only for
trivial, single-line, unambiguous edits; never skip step 2 for anything that
touches a symbol used elsewhere.

All commands run from the workspace root. Add `--json` for machine-readable
output. Every result labels its confidence: `confirmed` (parsed source),
`inferred` (heuristic or text match), `unknown` (analysis unavailable).

## 0. Environment (once per session)

```
python -m lord doctor
python -m lord inventory
```

`doctor` confirms the workspace root, that the Git root matches it, and which
tools exist. `inventory` gives the repository shape: kinds, languages, project
roots, excluded directories. Fix or report any error before editing.

## 1. Restate the task and open the task frame
One sentence: the outcome actually wanted, not the literal words. Then:

```
python -m lord task start "<the request in one line>" --intent "<outcome wanted>"
python -m lord task ask "<question>"                    # a material ambiguity; consequential edits wait for `task resolve`
python -m lord task assume "<assumption>" --material     # a sensible default you are proceeding on; surfaced until `task confirm`
python -m lord task show
```

Material means the interpretation changes files, signatures, data shapes,
scope, compatibility, architecture, or a window, threshold or policy the
request names but the code does not define. Ask once, precisely, with the
options. Do not ask about trivial, low-risk work.

## 2. Search, do not assume
Start with one call that synthesises unfinished work, durable memory,
definition, callers, dependents, tests, configuration, consequences and the
reuse decision for the intent:

```
python -m lord context <symbol|file> --intent "<goal>" [--name <ProposedName>]
```

(`brief` gives the same synthesis without memory and handoff.) Both count as
investigation evidence for the pre-edit gate: the target and every file the
output surfaced (callers, dependents, tests) become editable; other files
still need their own `refs`, `impact` or `brief`.

Then go deeper on every symbol you expect to touch:

```
python -m lord def <name>          # where it is defined (confirmed for Python, inferred for JS/TS)
python -m lord refs <name>         # every use: confirmed code references vs text matches; callers in meta
python -m lord symbols <file>      # what a file defines
python -m lord deps <file>         # what it imports (workspace files resolved)
python -m lord dependents <file>   # who imports it
python -m lord tests-for <name|file>
```

For the behaviour being requested, search by meaning before writing anything:

```
python -m lord related "<describe the behaviour, e.g. validate email address>"
```

Open every file the results point at. The index says where to look; the source
says what is implemented. If a result says `unknown` or `analysis unavailable`,
fall back to `rg -n "<pattern>"` or an editor search and say so; never treat an
unanalysed language as "no references".

Record the trail briefly: searched X, found Y at path:line.

## 3. Blast radius
From `refs`, `dependents` and `tests-for`, list every file that could be
affected, including indirect consumers: shared types, configuration, tests,
callers of callers.

## 4. Critical review
Compare the request with what you found. Raise now, before planning, if the
request: already exists (`related` or `def` found it); contradicts an
established pattern; breaks a consumer (`refs`/`dependents`); targets a symptom;
rests on a misreading. Use EVIDENCE -> CONSEQUENCE -> OPTIONS ->
RECOMMENDATION -> USER DECISION -> IMPLEMENT. One objection, stated once. A
bypass (a flag that switches an existing check off, a copied variant with a
rule removed) is presented as a bypass, never chosen silently.

## 5. Smallest valid change
Choose in order: reuse -> extend -> refactor into existing architecture -> new.
Before creating any symbol or file, run the reuse check and follow its decision
(see the `lord-reuse-audit` skill):

```
python -m lord reuse "<behaviour in words>" --name <ProposedName>
```

Justify every new file, symbol and dependency by the absence of an existing one
(cite the `reuse` decision and the terms it searched).

## 6. Plan
3-6 lines: what you read, what changes file by file, what could break, what you
flagged. Ask only if the interpretations differ materially or the risk is real.

## 7. Implement
Keep to the plan. If the diff must grow, stop and say why before continuing.

## 8. Verify and self-check
Run the detected verification steps through LORD so the result is
LORD-determined, then measure the change surface:

```
python -m lord verify --run --scope <path or term the task was about>
python -m lord diff --scope <path or term the task was about>
```

Paste the `Verification:` block verbatim into the report. State "files: N,
+A/-R lines, new files: K, bloat: LEVEL" and resolve or justify every bloat
reason (new single-symbol file, name collision, function resembling an
existing one, modified copy, invariant bypass, shared call removed,
additive-heavy diff, formatting churn, dependency change, unrelated files).
Report in the order Changed / Verification / Diff / Remaining: what was
reused, what was new and why, what is verified and what is not, what is
unresolved (unconfirmed assumptions, open questions).
