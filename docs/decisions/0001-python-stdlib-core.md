# ADR 0001: LORD core is Python 3.11+, standard library only

Status: accepted (Phase 1, 2026-09-20)

## Context

The environment inventory found Python 3.13, Node 24, Git 2.43 and ripgrep
14 installed; no tree-sitter, ast-grep, semgrep or `gh`. LORD must run on
Windows, must not require a model API, and must be portable across
unrelated projects with minimal setup.

## Decision

Implement the core in Python using only the standard library:
`ast` for confirmed Python parsing, `tokenize`/regex for heuristic
extraction in other languages, `json` for the index, `tomllib` for config,
`subprocess` for Git and ripgrep, `argparse` for the CLI, `pathlib` for
Windows-safe paths. pytest is a dev-only dependency.

## Consequences

- Zero install for users with Python: `python -m lord ...` works immediately.
- Python source analysis is CONFIRMED quality; other languages start as
  INFERRED (heuristic) and are labelled as such. Adding tree-sitter later
  is an optional capability, not a requirement.
- Node is not used. A future adapter may use it if an IDE requires it.
- Any runtime dependency needs a new ADR.
