"""The IST offset (UTC+5:30) is defined once, in app/domain/timezones.py; nothing else under app/ or scripts/ redefines it."""

import re
from datetime import timedelta
from pathlib import Path

from app.domain.timezones import IST, IST_OFFSET

ROOT = Path(__file__).resolve().parents[1]
_DEFINITION = re.compile(r"timedelta\(\s*hours\s*=\s*5\s*,\s*minutes\s*=\s*30\s*\)|timedelta\(\s*minutes\s*=\s*330\s*\)|\b19800\b")


def test_ist_offset_value():
    assert IST_OFFSET == timedelta(hours=5, minutes=30) and IST.utcoffset(None) == IST_OFFSET


def test_no_other_module_defines_the_ist_offset():
    offenders = []
    for folder in ("app", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name == "timezones.py" and path.parent.name == "domain":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _DEFINITION.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert offenders == []
