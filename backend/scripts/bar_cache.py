"""Disk cache in front of a HistoricalBarProvider (Feature 012 demo only). A hit makes no provider call.

Key: (symbol, exchange, start, end). Only successful batches are cached, never failures. The cached batch is replayed
with the caller's `retrieved_at` (the series service requires the echo); its source label is unchanged, so series
fingerprints are identical on a hit and a miss.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.domain.enums import Currency
from app.providers.market.history_port import RawBar, RawBarBatch


class CachingBars:
    def __init__(self, inner, cache_dir: Path) -> None:
        self._inner, self._dir = inner, Path(cache_dir)
        self.hits = self.misses = 0

    def _path(self, instrument, start: date, end: date) -> Path:
        return self._dir / f"{instrument.symbol}.{instrument.exchange.value}.{start}.{end}.json"

    def get_daily_bars(self, instrument, start, end, retrieved_at):
        path = self._path(instrument, start, end)
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            bars = tuple(RawBar(datetime.fromisoformat(b["ts"]), date.fromisoformat(b["d"]), *(Decimal(b[k]) for k in ("o", "h", "l", "c", "a")), int(b["v"]))
                         for b in d["bars"])
            self.hits += 1
            return RawBarBatch(instrument, bars, Currency(d["currency"]), d["source"], retrieved_at,
                               timedelta(seconds=d["offset_s"]), d["rows_returned"], d["empty_rows_excluded"])
        self.misses += 1
        batch = self._inner.get_daily_bars(instrument, start, end, retrieved_at)
        if isinstance(batch, RawBarBatch):
            self._dir.mkdir(parents=True, exist_ok=True)
            payload = {"currency": batch.currency.value, "source": batch.source, "offset_s": int(batch.exchange_utc_offset.total_seconds()),
                       "rows_returned": batch.rows_returned, "empty_rows_excluded": batch.empty_rows_excluded,
                       "bars": [{"ts": b.timestamp.isoformat(), "d": b.session_date.isoformat(), "o": str(b.open), "h": str(b.high),
                                 "l": str(b.low), "c": str(b.close), "a": str(b.adjusted_close), "v": b.volume} for b in batch.bars]}
            path.write_text(json.dumps(payload), encoding="utf-8")
        return batch
