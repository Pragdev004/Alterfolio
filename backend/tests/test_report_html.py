"""Self-contained HTML report: no external references, the refusals section, and the private output path rule."""

import fnmatch
import sys
from datetime import date
from pathlib import Path

from analysis_helpers import D_ASOF, NOW, FakeBars

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _assert_self_contained(html: str):
    low = html.lower()
    for forbidden in ("http://", "https://", "<script", "<link", "@import", "url(", "src="):
        assert forbidden not in low, forbidden


def test_offline_report_is_self_contained_and_lists_refusals():
    import report_html
    html = report_html.render(report_html.offline_model())
    _assert_self_contained(html)
    assert "<style>" in html and "<svg" in html
    assert html.count('<section class="q">') == 4 and "verified: yes" in html
    assert "What Alterfolio refuses to claim" in html and "Citations:" in html
    assert "<title>Alterfolio" in html


def test_committed_offline_report_matches_a_fresh_render():
    import report_html
    committed = (ROOT.parent / "docs" / "demo" / "alterfolio-demo.html").read_text(encoding="utf-8")
    assert committed == report_html.render(report_html.offline_model())  # deterministic; rebuild with scripts/report_html.py


def test_real_model_renders_from_a_run_and_lands_under_the_ignore_rule(tmp_path):
    import demo_real
    import report_html
    sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
    from build_demo_fixture import tradebook_bytes
    s = demo_real.run([("a.csv", tradebook_bytes())], FakeBars(), D_ASOF, NOW, tmp_path / "r.md", luck_portfolios=20, replicates=200)
    html = report_html.render(report_html.model_from_run(s, D_ASOF))
    _assert_self_contained(html)
    assert "What Alterfolio refuses to claim" in html and html.count('<section class="q">') == 4
    # the real report path must match the committed ignore rule
    ignore = (ROOT.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    rel = f"docs/reports/demo-real-{date.today().isoformat()}.html"
    assert any(fnmatch.fnmatch(rel, line.strip()) for line in ignore if line.strip() and not line.startswith("#"))
