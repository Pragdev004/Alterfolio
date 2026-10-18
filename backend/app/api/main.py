from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import analysis, analyst, health, imports, portfolio, trades
from app.config import Settings
from app.db.session import make_session_factory
from app.providers.market.port import MarketDataProvider
from app.providers.market.yahoo import YahooProvider
from app.services.portfolio_analysis import AnalysisConfig
from app.services.analysis_read import AnalysisCache
from app.services.errors import AnalysisTripNotFoundError, LedgerBusyError, LedgerError, TradeNotFoundError
from app.services.users import ensure_user


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _ledger_error(_: Request, exc: LedgerError) -> JSONResponse:
    if isinstance(exc, (TradeNotFoundError, AnalysisTripNotFoundError)):
        status = 404
    elif isinstance(exc, LedgerBusyError):
        status = 409
    else:
        status = 422
    return JSONResponse(
        status_code=status, content={"detail": {"code": exc.code, "message": str(exc)}}
    )


def create_app(
    *,
    session_factory: Callable | None = None,
    settings: Settings | None = None,
    clock: Callable[[], datetime] = _utc_now,
    id_factory: Callable[[], UUID] = uuid4,
    market_data: MarketDataProvider | None = None,
    history_provider=None,
    analysis_config: AnalysisConfig | None = None,
    retriever=None,
    analyst_llm=None,
) -> FastAPI:
    """Application factory; run with `uvicorn app.api.main:create_app --factory`."""
    settings = settings or Settings()
    if session_factory is None:
        if not settings.database_url:
            raise RuntimeError("ALTERFOLIO_DATABASE_URL is required to run the server")
        if not settings.database_url.startswith("postgresql"):
            raise RuntimeError("only PostgreSQL is supported when running the server (SQLite is test-only)")
        session_factory = make_session_factory(settings.database_url)
        seed_user = True
    else:
        seed_user = False

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if seed_user:
            with session_factory() as session:
                ensure_user(session, settings.user_id)
                session.commit()
        yield

    app = FastAPI(title="Alterfolio V2", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.settings = settings
    app.state.clock = clock
    app.state.id_factory = id_factory
    app.state.market_data = market_data or YahooProvider(timeout_seconds=settings.market_timeout_seconds)
    app.state.history_provider = history_provider or YahooProvider(timeout_seconds=settings.market_timeout_seconds)
    app.state.analysis_config = analysis_config or AnalysisConfig()
    app.state.analysis_cache = AnalysisCache()  # in process, no TTL; keyed by the ledger version (Feature 013a)
    app.state.retriever = retriever  # None: no document retrieval wired (the analyst then cites no passages)
    app.state.analyst_llm = analyst_llm  # None: AI_PROVIDER decides (default none, offline)
    app.add_exception_handler(LedgerError, _ledger_error)
    app.include_router(health.router)
    app.include_router(trades.router)
    app.include_router(imports.router)
    app.include_router(portfolio.router)
    app.include_router(analyst.router)
    app.include_router(analysis.router)
    return app
