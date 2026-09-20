# LORD Roadmap

Each phase ends with tests, a report in `docs/reports/`, one coherent commit,
and a push. A phase is never marked complete if it is not.

| Phase | Name | Delivers |
|---|---|---|
| 1 | Foundation | boundary, Git/GitHub setup, `.gitignore`, core package, `doctor`, contract rule, pre-edit-audit skill, investigator agent, docs, tests |
| 2 | Repository forensics | inventory with configurable exclusions, symbol model, extractors (Python AST confirmed; JS/TS heuristic), local index in `.lord/`, `def` / `refs` / `related` / `deps` commands, fixtures |
| 3 | Reuse-first / anti-bloat | reuse discovery by name, behaviour and structure; duplicate candidates with evidence; change-surface measurement (files, lines, new files, new symbols, unrelated changes); bloat signal, not a size limit |
| 4 | Impact / root cause | relationship graph over the index; impact traversal (callers, callees, dependents, tests, config); root-cause chain report with explicit confidence |
| 5 | Senior-engineer behaviour | specialist agents (reuse auditor, impact analyst, skeptical reviewer, verification reviewer); critical-review protocol; skills that bind the tooling to the workflow |
| 6 | Enforcement | `.agents/hooks.json`: pre-edit gate (deny/ask/allow from session evidence), completion gate on failed verification (bounded), change-surface advisory; fail-safe launcher; hook test suite; live Antigravity findings |
| 7 | Durable memory | structured `docs/state/`: decisions, discoveries, unresolved issues, conventions; session onboarding summary; compaction-friendly artifacts |
| 8 | Distribution | Antigravity plugin (`plugin.json`), global installation/synchronisation, versioning, per-project bootstrap |
| 9 | Benchmarking | repeatable task suite comparing models with and without LORD on bloat, reuse, root-cause accuracy and pushback quality |

Later direction (conceptual, not committed): forensics, context and critic
layers feeding a swappable model backend, followed by implementation,
verification and state.
