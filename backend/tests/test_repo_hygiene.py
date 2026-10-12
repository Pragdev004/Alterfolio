"""Machine-local state must never reach a commit (global rule: no credentials, caches, machine-specific state)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IN_GIT_CHECKOUT = shutil.which("git") is not None and (ROOT / ".git").exists()

needs_git = pytest.mark.skipif(not IN_GIT_CHECKOUT, reason="not a git checkout")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


@needs_git
@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.local.json",
        ".claude/anything.local.json",
        "CLAUDE.local.md",
        ".env",
        "backend/.env.test",
    ],
)
def test_machine_local_files_are_gitignored(path):
    assert _git("check-ignore", "-q", path).returncode == 0, f"{path} is not ignored"


@needs_git
@pytest.mark.skipif(not (ROOT / ".claude" / "settings.local.json").exists(), reason="no local settings file")
def test_add_all_would_not_stage_the_local_settings_file():
    dry_run = _git("add", "--dry-run", "--all")
    assert dry_run.returncode == 0
    assert "settings.local.json" not in dry_run.stdout


@needs_git
def test_local_settings_file_is_not_tracked():
    tracked = _git("ls-files", ".claude/settings.local.json").stdout.strip()
    assert tracked == ""


# ---- tradebook CSVs: only the synthetic fixture may live in the repository ------------------------------------------

FIXTURE = "backend/tests/fixtures/tradebook_synthetic.csv"
ZERODHA_HEADER = "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,"


def _candidate_files() -> list[str]:
    """Tracked files plus untracked files a plain `git add --all` would stage (ignored files are excluded)."""
    out = _git("ls-files", "--cached", "--others", "--exclude-standard")
    assert out.returncode == 0
    return [line for line in out.stdout.splitlines() if line]


@needs_git
def test_no_tradebook_csv_is_tracked_or_stageable_except_the_synthetic_fixture():
    offenders = []
    for rel in _candidate_files():
        path = ROOT / rel
        if not path.is_file():
            continue
        looks_like_csv = rel.lower().endswith((".csv", ".tsv", ".xlsx", ".xls"))
        with path.open("rb") as handle:
            first_line = handle.readline(512).decode("utf-8", "replace").lstrip("﻿").strip().lower()
        if (looks_like_csv or first_line.startswith(ZERODHA_HEADER)) and rel != FIXTURE:
            offenders.append(rel)
    assert offenders == [], f"tradebook-like files must stay outside the repository: {offenders}"


def test_the_fixture_contains_only_obviously_synthetic_values():
    rows = (ROOT / FIXTURE).read_text(encoding="utf-8").splitlines()[1:]
    assert rows, "fixture has no data rows"
    for row in rows:
        cells = row.split(",")
        assert cells[0].endswith("CO"), row  # fictional symbols
        assert cells[1].startswith("ZZ0"), row  # not a valid country prefix; cannot be a real ISIN
        assert cells[2].startswith("2020-"), row
        assert 900000 <= int(cells[10]) < 1000000, row  # fictional trade ids
        assert cells[11].startswith("100000000000"), row  # fictional order ids
