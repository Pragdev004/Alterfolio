# Alterfolio Milestones

_Last updated: 2026-07-27_

## Milestone tracker

| Milestone | Status | Target | Notes |
|---|---|---|---|
| M1: Backend foundation (FastAPI + DB + core domain) | Done | 2026-Q3 | Core routes/services/repos in place; API contract documented |
| M2: AI portfolio analysis workflow | In Progress | 2026-Q3 | Analysis endpoint + tool-call foundations present |
| M3: AI tooling hardening + coverage | Planned | 2026-Q3 | Expand tests, edge-case handling, observability |
| M4: Frontend MVP | Planned | 2026-Q4 | Portfolio/trades dashboard + insight surfaces |
| M5: AI twin simulation loop | Planned | 2027-Q1 | Shadow trades and comparative outcomes |

## Acceptance checkpoints

### M1 checkpoints
- [x] FastAPI app bootstrapped
- [x] Trades and portfolio routes implemented
- [x] SQLAlchemy + PostgreSQL connectivity in place
- [x] API contract documentation complete

### M2 checkpoints
- [x] AI analysis endpoint wired
- [x] Tool registry + tool executor introduced
- [x] Basic tool executor tests present
- [ ] End-to-end AI integration tests stabilized

### M3 checkpoints
- [ ] Tool-call error taxonomy and retries
- [ ] Structured logging for agent tool loops
- [ ] Coverage threshold defined and enforced in CI

## How to maintain this file

- Add/update milestones whenever roadmap scope changes.
- Keep status values to: `Planned`, `In Progress`, `Blocked`, `Done`.
- Link major changes to `docs/decisions.md` entries.
