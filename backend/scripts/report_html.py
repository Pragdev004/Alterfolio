"""Self-contained HTML report (inline CSS + inline SVG only: no network, no CDN, no scripts).

  python scripts/report_html.py                      OFFLINE demo (synthetic) -> docs/demo/alterfolio-demo.html  (committed)
  python scripts/report_html.py --real A.csv [B.csv] YOUR data (online, cached) -> docs/reports/demo-real-YYYY-MM-DD.html
                                                     (git-ignored by the `docs/reports/demo-real-*` rule; never written elsewhere)
"""

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
DOCS = BACKEND.parent / "docs"

CSS = """
:root{--bg:#f7f6f2;--fg:#1d1f24;--mut:#5b6068;--card:#fff;--line:#dcdad2;--ok:#1f7a4d;--bad:#b3261e;--na:#8a5a00;--acc:#27408b}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e8e6df;--mut:#9aa0a8;--card:#1c1f25;--line:#2f333b;--ok:#5fcf9a;--bad:#ff8a80;--na:#e0b04a;--acc:#9db4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 16px 64px}h1{font-size:1.7rem;margin:0 0 4px}h2{font-size:1.2rem;margin:32px 0 10px}
.sub{color:var(--mut);margin:0 0 16px}.meta{color:var(--mut);font-size:.9rem}.meta p{margin:4px 0}
section.q{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
section.q h3{margin:0 0 8px;font-size:1.05rem}.badge{display:inline-flex;align-items:center;gap:6px;font-weight:600;font-size:.9rem}
.ok{color:var(--ok)}.bad{color:var(--bad)}pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.45 ui-monospace,Consolas,monospace;margin:8px 0}
.cit{color:var(--mut);font-size:.82rem;word-break:break-all}table{width:100%;border-collapse:collapse;font-size:.88rem}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600}
td.v{font-family:ui-monospace,Consolas,monospace;word-break:break-all}td.na{color:var(--na)}.wrap{overflow-x:auto}
details{margin-top:8px}summary{cursor:pointer;color:var(--acc)}.refuse{border-left:4px solid var(--na);padding-left:12px}
svg text{fill:var(--fg);font:12px system-ui,sans-serif}
"""

CHECK = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5 9.5l3 3 5-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
CROSS = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M6 6l6 6M12 6l-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'


def _facts_table(rows) -> str:
    body = "".join(
        f'<tr><td>{escape(r["name"])}</td><td class="v{" na" if r["value"] == "Unavailable" else ""}">{escape(r["value"])}</td>'
        f'<td>{escape(r.get("unit", ""))}</td><td>{escape(r.get("source", ""))}</td></tr>' for r in rows)
    return f'<div class="wrap"><table><thead><tr><th>Fact</th><th>Value</th><th>Unit</th><th>Source</th></tr></thead><tbody>{body}</tbody></table></div>'


def _regime_chart(facts) -> str:
    counts = {}
    for f in facts:
        for r in ("LOW", "NORMAL", "HIGH"):
            if f["name"] == f"regime.{r}.trip_count" and f["value"] != "Unavailable":
                counts[r] = int(f["value"])
    if not counts:
        return ""
    top = max(counts.values()) or 1
    bars = "".join(
        f'<text x="0" y="{22 + i * 28}">{r}</text><rect x="70" y="{9 + i * 28}" width="{int(300 * n / top)}" height="16" rx="3" fill="var(--acc)"/>'
        f'<text x="{78 + int(300 * n / top)}" y="{22 + i * 28}">{n}</text>' for i, (r, n) in enumerate(counts.items()))
    return (f'<h2>Round trips by volatility regime</h2><svg width="100%" viewBox="0 0 420 {len(counts) * 28 + 8}" role="img" '
            f'aria-label="Round trips per regime">{bars}</svg>')


def render(model: dict) -> str:
    out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{escape(model["title"])}</title><style>{CSS}</style></head><body><main>',
           f'<h1>{escape(model["title"])}</h1><p class="sub">{escape(model["subtitle"])}</p>',
           '<div class="meta">' + "".join(f"<p>{escape(m)}</p>" for m in model["meta"]) + "</div>"]
    for n, s in enumerate(model["sections"], 1):
        verdict = (f'<span class="badge ok">{CHECK} verified: yes</span>' if s["verified"]
                   else f'<span class="badge bad">{CROSS} verified: no</span>')
        cites = ", ".join(s["citations"]) or "none"
        out.append(f'<section class="q"><h3>Q{n}. {escape(s["q"])}</h3>{verdict} <span class="meta">(attempts {s["attempts"]})</span>'
                   f'<pre>{escape(s["text"])}</pre><p class="cit"><strong>Citations:</strong> {escape(cites)}</p>')
        if s.get("note"):
            out.append(f'<p class="meta">{escape(s["note"])}</p>')
        if s.get("used"):
            out.append(f'<details><summary>Facts used ({len(s["used"])})</summary>{_facts_table(s["used"])}</details>')
        out.append("</section>")
    out.append(_regime_chart(model["facts"]))
    out.append(f'<h2>All facts</h2>{_facts_table(model["facts"])}')
    un = model["unavailable"]
    out.append('<h2>What Alterfolio refuses to claim</h2><div class="refuse"><p>Every value below is <strong>Unavailable</strong>, never zero '
               'and never estimated, with the reason it cannot be computed.</p>')
    if un:
        out.append('<div class="wrap"><table><thead><tr><th>Fact or analysis</th><th>Reason</th></tr></thead><tbody>'
                   + "".join(f'<tr><td>{escape(a)}</td><td>{escape(b)}</td></tr>' for a, b in un) + "</tbody></table></div>")
    else:
        out.append("<p>Nothing was unavailable in this run.</p>")
    out.append("</div>" + "<p class=\"meta\">Educational, not financial advice. Numbers come only from deterministic code; the analyst states "
               "them and a number check rejects any it cannot trace.</p></main></body></html>")
    return "".join(out)


