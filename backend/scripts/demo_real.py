"""Real-data demo (Feature 012): YOUR tradebook + market data fetched ONLINE (Yahoo adapter, cached) -> the 4 analyst questions.

Run from backend/:  python scripts/demo_real.py TRADEBOOK.csv [MORE.csv ...] [--as-of YYYY-MM-DD]
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
from app.services.analysis_toml import load_aliases, load_reviewed, load_universe, resolve_corporate_actions  # noqa: E402
from app.services.tradebook_merge import merge_tradebooks  # noqa: E402
from app.services.portfolio_analysis import HISTORY_DAYS, AnalysisConfig, PortfolioAnalysisService  # noqa: E402
from app.services.tradebook_import import TradebookImportService  # noqa: E402
from bar_cache import AliasingBars, CachingBars  # noqa: E402

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


def run(tradebooks: list[tuple[str, bytes]], provider, as_of: date, now: datetime, out_path: Path, *,
        config_dir: Path | None = None, luck_portfolios: int = 500, replicates: int = 10_000) -> dict:
    """Import, analyse, answer the questions, write the report. `provider` is any HistoricalBarProvider (cached or fake)."""
    cfg_dir = config_dir or BACKEND / "config"
    universe = load_universe(cfg_dir / "analysis_universe.toml")
    windows = load_reviewed(cfg_dir / "corporate_actions_reviewed.toml")
    aliases = load_aliases(cfg_dir / "symbol_aliases.toml") if (cfg_dir / "symbol_aliases.toml").exists() else {}
    if aliases:
        provider = AliasingBars(provider, aliases)  # market-data lookup only; ledger and reports keep the original symbol
    ids = iter(range(1, 1_000_000))
    with Session(_engine()) as session:
        UserRepository(session).ensure(USER)
        session.commit()
        imp = TradebookImportService.for_session(session, clock=lambda: now, id_factory=lambda: UUID(int=next(ids) + 0x7000))
        # ONE import over the merged files: separate imports are order-dependent (a sell imported before its buy is rejected).
        merged = merge_tradebooks([content for _, content in tradebooks])
        result = imp.import_tradebook(user_id=USER, file_name="merged-tradebooks", content=merged)
        imported, duplicates, rejected = result.imported, result.duplicates, result.rejected_total
        merged_lines = merged.decode("utf-8").splitlines()
        rejected_rows = [(r.line, merged_lines[r.line - 1].split(",")[0] if 0 < r.line <= len(merged_lines) else "?", r.code, r.message)
                         for r in result.rejected]
        trades = TradeRepository(session).list_effective(user_id=USER)
        traded = {Instrument(t.symbol, t.exchange) for t in trades}
        listings = traded | {c.instrument for c in universe.candidates}
        first = min((t.trade_timestamp.date() for t in trades), default=as_of)
        start = first - timedelta(days=HISTORY_DAYS)
        isin_of = {Instrument(t.symbol, t.exchange): t.isin for t in trades if t.isin}
        isin_of.update({c.instrument: c.isin for c in universe.candidates})
        reviewed, known = resolve_corporate_actions(windows, listings, start, as_of, isin_of)
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
        facts_all = service.analyse(USER, as_of)
        prov = facts_all.provenance
    unreviewed = sorted(f"{i.symbol}.{i.exchange.value}" for i in listings - reviewed)
    lines = [f"# Real-data demo ({now.date().isoformat()})", "",
             f"As-of D = {as_of}; provider Yahoo via cache; TemplateLLM (no model). Tradebooks merged and imported once: {len(tradebooks)}. "
             f"Rows imported {imported}, skipped as duplicates {duplicates}, rejected {rejected}. "
             f"Trades used: {prov['user_trade_count']}.", "",
             f"Universe: {len(universe.candidates)} listings. **{universe.note}.** Corporate-action register: "
             f"{len(windows)} reviewed window(s); reviewed {len(reviewed)} of {len(listings)} listings; known-action listings {len(known)}.",
             "Rejected rows (row of the merged file, symbol, reason): "
             + ("; ".join(f"{n} {sym} {code} ({msg})" for n, sym, code, msg in rejected_rows) or "none") + ".",
             f"Market-data symbol aliases (lookup only): {', '.join(f'{k}->{v}' for k, v in aliases.items()) or 'none'}.",
             f"Not reviewed (their luck/regime results are Unavailable): {', '.join(unreviewed) or 'none'}.",
             f"Seeds: {prov['seeds']}. Nifty 50 membership is not configured, so the NIFTY baseline is Unavailable.", ""]
    for n, (q, a) in enumerate(sections, 1):
        lines += [f"## Q{n}. {q}", "", f"verified: **{a.verified}** (attempts {a.attempts})", "", "```", a.text, "```", "",
                  f"Citations: {', '.join(f'{c.kind}:{c.ref}' for c in a.citations) or 'none'}", ""]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"facts": [f.to_dict() for f in facts_all.facts], "provenance": prov, "imported": imported, "duplicates": duplicates, "rejected": rejected, "verified": sum(1 for _, a in sections if a.verified), "total": len(sections), "unreviewed": unreviewed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tradebooks", type=Path, nargs="+")
    ap.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = ap.parse_args(argv)
    from app.providers.market.yahoo import YahooProvider  # network adapter: this script only
    now = datetime.now(timezone.utc)
    as_of = args.as_of or ((now + IST).date() - timedelta(days=1))
    cache = CachingBars(YahooProvider(timeout_seconds=10, total_budget_seconds=60), BACKEND / ".cache")
    out = REPORTS / f"demo-real-{date.today().isoformat()}.md"
    summary = run([(p.name, p.read_bytes()) for p in args.tradebooks], cache, as_of, now, out)
    print(f"wrote {out}; {summary['verified']}/{summary['total']} verified; rows {summary['imported']} imported, {summary['duplicates']} duplicate, {summary['rejected']} rejected; cache hits {cache.hits}, misses {cache.misses}; "
          f"{len(summary['unreviewed'])} listing(s) unreviewed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
