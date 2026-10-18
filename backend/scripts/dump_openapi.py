"""Write the app's /openapi.json to a file (default frontend/openapi.json) without a database or network.

Run from backend/:  python scripts/dump_openapi.py ../frontend/openapi.json
The frontend generates its API types from that file (`npm run gen:types`), so the compiler sees the same schema the server serves.
"""

import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from dev_server import scenario_app  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "../frontend/openapi.json")
out.write_text(json.dumps(scenario_app("empty").openapi(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {out}")
