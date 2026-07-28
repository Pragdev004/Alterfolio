# Alterfolio Decisions Log

_Last updated: 2026-07-27_

This file records concise architectural and product decisions. For deep ADRs, link to `docs/ADR/` when available.

## Decision format

- **ID**: DEC-XXXX
- **Date**: YYYY-MM-DD
- **Status**: Proposed | Accepted | Superseded
- **Context**
- **Decision**
- **Consequences**

---

## DEC-0001
- **Date**: 2026-07-27
- **Status**: Accepted
- **Context**: AI workflows required callable domain tools without tightly coupling routing logic to core services.
- **Decision**: Introduce `ToolRegistry` + `ToolExecutor` to route model tool calls to domain-backed tool adapters.
- **Consequences**: Cleaner AI orchestration boundary; easier testability; requires explicit mapping maintenance for new tools.

## DEC-0002
- **Date**: 2026-07-27
- **Status**: Accepted
- **Context**: Project context is getting large and repeated onboarding per session is expensive.
- **Decision**: Maintain persistent docs (`architecture.md`, `roadmap.md`, `milestones.md`, `decisions.md`, `ai-agent-design.md`) as session bootstrap context.
- **Consequences**: Better continuity; requires disciplined updates after major changes.

## DEC-0003
- **Date**: 2026-07-27
- **Status**: Accepted
- **Context**: M1 required explicit API contract documentation aligned with implemented FastAPI routes and schemas.
- **Decision**: Standardize endpoint contract details in `docs/API.md` as the current API reference.
- **Consequences**: Faster onboarding and reduced ambiguity for clients; requires updates whenever route or schema contracts change.

## Maintenance policy

After meaningful implementation changes, update:
1. `docs/decisions.md` (what changed and why)
2. `docs/architecture.md` (if structure/flows changed)
3. `docs/milestones.md` (if checkpoint status changed)
