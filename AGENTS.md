# LORD: Agent Operating Rules

This workspace runs under LORD, a model-agnostic senior-engineer harness.
The canonical, always-on contract lives in
`.agents/rules/lord-operating-contract.md` (Antigravity loads it automatically).
Any tool that reads this file instead must treat that contract as pasted here.

In one line each:

1. Explore before you edit: definition, every reference, every caller.
2. Reuse before creation: reuse -> extend -> refactor -> create, in that order.
3. Minimal correct diff: no speculative abstraction, no drive-by changes.
4. Evidence-based critical review: EVIDENCE -> CONSEQUENCE -> RECOMMENDATION -> USER DECISION.
5. Root cause over symptom; label claims CONFIRMED / INFERRED / UNKNOWN.
6. Material ambiguity: ask, or state the assumption explicitly.
7. Verify before completion; review the diff against the stated scope.

Procedure: `.agents/skills/lord-pre-edit-audit/SKILL.md`.
Tooling: `python -m lord --help` (start with `python -m lord doctor`).
Architecture and limits: `docs/ARCHITECTURE.md`.
