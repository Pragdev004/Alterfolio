from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.routes.trades import router as trades_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.astra import router as astra_router


api_router = APIRouter()

api_router.include_router(
    health_router,
    tags=["Health"],
)

api_router.include_router(
    trades_router,
    prefix="/trades",
    tags=["Trades"],
)

api_router.include_router(
    portfolio_router,
    prefix="/portfolio",
    tags=["Portfolio"],
)

api_router.include_router(
    astra_router,
    prefix="/astra",
    tags=["Astra"],
)