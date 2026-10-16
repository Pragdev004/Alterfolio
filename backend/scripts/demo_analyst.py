"""Offline demo of the 011 wiring: fixture tradebook + recorded bars -> real 006/007/008 facts -> the 010 analyst.

Run from backend/:  python scripts/demo_analyst.py     Writes docs/reports/demo-analyst-YYYY-MM-DD.md.
No network (a socket guard enforces it), AI_PROVIDER=none (TemplateLLM). Rebuild the fixtures with
tests/fixtures/build_demo_fixture.py; they are synthetic (invented symbols and ISINs).
"""

import json
import os
import socket
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["AI_PROVIDER"] = "none"

_connect = socket.socket.connect


def _guard(self, address, *a, **k):
    if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
        raise RuntimeError(f"demo is offline; blocked connection to {address!r}")
    return _connect(self, address, *a, **k)


socket.socket.connect = _guard

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.analyst.llm import TemplateLLM  # noqa: E402
from app.analyst.service import ask  # noqa: E402
from app.api.analyst_wiring import quant_tools_from  # noqa: E402
from app.domain.enums import Currency, Exchange  # noqa: E402
from app.domain.instrument import Instrument  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.providers.market.history_port import BarFailure, BarFailureKind, RawBar, RawBarBatch  # noqa: E402
from app.quant.luck_test.types import Candidate, Membership  # noqa: E402
from app.quant.regime_split.types import RegimeParameters  # noqa: E402
from app.repositories.trade_repository import TradeRepository  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.services.portfolio_analysis import AnalysisConfig, PortfolioAnalysisService  # noqa: E402
from app.services.tradebook_import import TradebookImportService  # noqa: E402

FIX = BACKEND / "tests" / "fixtures"
REPORTS = BACKEND.parent / "docs" / "reports"
USER = UUID(int=0xD0)
CLOCK_NOW = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 9, 30)
IST = timedelta(hours=5, minutes=30)
TRADED = "DEMOCO"


class ReplayBars:
    """HistoricalBarProvider replaying the recorded fixture (honours `end`, like a real provider)."""

    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self._start = date.fromisoformat(data["start"])
        self._closes = {s: [Decimal(c) for c in v] for s, v in data["closes"].items()}

    def get_daily_bars(self, instrument, start, end, retrieved_at):
        closes = self._closes.get(instrument.symbol)
        if closes is None or instrument.exchange is not Exchange.NSE:
            return BarFailure(BarFailureKind.NOT_FOUND, "not in the recorded fixture")
        bars = []
        for i, c in enumerate(closes):
            d = self._start + timedelta(days=i)
            if start <= d <= end:
                bars.append(RawBar(datetime(d.year, d.month, d.day, 3, 45, tzinfo=timezone.utc), d, c, c, c, c, c, 1000))
        return RawBarBatch(instrument, tuple(bars), Currency.INR, "recorded-fixture", retrieved_at, IST, len(bars), 0)


class DemoRetriever:
    """Duck-typed RetrievalService: one note before D and one after D, whatever the query (the graph must drop the late one)."""

    def __init__(self) -> None:
        self.returned: list[str] = []
        self.chunks = [
            SimpleNamespace(chunk_id="11111111-1111-1111-1111-111111111111", source_id="h1-outlook-note", chunk_index=0,
                            text="Management outlook note for the first half.", score=0.5, rank=1,
                            published_at=datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)),
            SimpleNamespace(chunk_id="22222222-2222-2222-2222-222222222222", source_id="nov-results-announcement",
                            chunk_index=0, text="Results announcement published in November.", score=0.4, rank=2,
                            published_at=datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)),
        ]

    def search(self, *, user_id, query_text, cutoff, k):
        self.returned = [f"{c.source_id} ({c.published_at.date()})" for c in self.chunks]
        return SimpleNamespace(provenance=SimpleNamespace(cutoff=cutoff), chunks=tuple(self.chunks))


def _engine():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _on(conn, _):
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    return engine


def _recording(tool, used):
    def call(user_id, as_of):
        facts = tool(user_id, as_of)
        used.extend(facts)
        return facts
    return call


