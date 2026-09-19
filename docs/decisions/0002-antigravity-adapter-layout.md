# ADR 0002: One contract rule, procedures in skills, roles in agents

Status: accepted (Phase 1, 2026-09-20)

## Context

The v0.1 experiment kept identical copies of the rules in `AGENTS.md`,
`CLAUDE.md` and `GEMINI.md` plus four rule files and one workflow. Copies
drift, and Antigravity now documents `.agents/rules`, `.agents/skills`,
`.agents/agents`, `.agents/hooks.json` and plugins as the supported
customisation surface (with workflows migrating to skills).

## Decision

- Exactly one always-on rule, `.agents/rules/lord-operating-contract.md`,
  holds the behavioural principles (under the 12,000-character limit).
- Procedures live in skills (`lord-pre-edit-audit` now; reuse audit, impact
  and verification skills in Phases 3-5).
- Roles live in custom subagents (`lord-investigator` now; the remaining
  specialists in Phase 5).
- `AGENTS.md` at the root is a seven-line pointer for tools that read it;
  `CLAUDE.md` imports `AGENTS.md`. No `GEMINI.md` copy at the workspace root.
- Hooks and plugins are deferred to Phases 6 and 8; no placeholder files.

## Consequences

- No duplicated rule content; one place to edit.
- Other IDEs get an adapter later by mapping the same three concepts
  (contract, procedures, roles) onto their mechanisms.
- If Antigravity ignores `AGENTS.md`, nothing is lost: the `.agents` rule is
  the canonical source.
