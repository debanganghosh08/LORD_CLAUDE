---
name: lord-impact-analysis
description: Impact and root-cause analysis. Use before changing any shared symbol or file to learn what breaks (callers, dependents, subtypes, tests, configuration, architectural boundary), and when debugging to trace from the observed symptom to candidate causes upstream and downstream instead of patching where the error appears.
---
# LORD Impact Analysis

Run from the workspace root. Add `--json` for machine-readable output.
Every hop carries a confidence: `confirmed` (import binding or same-file
definition), `inferred` (matched by name across files), `unknown`.

## "What happens if we change this?"

```
python -m lord impact <symbol | Class.method | path/to/file> [--depth 2]
```

The report follows TARGET -> DEFINITION -> DIRECT REFERENCES -> INDIRECT
CALLERS -> CALLEES -> DEPENDENCIES -> DEPENDENTS -> RELATED TYPES -> TESTS
-> CONFIGURATION -> BOUNDARY -> CONSEQUENCES -> REUSE CANDIDATES.

Before editing, you must be able to answer from it:
- which files and symbols call or reference the target, and with what confidence;
- which subtypes inherit its behaviour;
- which tests exercise it (if none, say so and add one before changing behaviour);
- which configuration names it;
- how many top-level directories the change crosses.

Open every direct caller the report lists. The graph says where to look; the
source says what is implemented. If `overall_confidence` is `inferred`, say
so in your plan.

## "Where is the actual cause?"

A bug reported at A is often caused at D through A -> B -> C -> D. Do not
patch A until you have traced the chain.

```
python -m lord trace <symbol> --observed "<what was observed>" [--depth 3]
```

The report gives:
- OBSERVED SYMPTOM: where the behaviour was seen;
- CANDIDATE CAUSES: downstream symbols the symptom depends on, nearest first,
  with the chain and its confidence;
- UPSTREAM: callers that feed the symptom (the input may already be wrong);
- MISSING EVIDENCE: unresolved calls, unsupported languages, inferred hops;
- NEXT INVESTIGATION: what to open first.

Status vocabulary you must use in your answer:

| Status | Meaning |
|---|---|
| OBSERVED SYMPTOM | where the wrong behaviour shows up |
| LIKELY ROOT CAUSE | a candidate supported by evidence you have read |
| CONFIRMED ROOT CAUSE | you read the source, reproduced the behaviour, and the fix location explains every observation |
| UNKNOWN | the chain could not be established (say why) |

LORD never emits CONFIRMED; only you can, after reading the source.

## Your root-cause finding must contain

```
OBSERVATION: <symptom, input, expected vs actual>
EVIDENCE: <file:line facts you verified>
UPSTREAM CHAIN: A <- B <- C
DOWNSTREAM CHAIN: A -> B -> C -> D
STATUS: likely | confirmed | unknown
CONFIDENCE: confirmed | inferred | unknown  (weakest hop)
MISSING EVIDENCE: <what you could not establish>
RECOMMENDED FIX LOCATION: <file:line> and why the symptom location is wrong
NEXT INVESTIGATION: <if not confirmed>
```

## Inspecting the graph

```
python -m lord graph <symbol | file>
```

lists a node's incoming and outgoing edges (defines, imports, calls,
references, extends, implements, tests, configures) with confidence and
line. Use it when a chain looks surprising.
