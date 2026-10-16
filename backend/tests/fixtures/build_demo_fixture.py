"""Builds the recorded, fully synthetic demo fixtures (no network): analyst_demo_bars.json, and the demo tradebook text in
memory (`tradebook_bytes()`; no second tradebook file may live in the repo, see test_repo_hygiene).

Run from backend/:  python tests/fixtures/build_demo_fixture.py   (deterministic; commit the outputs)
"""

import csv
import io
import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
START, END = date(2025, 1, 1), date(2026, 11, 30)
TRADED, TRADED_ISIN = "DEMOCO", "ZZ0DEMOCO001"
UNIVERSE = [(f"DEMOU{i:02d}", f"ZZ0UNIV{i:05d}") for i in range(1, 13)]
SYMBOLS = [TRADED] + [s for s, _ in UNIVERSE]


def close_on(k: int, d: date) -> D:
    i = (d - START).days
    amp = (D("0.2"), D("0.8"), D("1.5"))[(i // 45) % 3]
    return (D(100) + D(i) * D("0.02") + amp * D(((i * 7 + k * 5) % 11) - 5)).quantize(D("0.01"))


def main() -> None:
    days = (END - START).days + 1
    bars = {"start": START.isoformat(), "closes": {}}
    for k, symbol in enumerate(SYMBOLS):
        bars["closes"][symbol] = [str(close_on(k, START + timedelta(days=i))) for i in range(days)]
    (HERE / "analyst_demo_bars.json").write_text(json.dumps(bars, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(SYMBOLS)} bar series")


def tradebook_bytes() -> bytes:
    """Zerodha-format tradebook text (same header as tradebook_synthetic.csv): 14 round trips plus one after D."""
    header = ["symbol", "isin", "trade_date", "exchange", "segment", "series", "trade_type", "auction", "quantity", "price",
              "trade_id", "order_id", "order_execution_time"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    n = 0
    trips = [(date(2026, 3, 2) + timedelta(days=8 * k), 3) for k in range(14)] + [(date(2026, 10, 12), 3)]  # last is after D
    for buy_day, hold in trips:
        for side, day in (("buy", buy_day), ("sell", buy_day + timedelta(days=hold))):
            n += 1
            px = close_on(0, day)
            w.writerow([TRADED, TRADED_ISIN, day.isoformat(), "NSE", "EQ", "EQ", side, "false", "10.000000", f"{px:.6f}",
                        str(910000 + n), str(2000000000000000 + n), f"{day.isoformat()}T10:30:00"])
    return buf.getvalue().encode("utf-8")


if __name__ == "__main__":
    main()
