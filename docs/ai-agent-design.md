# AI Agent Design & Session Bootstrap

_Last updated: 2026-07-27_

## Purpose
Define how coding agents (including GPT-5.6 Sol) should maintain project continuity and update planning artifacts.

## Primary agent role

**GPT-5.6 Sol responsibilities:**
1. Read persistent project context docs at session start.
2. Plan tasks against current architecture and roadmap.
3. Execute only requested changes.
4. Update docs when implementation meaningfully changes architecture, milestones, or decisions.

## Required session bootstrap (every new Continue session)

Before proposing a plan, read these files in order:
1. `docs/architecture.md`
2. `docs/roadmap.md`
3. `docs/milestones.md`
4. `docs/decisions.md`
5. `docs/ai-agent-design.md`

Then produce:
- A short summary of current project state.
- Any detected doc drift (if code and docs disagree).
- A task plan aligned with roadmap + milestones.

## Documentation update triggers

Update docs when any of these occur:
- New subsystem/component introduced.
- Service/repository/API boundaries change.
- AI tool interfaces/execution flow changes.
- Milestone status changes.
- A non-trivial tradeoff or irreversible choice is made.

## Post-task checklist for agents

1. Confirm code/tests status.
2. Update relevant docs listed above.
3. Add/append a decision entry for important tradeoffs.
4. Refresh `Last updated` date in modified docs.

## Operating principles

- Keep docs concise, factual, and implementation-grounded.
- Avoid speculative architecture unless marked as proposed.
- Prefer incremental updates over large rewrites.
- Never let roadmap/milestones contradict actual shipped behavior.
