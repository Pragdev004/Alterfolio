"""Record real 013a responses from the synthetic dev world as the frontend's test fixtures (frontend/src/test/fixtures).

Run from backend/:  python scripts/record_fixtures.py
Every analysis file is the exact body the real endpoint returned (plus its status for errors); nothing is hand-written.
`trades.json` keeps only id, symbol and side (the UI only needs to know whether any trade exists). The frontend tests
serve them through MSW, so they run with no backend, network or AI credentials (spec 013 A7).
"""

import json
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from dev_server import scenario_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.analyst.llm import FakeLLM  # noqa: E402
from app.analyst.types import Draft  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "fixtures"


def write(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")


for name in ("full", "few", "open", "holdings", "valued", "excluded", "empty", "imported"):
    client = TestClient(scenario_app(name))
    write(OUT / name / "meta.json", client.get("/api/analysis/meta").json())
    trips = client.get("/api/analysis/trips").json()
    write(OUT / name / "trips.json", trips)
    write(OUT / name / "regimes.json", client.get("/api/analysis/regimes").json())
    write(OUT / name / "biases.json", client.get("/api/analysis/biases").json())
    if name in ("empty", "open"):
        trades = client.get("/trades").json()
        write(OUT / name / "trades.json", [{"id": t["id"], "symbol": t["symbol"], "side": t["side"]} for t in trades])
    if name in ("empty", "imported"):
        write(OUT / name / "status.json", client.get("/imports/status").json())
    if name in ("holdings", "valued", "empty", "imported"):
        write(OUT / name / "summary.json", client.get("/portfolio/summary").json())
        write(OUT / name / "holdings.json", client.get("/portfolio/holdings").json())
    if trips["trips"]:
        first = trips["trips"][0]["trip_id"]
        write(OUT / name / "trip.json", client.get(f"/api/analysis/trips/{first}").json())

client = TestClient(scenario_app("full"))
errors = {}
for key, path in (("not_sealed", "/api/analysis/trips?as_of=2026-12-01"), ("trip_not_found", "/api/analysis/trips/no-such-trip")):
    r = client.get(path)
    errors[key] = {"status": r.status_code, "body": r.json()}
write(OUT / "errors.json", errors)
print(f"recorded fixtures under {OUT}")

# Meta when no reference listing has any bars: last_bar_date is null with the server's sentence.
from analysis_helpers import TRADED, UNIVERSE, FakeBars  # noqa: E402

no_bars = FakeBars(missing=frozenset({TRADED, *[c.instrument for c in UNIVERSE]}))
write(OUT / "meta_no_bars.json", TestClient(scenario_app("full", bars=no_bars)).get("/api/analysis/meta").json())

# Ask: a template answer, an unverified model answer, an unconfigured provider (503) and a not-final date (422).
ASK = {"question": "What did my behaviour cost me?", "as_of": "2026-11-30"}
os.environ["AI_PROVIDER"] = "none"
ask = {}


def keep(key, response):
    ask[key] = {"status": response.status_code, "body": response.json()}


keep("template", TestClient(scenario_app("full")).post("/api/analyst/ask", json=ASK))
keep("unverified", TestClient(scenario_app("full", llm=FakeLLM([Draft("You gained 99.5% on every trip.", ())] * 5))).post("/api/analyst/ask", json=ASK))
keep("not_sealed", TestClient(scenario_app("full")).post("/api/analyst/ask", json={**ASK, "as_of": "2026-12-01"}))
os.environ["AI_PROVIDER"] = "openai_compatible"
os.environ.pop("AI_BASE_URL", None)
os.environ.pop("AI_MODEL", None)
keep("offline", TestClient(scenario_app("full")).post("/api/analyst/ask", json=ASK))
os.environ["AI_PROVIDER"] = "none"
write(OUT / "ask.json", ask)

# Upload: synthetic tradebooks only (tests/fixtures), never real ones.
FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
HEAD = "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time\n"
SELL_ONLY = HEAD + "ALPHACO,ZZ0ALPHA0001,2020-03-02,NSE,EQ,EQ,sell,false,10.000000,100.000000,910001,1000000000000009,2020-03-02T09:30:00\n"
uploads = {}


def upload(key, client, content: bytes, name="tradebook.csv"):
    r = client.post("/imports/tradebook", files={"file": (name, content, "text/csv")})
    uploads[key] = {"status": r.status_code, "body": r.json()}


client = TestClient(scenario_app("empty"))
upload("ok", client, (FIX / "tradebook_synthetic.csv").read_bytes(), "tradebook_synthetic.csv")
upload("duplicate", client, (FIX / "tradebook_synthetic.csv").read_bytes(), "tradebook_synthetic.csv")
upload("oversell", TestClient(scenario_app("empty")), SELL_ONLY.encode(), "sells_first.csv")
upload("invalid", TestClient(scenario_app("empty")), b"this is not a tradebook\n", "notes.csv")
write(OUT / "imports.json", uploads)
