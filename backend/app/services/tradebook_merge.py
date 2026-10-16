"""Merge several Zerodha tradebook files into ONE canonical file before a single import.

Why: the importer rejects a sell whose buy is not yet in the ledger (oversell rule), so importing file A then file B can
reject rows that B-then-A accepts. One import over the union is independent of the order of the files: rows are
sorted canonically and cross-file repeats become ordinary in-file duplicates. Pure text/CSV; no database.
"""

import csv
import io


def _norm(header: list[str]) -> list[str]:
    return [h.strip().lower() for h in header]


def merge_tradebooks(contents: list[bytes]) -> bytes:
    """Union of the data rows of all files (identical headers required), sorted by (date, time, exchange, trade_id, row text)."""
    if not contents:
        raise ValueError("no tradebook to merge")
    header: list[str] | None = None
    rows: list[list[str]] = []
    for content in contents:
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
        head = next(reader, None)
        if head is None:
            continue
        if header is None:
            header = head
        elif _norm(head) != _norm(header):
            raise ValueError("tradebook files have different headers and cannot be merged")
        rows.extend(r for r in reader if any(cell.strip() for cell in r))
    if header is None:
        raise ValueError("every tradebook file is empty")
    names = _norm(header)
    idx = {n: names.index(n) for n in ("trade_date", "order_execution_time", "exchange", "trade_id") if n in names}

    def key(row: list[str]):
        return tuple(row[idx[n]] if n in idx and idx[n] < len(row) else "" for n in ("trade_date", "order_execution_time", "exchange", "trade_id")) + (",".join(row),)

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(sorted(rows, key=key))
    return out.getvalue().encode("utf-8")
