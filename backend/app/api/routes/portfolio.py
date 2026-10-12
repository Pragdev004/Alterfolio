from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id, get_ledger, get_summary_service
from app.schemas.summary import QuoteOut, SummaryHoldingOut, SummaryOut
from app.schemas.trade import HoldingOut, ListingOut
from app.services.errors import HistoricalValuationUnsupportedError
from app.services.ledger import LedgerService
from app.services.portfolio_summary import PortfolioSummaryService, QuoteStatus, ValuedHolding

router = APIRouter(prefix="/portfolio")


@router.get("/holdings", response_model=list[HoldingOut])
def holdings(
    as_of: datetime | None = None,
    user_id: UUID = Depends(get_current_user_id),
    ledger: LedgerService = Depends(get_ledger),
):
    return [
        HoldingOut(
            isin=h.key.isin,
            listings=[ListingOut(symbol=i.symbol, exchange=i.exchange) for i in h.listings],
            name=h.name,
            quantity=h.quantity,
            average_buy_price=h.average_buy_price,
            invested_amount=h.invested_amount,
            cost_basis_complete=h.cost_basis_complete,
        )
        for h in ledger.holdings(user_id=user_id, as_of=as_of)
    ]


def _summary_holding(v: ValuedHolding) -> SummaryHoldingOut:
    h, q = v.holding, v.quote
    return SummaryHoldingOut(
        isin=h.key.isin,
        listings=[ListingOut(symbol=i.symbol, exchange=i.exchange) for i in h.listings],
        name=h.name,
        quantity=h.quantity,
        average_buy_price=h.average_buy_price,
        invested_amount=h.invested_amount,
        cost_basis_complete=h.cost_basis_complete,
        quote_status=v.quote_status.value,
        quote=None
        if q is None
        else QuoteOut(
            symbol=q.instrument.symbol,
            exchange=q.instrument.exchange,
            price=q.price,
            currency=q.currency,
            price_timestamp=q.price_timestamp,
            retrieved_at=q.retrieved_at,
            source=q.source,
        ),
        market_value=v.market_value,
        unrealized_pnl=v.unrealized_pnl,
    )


@router.get("/summary", response_model=SummaryOut)
def summary(
    as_of: datetime | None = None,
    user_id: UUID = Depends(get_current_user_id),
    service: PortfolioSummaryService = Depends(get_summary_service),
):
    if as_of is not None:
        raise HistoricalValuationUnsupportedError()
    s = service.summary(user_id=user_id)
    return SummaryOut(
        valuation_time=s.valuation_time,
        valuation_status=s.valuation_status.value,
        total_trades=s.total_trades,
        holdings_count=len(s.holdings),
        valued_holdings_count=sum(1 for v in s.holdings if v.quote_status is QuoteStatus.VALUED),
        total_invested=s.total_invested,
        total_market_value=s.total_market_value,
        total_unrealized_pnl=s.total_unrealized_pnl,
        cost_basis_complete=s.cost_basis_complete,
        holdings=[_summary_holding(v) for v in s.holdings],
    )
