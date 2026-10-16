"""Real-data demo (Feature 012): YOUR tradebook + market data fetched ONLINE (Yahoo adapter, cached) -> the 4 analyst questions.

Run from backend/:  python scripts/demo_real.py PATH_TO_TRADEBOOK.csv [--as-of YYYY-MM-DD]
Network is used only here (tests stay offline). Bars are cached under backend/.cache/ (git-ignored); a re-run for the same
as-of day makes no network call. Writes docs/reports/demo-real-YYYY-MM-DD.md (aggregates only; the tradebook is never copied).
Config: backend/config/analysis_universe.toml (static universe flag) and corporate_actions_reviewed.toml (you fill in).
"""

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.analyst.llm import TemplateLLM  # noqa: E402
from app.analyst.service import ask  # noqa: E402
from app.api.analyst_wiring import apply_caveats, quant_tools_with_caveats  # noqa: E402
from app.domain.instrument import Instrument  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.quant.regime_split.types import RegimeParameters  # noqa: E402
from app.repositories.trade_repository import TradeRepository  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.services.analysis_toml import load_reviewed, load_universe, resolve_corporate_actions  # noqa: E402
from app.services.portfolio_analysis import HISTORY_DAYS, AnalysisConfig, PortfolioAnalysisService  # noqa: E402
from app.services.tradebook_import import TradebookImportService  # noqa: E402
from bar_cache import CachingBars  # noqa: E402

USER = UUID(int=0xD1)
IST = timedelta(hours=5, minutes=30)
REPORTS = BACKEND.parent / "docs" / "reports"
QUESTIONS = ["Was my last buy skill or luck?", "What did my behaviour cost me?", "How did I do in each regime?",
             "What did the latest annual report say?"]


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


def run(tradebook: bytes, provider, as_of: date, now: datetime, out_path: Path, *, config_dir: Path | None = None,
        file_label: str = "tradebook", luck_portfolios: int = 500, replicates: int = 10_000) -> dict:
    """Import, analyse, answer the questions, write the report. `provider` is any HistoricalBarProvider (cached or fake)."""
    cfg_dir = config_dir or BACKEND / "config"
    universe = load_universe(cfg_dir / "analysis_universe.toml")
    windows = load_reviewed(cfg_dir / "corporate_actions_reviewed.toml")
    ids = iter(range(1, 1_000_000))
    with Session(_engine()) as session:
        UserRepository(session).ensure(USER)
        session.commit()
        imp = TradebookImportService.for_session(session, clock=lambda: now, id_factory=lambda: UUID(int=next(ids) + 0x7000))
        result = imp.import_tradebook(user_id=USER, file_name=file_label, content=tradebook)
        trades = TradeRepository(session).list_effective(user_id=USER)
        traded = {Instrument(t.symbol, t.exchange) for t in trades}
        listings = traded | {c.instrument for c in universe.candidates}
        first = min((t.trade_timestamp.date() for t in trades), default=as_of)
        start = first - timedelta(days=HISTORY_DAYS)
        reviewed, known = resolve_corporate_actions(windows, listings, start, as_of)
        config = AnalysisConfig(
            universe=universe.candidates, universe_static=universe.static, universe_note=universe.note,
            corporate_action_listings=known, corporate_action_reviewed=reviewed, luck_portfolio_count=luck_portfolios,
            luck_bootstrap_replicates=replicates, regime_parameters=RegimeParameters())
        service = PortfolioAnalysisService(repo=TradeRepository(session), provider=provider, clock=lambda: now, config=config)
        sections = []
        for q in QUESTIONS:
            tools, caveats = quant_tools_with_caveats(service.analyse)
            answer = apply_caveats(ask(USER, q, as_of, llm=TemplateLLM(), tools=tools, retriever=None), caveats())
            sections.append((q, answer))
        prov = service.analyse(USER, as_of).provenance
    unreviewed = sorted(f"{i.symbol}.{i.exchange.value}" for i in listings - reviewed)
    lines = [f"# Real-data demo ({now.date().isoformat()})", "",
             f"As-of D = {as_of}; provider Yahoo via cache; TemplateLLM (no model). Tradebook: {file_label} "
             f"({result.imported} rows imported, {result.duplicates} duplicates, {result.rejected_total} rejected). "
             f"Trades used: {prov['user_trade_count']}.", "",
             f"Universe: {len(universe.candidates)} listings. **{universe.note}.** Corporate-action register: "
             f"{len(windows)} reviewed window(s); reviewed {len(reviewed)} of {len(listings)} listings; known-action listings {len(known)}.",
             f"Not reviewed (their luck/regime results are Unavailable): {', '.join(unreviewed) or 'none'}.",
             f"Seeds: {prov['seeds']}. Nifty 50 membership is not configured, so the NIFTY baseline is Unavailable.", ""]
    for n, (q, a) in enumerate(sections, 1):
        lines += [f"## Q{n}. {q}", "", f"verified: **{a.verified}** (attempts {a.attempts})", "", "```", a.text, "```", "",
                  f"Citations: {', '.join(f'{c.kind}:{c.ref}' for c in a.citations) or 'none'}", ""]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"verified": sum(1 for _, a in sections if a.verified), "total": len(sections), "unreviewed": unreviewed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tradebook", type=Path)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = ap.parse_args(argv)
    from app.providers.market.yahoo import YahooProvider  # network adapter: this script only
    now = datetime.now(timezone.utc)
    as_of = args.as_of or ((now + IST).date() - timedelta(days=1))
    cache = CachingBars(YahooProvider(timeout_seconds=10, total_budget_seconds=60), BACKEND / ".cache")
    out = REPORTS / f"demo-real-{date.today().isoformat()}.md"
    summary = run(args.tradebook.read_bytes(), cache, as_of, now, out, file_label=args.tradebook.name)
    print(f"wrote {out}; {summary['verified']}/{summary['total']} verified; cache hits {cache.hits}, misses {cache.misses}; "
          f"{len(summary['unreviewed'])} listing(s) unreviewed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