def _fact_dict(f) -> dict:
    return {"name": f.name, "value": f.value, "unit": f.unit, "source": f.source}


def offline_model() -> dict:
    import demo_analyst
    d = demo_analyst.collect()
    facts, prov = d["facts"], d["facts"].provenance
    sections = []
    for q, a, cited, used, returned in d["sections"]:
        note = ""
        if returned:
            late = [r for r in returned if r.split("(")[-1].rstrip(")") > d["as_of"].isoformat()]
            note = f"Retriever returned: {', '.join(returned)}. Dated after the as-of day and dropped: {len(late)}."
        sections.append({"q": q, "text": a.text, "verified": a.verified, "attempts": a.attempts, "citations": cited, "note": note,
                         "used": [{"name": f.name, "value": f.value, "unit": f.unit, "source": f.source} for f in used]})
    return {"title": "Alterfolio: skill or luck, with no hindsight",
            "subtitle": "Offline demo on synthetic data (invented symbols and ISINs).",
            "meta": [f"As-of day {d['as_of']}; injected clock {d['clock']:%Y-%m-%d %H:%M}Z; no model (template drafting); no network.",
                     f"{d['imported']} tradebook rows imported, 2 dated after the as-of day and ignored; trades used: {prov['user_trade_count']}.",
                     f"Seeds: {prov['seeds']}. Universe: 12 synthetic listings; corporate-action coverage declared for the fixture only."],
            "sections": sections, "facts": [f.to_dict() for f in facts.facts], "unavailable": [list(u) for u in facts.unavailable]}


def real_model(paths: list[Path]) -> dict:
    import demo_real
    from app.providers.market.yahoo import YahooProvider
    from app.services.analysis_toml import load_aliases  # noqa: F401  (aliases are applied inside demo_real.run)
    from bar_cache import CachingBars
    now = datetime.now(timezone.utc)
    as_of = (now + timedelta(hours=5, minutes=30)).date() - timedelta(days=1)
    cache = CachingBars(YahooProvider(timeout_seconds=10, total_budget_seconds=60), BACKEND / ".cache")
    scratch = DOCS / "reports" / f"demo-real-{date.today().isoformat()}.md"
    s = demo_real.run([(p.name, p.read_bytes()) for p in paths], cache, as_of, now, scratch)
    return model_from_run(s, as_of)


def model_from_run(s: dict, as_of: date) -> dict:
    prov = s["provenance"]
    sections = [{"q": q, "text": a.text, "verified": a.verified, "attempts": a.attempts,
                 "citations": [f"{c.kind}:{c.ref}" for c in a.citations], "note": "", "used": []} for q, a in s["answers"]]
    return {"title": "Alterfolio: your trades, skill or luck", "subtitle": "Real-data run (private). Do not share or commit.",
            "meta": [f"As-of day {as_of}; rows imported {s['imported']}, duplicates {s['duplicates']}, rejected {s['rejected']}.",
                     f"Trades used: {prov['user_trade_count']}; trips analysed {prov['trips_total'] - sum(e[3] for e in prov['excluded_listings'])} of {prov['trips_total']}.",
                     "Excluded: " + ("; ".join(f"{a}.{b} ({c})" for a, b, c, _ in prov["excluded_listings"]) or "none"),
                     prov.get("universe_note", ""), prov.get("price_proxy_note", "")],
            "sections": sections, "facts": s["facts"], "unavailable": s["unavailable"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", type=Path, nargs="+", metavar="TRADEBOOK")
    args = ap.parse_args(argv)
    if args.real:
        out = DOCS / "reports" / f"demo-real-{date.today().isoformat()}.html"  # matches the docs/reports/demo-real-* ignore rule
        html = render(real_model(args.real))
    else:
        out = DOCS / "demo" / "alterfolio-demo.html"
        html = render(offline_model())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
