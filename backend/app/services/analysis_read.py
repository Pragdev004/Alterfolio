"""Feature 013a: read side of the analysis. Resolves the as-of day, caches one analysis per ledger state, and answers `meta`.

The cache is in process, has no TTL and is keyed `(user_id, as_of, ledger_version)`: any change to the user's ledger (import,
manual trade, correction, void) changes the version, so a stale result is never served. A result that lacked a market-data series
is never stored, so a transient fetch failure cannot stick. Nothing is persisted. Imports no analyst, API or HTTP module.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from app.domain.instrument import Instrument
from app.domain.timezones import IST_OFFSET
from app.quant.luck_test.types import LIMITATIONS as LUCK_LIMITATIONS
from app.quant.market_data.exchange_time import local_date
from app.quant.regime_split.types import LIMITATIONS as REGIME_LIMITATIONS
from app.repositories.trade_repository import TradeRepository
from app.services.analysis_view import AnalysisView, build_view
from app.services.market_series import MarketSeriesService, ResolvedSeries
from app.services.portfolio_analysis import PortfolioAnalysisService, Thresholds

CACHE_MAX_ITEMS = 64  # the cache holds at most this many entries; the oldest goes first
BAR_LOOKBACK_DAYS = 14  # how far back the freshness probe looks for the newest bar


class AnalysisCache:
    """A small thread-safe dict. Values are immutable views; there is deliberately no expiry."""

    def __init__(self, max_items: int = CACHE_MAX_ITEMS) -> None:
        self._items: dict = {}
        self._max = max_items  # a size bound only (oldest entry out); results never expire by time
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            return self._items.get(key)

    def put(self, key, value) -> None:
        with self._lock:
            if key not in self._items and len(self._items) >= self._max:
                self._items.pop(next(iter(self._items)))
            self._items[key] = value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True)
class MetaView:
    latest_sealed_as_of: date
    today_ist: date
    last_bar_date: date | None
    last_bar_reason: str
    thresholds: Thresholds
    luck_limitations: tuple[str, ...]
    regime_limitations: tuple[str, ...]


class AnalysisReadService:
    def __init__(self, *, analysis: PortfolioAnalysisService, repo: TradeRepository, cache: AnalysisCache, provider,
                 clock: Callable[[], datetime]) -> None:
        self._analysis, self._repo, self._cache, self._provider, self._clock = analysis, repo, cache, provider, clock

    @classmethod
    def for_session(cls, session, *, provider, clock: Callable[[], datetime], config, cache: AnalysisCache) -> "AnalysisReadService":
        return cls(analysis=PortfolioAnalysisService.for_session(session, provider=provider, clock=clock, config=config),
                   repo=TradeRepository(session), cache=cache, provider=provider, clock=clock)

    def resolve_as_of(self, as_of: date | None) -> tuple[date, bool]:
        """(as-of day, defaulted). Omitted = the latest sealed day, never today; today or later raises AsOfNotSealedError."""
        if as_of is None:
            return self._analysis.latest_sealed(), True
        self._analysis.require_sealed(as_of)
        return as_of, False

    def view(self, user_id: UUID, as_of: date) -> AnalysisView:
        key = (user_id, as_of, self._repo.ledger_version(user_id=user_id))
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        detail = self._analysis.analyse_detail(user_id, as_of)
        view = build_view(detail, as_of)
        if not detail.facts.provenance["series_unavailable"]:
            self._cache.put(key, view)
        return view

    def meta(self, user_id: UUID) -> MetaView:
        now = self._clock()
        sealed = self._analysis.latest_sealed()
        last, reason = self._last_bar_date(user_id, sealed, now)
        return MetaView(sealed, local_date(now, IST_OFFSET), last, reason, self._analysis.thresholds(), tuple(LUCK_LIMITATIONS),
                        tuple(REGIME_LIMITATIONS))

    def _last_bar_date(self, user_id: UUID, sealed: date, now: datetime) -> tuple[date | None, str]:
        """Newest session date of a reference series (the user's first traded listing, else the first universe listing)."""
        rows = self._repo.list_effective(user_id=user_id)
        universe = self._analysis.config.universe
        if rows:
            listing = Instrument(rows[0].symbol, rows[0].exchange)
        elif universe:
            listing = universe[0].instrument
        else:
            return None, "no reference listing: the ledger is empty and no universe is configured"
        key = ("last_bar", listing, sealed)
        hit = self._cache.get(key)
        if hit is not None:
            return hit, ""
        r = MarketSeriesService(provider=self._provider, clock=lambda: now).resolve_series(
            [listing], sealed - timedelta(days=BAR_LOOKBACK_DAYS), sealed)
        if not isinstance(r, ResolvedSeries):
            why = ",".join(a.outcome.value for a in r.attempts)
            return None, f"no bars for {listing.symbol}.{listing.exchange.value}: {why}"
        bars = [b.session_date for b in r.series.bars if b.session_date <= sealed]
        if not bars:
            return None, f"no bars for {listing.symbol}.{listing.exchange.value} in the last {BAR_LOOKBACK_DAYS} days"
        self._cache.put(key, max(bars))
        return max(bars), ""
