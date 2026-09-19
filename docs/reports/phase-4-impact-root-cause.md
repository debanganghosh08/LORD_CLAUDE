# Phase 4 Report: Impact Analysis / Root-Cause Engine

Date: 2026-09-20

## Objective

Answer "what happens if we change this?" and "where is the actual cause?"
with a reproducible, inspectable, evidence-backed relationship graph and
traversals over it, while keeping the division of labour: the graph says
where to look, the source says what is implemented, the model says what it
means.

## What was built

```
lord/graph.py                relationship graph derived from the index (8 edge kinds, per-edge confidence)
lord/impact.py               impact report and root-cause trace worksheet
lord/cli.py                  `impact`, `trace`, `graph` commands
lord/symbols.py              Ref gains `receiver` (dotted receiver of attribute uses)
lord/extractors/python_ast.py, js_ts.py   record receivers for calls and attribute references
lord/index.py                INDEX_VERSION 2 (older caches rebuild automatically)
.agents/skills/lord-impact-analysis/SKILL.md   procedure and the status vocabulary
tests/fixtures/sample_repo/  config names symbols; runner/jobs files for receiver resolution
tests/test_impact.py         13 tests
```

## What the code does

**Graph.** `build_graph(index, root)` produces nodes `file:<path>` and
`sym:<path>::<qualname>` with edges `defines`, `imports`, `calls`,
`references`, `extends`, `implements`, `tests` and `configures`. It is
rebuilt from the index on demand (10 ms for LORD's 3,000 edges), so it is
never a second source of truth. `lord graph <target>` dumps a node's edges.

Name resolution is receiver-aware, which is what makes chains trustworthy:
- bare name -> import binding in the file (confirmed), else same-file
  definition (confirmed), else any same-named top-level symbol in another
  code file (inferred, ambiguity kept as several edges);
- `alias.name` where `alias` is a module import (`import pkg.runner as r`,
  `from pkg import runner`) -> that module's symbol (confirmed);
- `self.name` / `cls.name` -> the method on the enclosing class or, walking
  same-file bases, an inherited method (confirmed); otherwise same-file
  methods of that name (inferred);
- `obj.name` with an unknown receiver -> only *methods* named `name`
  (inferred). `subprocess.run()` therefore never links to a module-level
  `run` elsewhere, and `os.getcwd()` links to nothing.
- test files add `tests` edges to what they import and call; config and
  manifest files add `configures` edges when they mention a distinctive
  symbol name or a dotted path that matches the defining file (inferred).

**Impact report.** For a symbol (optionally qualified) or a file: definition
(with ambiguity noted), direct references and callers with confidence,
indirect callers to a depth with the chain, callees, file dependencies,
dependents by import depth, related types (extends/implements in both
directions), tests, configuration, architectural boundary (files, top-level
directories, project roots) and consequence statements: direct sites
reached, indirect inheritance of the change, subtypes, tests to run first or
an explicit "no test references it" warning, configuration to update,
boundary crossing, and callers invisible in unsupported languages. It ends
with reuse candidates near the target and an `overall_confidence`.

**Trace worksheet.** For an observed symptom at a symbol: candidate causes
downstream (what the symptom depends on, nearest first, callables before
types before constants, other files first) with the chain and the weakest
hop confidence; upstream callers that feed it; missing evidence (unresolved
external or dynamic calls, unsupported languages, inferred hops); and a
recommended next investigation. LORD labels only OBSERVED SYMPTOM,
CANDIDATE CAUSE and UNKNOWN. The skill reserves CONFIRMED ROOT CAUSE for
the model after it has read the source and reproduced the behaviour.

## Design decisions

1. **Adjacency lists, not a graph database.** The whole graph for a
   medium repository is a few thousand edges and builds in milliseconds;
   persistence would only add staleness. Reproducibility comes from the
   index, inspectability from `lord graph` and `--json`.
2. **Confidence propagates along chains.** Every hop keeps its own
   confidence and every chain reports its weakest hop, so a confirmed
   caller reached through an inferred hop is presented as inferred.
3. **Receiver-aware resolution was added after dogfooding.** The first
   version linked `subprocess.run` to `lord.cli.run` and produced 40
   "upstream" callers for `query.references`; after the change there are 7,
   all real. The precision cost is that inherited methods across files stay
   inferred.
4. **The model owns the verdict.** The trace never says "root cause"; it
   ranks candidates and states what it could not establish.

## What was reused

The index, `Extraction` records, `related`, `BUILTIN_NAMES`, the
`Report`/`Finding` model and CLI skeleton. No new dependencies.

## What was new

`graph.py`, `impact.py`, three commands, one skill, the `receiver` field,
fixture additions and tests.

## Tests

`tests/test_impact.py` (13) plus earlier suites: **104 passed in ~6s**.
Behaviours covered:
- import and define edges (Python confirmed, JS inferred);
- calls resolved through import bindings, same-file definitions,
  same-file inheritance (`self.create()` in a subclass -> confirmed), JS
  alias bindings (`h` -> `helper`);
- receiver-aware resolution: module alias confirmed, `subprocess.run` not
  linked, unknown receiver only to methods, `os.getcwd()` to nothing;
- extends, tests and configures edges (dotted path and distinctive name);
- excluded and generated definitions absent from the graph;
- target resolution for qualified names, Windows-style paths, unknown;
- impact of a shared function: definition, direct and indirect callers
  with an exact chain, dependents, tests, config, directories, every
  consequence statement, reuse candidate, overall confidence;
- impact of a class: subtype consequence and the untested warning;
- impact of a file: dependents with depth;
- trace: observed symptom, candidate ranking (callables first), depth-2
  constants via references with the exact chain, upstream, missing
  evidence labelled unknown, next investigation with the CONFIRMED caveat;
- CLI JSON contract for `impact`, `trace`, `graph`.

## Manual validation (dogfooding on LORD)

| Command | Result |
|---|---|
| `impact Finding` | 21 direct caller/reference sites, 35 indirect, dependents across the core, 4 test files, directories `lord` and `tests`, overall confidence confirmed |
| `trace references` before receiver-aware resolution | 40 upstream callers including `git_toplevel` via a false `subprocess.run -> cli.run` hop |
| `trace references` after | 7 upstream callers (cli, main, three tests), candidates `Graph.add`, `Index.extraction_for`, ... ; missing evidence lists unresolved external calls and 37 inferred chains |
| graph build on LORD | 3,000 edges, 421 nodes, ~10 ms |

## Git

Commit: Phase 4 commit on `main` (see `git log`). Push result recorded in
the Phase 5 report.

## Known limitations

- Cross-file inheritance and unknown-receiver method calls are inferred;
  dynamic dispatch, decorators that rewrite functions, reflection and
  string-based lookups are invisible.
- JS/TS edges inherit the heuristic extractor's limits.
- `configures` edges are lexical: a config key that happens to equal a
  distinctive symbol name produces an inferred edge.
- Depth-limited traversals can miss long chains; raise `--depth` when the
  boundary finding shows the change stays local.
- No data-flow analysis: a "candidate cause" is a structural dependency,
  not a proven source of the wrong value.

## Next phase readiness

Phase 5 binds all of this to behaviour: specialist agents that run the
commands and return structured findings, plus the critical-review protocol.
No Phase 4 contract needs to change.
