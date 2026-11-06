"""CSV for spreadsheets: a text cell can't turn into a formula when it's opened."""
from __future__ import annotations

import csv
import io


def _safe(cell) -> str:
    s = str(cell)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(s) else s


def _is_number(s) -> bool:
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def to_csv(headers, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([_safe(h) for h in headers])
    for r in rows:
        w.writerow([_safe(c) for c in r])
    return buf.getvalue()
