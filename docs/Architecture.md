# Alterfolio Architecture

_Last updated: 2026-07-27_

## 1) System overview

Alterfolio is currently a backend-first system built with FastAPI, PostgreSQL (via SQLAlchemy), and Azure OpenAI integration for portfolio analysis and tool-driven agent behavior.

## 2) Current repository shape

- `backend/`: Primary application runtime
  - `app/main.py`: FastAPI app bootstrap
  - `app/api/`: API routers (`/trades`, `/portfolio`, `/health`)
  - `app/services/`: Business services (trade, portfolio, market, news, AI)
  - `app/services/ai/`: AI orchestration, prompt layer, tool definitions/execution
  - `app/repositories/`: Persistence abstraction per aggregate
  - `app/models/`: SQLAlchemy models
  - `app/schemas/`: Pydantic I/O and domain response contracts
  - `tests/`: pytest suite
- `frontend/`: Reserved (currently empty)
- `infrastructure/`: Reserved (currently empty)

## 3) Runtime architecture (current)

### API layer
- FastAPI routers delegate to service layer.
- Dependency injection is used to construct repositories/services per request.

### Service layer
- `TradeService`: trade operations.
- `PortfolioService`: summary and portfolio calculations.
- `MarketService` / `NewsService`: market/news provider integration.
- `AIWorkflowService`: composes portfolio + market + news context and requests AI analysis.

### AI agent/tool layer
- `ToolRegistry` owns concrete tool instances (`PortfolioTool`, `MarketTool`, `NewsTool`).
- `ToolExecutor` routes model tool calls by tool name.
- `AIService.run_agent(...)` loops over function calls until model returns final text.

### Data layer
- SQLAlchemy engine/session via `app/db/database.py`.
- Repositories isolate persistence logic from services.

## 4) External dependencies

- PostgreSQL (`psycopg` driver)
- Azure OpenAI Responses API
- Market/news providers (through service abstractions)

## 5) Key flows

1. **Trade write/read flow**: Router -> Service -> Repository -> DB -> response schema.
2. **Portfolio analysis flow**: Router -> `AIWorkflowService` -> gather summary/quotes/news -> `AIService.analyze_portfolio` -> structured AI output.
3. **Tool-calling agent flow**: `AIService.run_agent` -> model function calls -> `ToolExecutor` -> tool outputs -> follow-up model turn(s).

## 6) Known gaps / next architecture steps

- Frontend app and deployment topology not yet codified.
- Background jobs/eventing for async workflows not yet introduced.
- Provider adapters and retry/circuit-breaker patterns should be formalized.
- Security architecture (authn/authz, tenancy boundaries) needs an explicit design doc.

## 7) How to maintain this doc

Update this file whenever any of the following changes:
- Router/service/repository boundaries
- AI tool orchestration flow
- Database strategy or provider strategy
- New runtime components (workers, queues, frontend, infra)
