"""Serve the real 013a API on a synthetic world (invented symbols, fake bars, in-memory ledger) for the frontend.

Run from backend/:  python scripts/dev_server.py [full|few|open|holdings|valued|excluded|empty] [--port 8000]
`full` = 14 closed trips with NIFTY BANK alternatives and no Nifty 50 membership (the Nifty baseline is Unavailable);
`few` = 7 trips (below the 10 needed); `open` = one buy, no closed trip; `holdings` = two open positions, one has no quote (PARTIAL valuation); `valued` = the same with both quoted;
`imported` = one holding made by a tradebook import with one rejected row (charges unknown, so cost basis is incomplete); `excluded` = the traded listing is under
corporate-action review, so its trips are listed but not compared; `empty` = no trades. Offline, AI_PROVIDER=none. `scenario_app` is also used by
`record_fixtures.py`. Not part of the product: it reuses the test helpers, so it only runs from a source checkout.
"""

import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]
os.environ.setdefault("AI_PROVIDER", "none")

from analysis_helpers import NOW, TRADED, TRADED_ISIN, UNIVERSE, FakeBars, add_trade, config, seed_round_trips  # noqa: E402
from conftest import USER_A, make_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.api.main import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.domain.enums import Currency, TradeSide  # noqa: E402
from app.providers.market.port import MarketQuote  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.services.tradebook_import import TradebookImportService  # noqa: E402

TRIPS = {"full": 14, "few": 7, "excluded": 14, "open": 0, "holdings": 0, "valued": 0, "empty": 0, "imported": 0}


class FakeQuotes:
    """MarketDataProvider with fixed prices; a listing without one has no quote (the valuation is then PARTIAL)."""

    def __init__(self, prices: dict):
        self.prices = prices

    def get_quotes(self, instruments, retrieved_at):
        return {i: MarketQuote(i, Decimal(self.prices[i]), Currency.INR, retrieved_at - timedelta(hours=1), retrieved_at, "fake")
                for i in instruments if i in self.prices}


def scenario_app(name: str, llm=None, bars=None):
    engine = make_engine()
    with Session(engine) as s:
        UserRepository(s).ensure(USER_A)
        s.commit()
        if TRIPS[name]:
            seed_round_trips(s, USER_A, TRIPS[name])
        if name in ("open", "holdings", "valued"):
            add_trade(s, USER_A, TradeSide.BUY, date(2026, 9, 1))
        if name in ("holdings", "valued"):
            add_trade(s, USER_A, TradeSide.BUY, date(2026, 9, 2), qty="5", instrument=UNIVERSE[0].instrument, isin=UNIVERSE[0].isin)
        s.commit()
        if name == "imported":
            from test_tradebook_import import csv_bytes, r  # synthetic rows: one buy of the traded ISIN on each exchange, one bad side

            rows = (r(1, "buy", "6", "100", isin=TRADED_ISIN, symbol=TRADED.symbol, exchange="NSE", ts="2026-09-01T09:30:00"),
                    r(2, "buy", "4", "101", isin=TRADED_ISIN, symbol=TRADED.symbol, exchange="BSE", ts="2026-09-02T09:30:00"),
                    r(3, "hold", "1", "100", isin=TRADED_ISIN, symbol=TRADED.symbol, exchange="NSE", ts="2026-09-03T09:30:00"))
            TradebookImportService.for_session(s, clock=lambda: NOW).import_tradebook(user_id=USER_A, file_name="sept.csv", content=csv_bytes(*rows))
            s.commit()
    prices = {TRADED: "123.45", **({UNIVERSE[0].instrument: "88.8"} if name == "valued" else {})}
    cfg = config(alternatives={TRADED_ISIN: (UNIVERSE, f"alternatives: NIFTY BANK ({len(UNIVERSE)})")}, nifty50=(), luck_portfolio_count=500,
                 **({"corporate_action_listings": frozenset({TRADED})} if name == "excluded" else {}))
    return create_app(session_factory=sessionmaker(engine, expire_on_commit=False), settings=Settings(user_id=USER_A),
                      clock=lambda: NOW, history_provider=bars or FakeBars(), analysis_config=cfg, market_data=FakeQuotes(prices), analyst_llm=llm)


if __name__ == "__main__":
    import uvicorn

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
    args = [a for a in args if a != str(port)]
    uvicorn.run(scenario_app(args[0] if args else "full"), host="127.0.0.1", port=port, log_level="warning")