def collect() -> dict:
    """Run the offline demo and return everything a renderer needs (no files written)."""
    sys.path.insert(0, str(FIX))
    from build_demo_fixture import tradebook_bytes
    ids = iter(range(1, 10_000))
    with Session(_engine()) as session:
        UserRepository(session).ensure(USER)
        session.commit()
        imp = TradebookImportService.for_session(session, clock=lambda: CLOCK_NOW, id_factory=lambda: UUID(int=next(ids) + 0x5000))
        result = imp.import_tradebook(user_id=USER, file_name="tradebook_demo.csv", content=tradebook_bytes())
        universe = tuple(Candidate(Instrument(f"DEMOU{i:02d}", Exchange.NSE), f"ZZ0UNIV{i:05d}") for i in range(1, 13))
        listings = frozenset({Instrument(TRADED, Exchange.NSE)} | {c.instrument for c in universe})
        config = AnalysisConfig(
            universe=universe, nifty50=tuple(Membership(c.isin, date(2020, 1, 1)) for c in universe),
            corporate_action_reviewed=listings,  # synthetic fixture: no corporate actions exist; declared for this demo only
            luck_portfolio_count=100, luck_bootstrap_replicates=1000, regime_parameters=RegimeParameters(min_trips_per_regime=3))
        service = PortfolioAnalysisService(repo=TradeRepository(session), provider=ReplayBars(FIX / "analyst_demo_bars.json"),
                                           clock=lambda: CLOCK_NOW, config=config)
        retriever = DemoRetriever()
        questions = ["Was my last buy skill or luck?", "What did my behaviour cost me?", "How did I do in each regime?",
                     "What did the November 2026 results announcement say?"]
        sections = []
        for q in questions:
            used: list = []
            tools = {k: _recording(t, used) for k, t in quant_tools_from(service.analyse).items()}
            retriever.returned = []
            answer = ask(USER, q, AS_OF, llm=TemplateLLM(), tools=tools, retriever=retriever)
            sections.append((q, answer, [f"{c.kind}:{c.ref}" for c in answer.citations], used, list(retriever.returned)))
        facts = service.analyse(USER, AS_OF)
    return {"sections": sections, "facts": facts, "imported": result.imported, "as_of": AS_OF, "clock": CLOCK_NOW}


def main(argv: list[str] | None = None) -> int:
    """`python scripts/demo_analyst.py [OUT_DIR]`: OUT_DIR defaults to docs/reports."""
    if not (FIX / "analyst_demo_bars.json").exists():
        print("missing fixture analyst_demo_bars.json; run tests/fixtures/build_demo_fixture.py", file=sys.stderr)
        return 2
    argv = sys.argv[1:] if argv is None else argv
    out_dir = Path(argv[0]) if argv else REPORTS
    data = collect()
    sections, provenance, imported = data["sections"], data["facts"].provenance, data["imported"]
    unverified = sum(0 if a.verified else 1 for _, a, *_ in sections)
    out = out_dir / f"demo-analyst-{date.today().isoformat()}.md"
    lines = [f"# Demo: analyst on real facts ({date.today().isoformat()})", "",
             f"Offline run. As-of D = {AS_OF}; injected clock {CLOCK_NOW:%Y-%m-%d %H:%M}Z; provider none (TemplateLLM); "
             f"fixtures: tradebook built in memory by `build_demo_fixture.py` in the `tradebook_synthetic.csv` format ({imported} rows imported, 2 of them after D and must be ignored) and "
             "recorded `analyst_demo_bars.json` (bars run to 2026-11-30; none after D may be used). All data is synthetic.", "",
             f"Seeds: {provenance['seeds']}. Luck universe: 12 synthetic NSE listings; corporate-action coverage declared for the fixture only.",
             f"Trades used: {provenance['user_trade_count']}. Late-recorded rows: {provenance['late_recorded_row_count']} "
             "(imported after D by nature; disclosed, not filtered).", ""]
    for n, (q, a, cited, used, returned) in enumerate(sections, 1):
        lines += [f"## Q{n}. {q}", "", f"verified: **{a.verified}** (attempts {a.attempts})", "", "Answer:", "```", a.text, "```", "",
                  f"Citations: {', '.join(cited) or 'none'}", ""]
        if returned:
            kept = [c for c in cited if c.startswith("chunk:")]
            late = [r for r in returned if r.split("(")[-1].rstrip(")") > AS_OF.isoformat()]
            lines += [f"Retriever returned: {', '.join(returned)}. Dated after D and dropped by the analyst: {len(late)}; cited: {len(kept)}.", ""]
        lines += ["Facts used (" + str(len(used)) + "): " + (", ".join(f"{f.name}={f.value}" for f in used) if used else "none (documents only)"), ""]
    out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}; {len(sections) - unverified}/{len(sections)} answers verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
