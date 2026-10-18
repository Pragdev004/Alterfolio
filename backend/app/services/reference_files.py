"""Feature 014: offline reference-data files with provenance. Stdlib only; no network, no clock.

Every loader returns its data plus a `FileProvenance` {file name, SHA-256, download date, source label}. Columns are found
by header name (case-insensitive); a missing required column fails loudly with the file name and the columns found.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_DATE_SUFFIX = re.compile(r"(\d{4}-\d{2}-\d{2})\.csv$", re.IGNORECASE)


class ReferenceDataError(ValueError):
    """A reference file is unreadable, lacks a required column, or holds a bad value."""


@dataclass(frozen=True)
class FileProvenance:
    file_name: str
    sha256: str
    download_date: date
    source_label: str

    def to_dict(self) -> dict:
        return {"file_name": self.file_name, "sha256": self.sha256, "download_date": self.download_date.isoformat(),
                "source_label": self.source_label}


def read_reference_csv(path: Path, required: tuple[str, ...], source_label: str) -> tuple[list[dict[str, str]], FileProvenance]:
    """Rows keyed by the REQUIRED columns' canonical names (spelled as in `required`), plus the file's provenance."""
    path = Path(path)
    raw = path.read_bytes()
    match = _DATE_SUFFIX.search(path.name)
    if not match:
        raise ReferenceDataError(f"{path.name}: the file name must end with its download date (YYYY-MM-DD.csv)")
    try:
        download = date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise ReferenceDataError(f"{path.name}: bad download date in the file name") from exc
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    header = next(reader, None)
    if not header:
        raise ReferenceDataError(f"{path.name}: the file is empty; columns found: none")
    index = {h.strip().lower(): i for i, h in enumerate(header)}
    missing = [c for c in required if c.lower() not in index]
    if missing:
        raise ReferenceDataError(f"{path.name}: missing required column(s) {missing}; columns found: {[h.strip() for h in header]}")
    rows = []
    for n, rec in enumerate(reader, 2):
        if not any(cell.strip() for cell in rec):
            continue
        if len(rec) <= max(index[c.lower()] for c in required):
            raise ReferenceDataError(f"{path.name}: line {n} is too short")
        rows.append({c: rec[index[c.lower()]].strip() for c in required})
    return rows, FileProvenance(path.name, hashlib.sha256(raw).hexdigest(), download, source_label)
