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
