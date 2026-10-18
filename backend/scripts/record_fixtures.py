"""Record real 013a responses from the synthetic dev world as the frontend's test fixtures (frontend/src/test/fixtures).

Run from backend/:  python scripts/record_fixtures.py
Every analysis file is the exact body the real endpoint returned (plus its status for errors); nothing is hand-written.
`trades.json` keeps only id, symbol and side (the UI only needs to know whether any trade exists). The frontend tests
serve them through MSW, so they run with no backend, network or AI credentials (spec 013 A7).
"""

import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from dev_server import scenario_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "fixtures"


def write(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")


for name in ("full", "few", "open", "excluded", "empty"):
    client = TestClient(scenario_app(name))
    write(OUT / name / "meta.json", client.get("/api/analysis/meta").json())
    trips = client.get("/api/analysis/trips").json()
    write(OUT / name / "trips.json", trips)
    write(OUT / name / "regimes.json", client.get("/api/analysis/regimes").json())
    write(OUT / name / "biases.json", client.get("/api/analysis/biases").json())
    if name in ("empty", "open"):
        trades = client.get("/trades").json()
        write(OUT / name / "trades.json", [{"id": t["id"], "symbol": t["symbol"], "side": t["side"]} for t in trades])
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
