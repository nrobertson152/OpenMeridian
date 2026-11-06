"""Command line: open a company file, or check an install without a window."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

from . import APP_NAME, VERSION


def _say(text=""):
    if sys.stdout is not None:
        print(text)


def self_test(report: str) -> int:
    from . import planning, sample
    lines, ok = [], True

    def note(cond, text):
        nonlocal ok
        ok = ok and bool(cond)
        lines.append(("ok   " if cond else "FAIL ") + text)
    try:
        with tempfile.TemporaryDirectory() as d:
            c = sample.build(os.path.join(d, "t.meridian"))
            note(c.summary()["stock_value"] > 0, "sample company built, with stock value")
            note(planning.plan(c), "planning suggests orders")
            c.backup(os.path.join(d, "b.meridian"))
            note(os.path.exists(os.path.join(d, "b.meridian")), "backup written")
            c.close()
    except Exception as e:  # noqa: BLE001 - this command reports every failure instead of raising
        note(False, f"{type(e).__name__}: {e}")
    lines.append(f"self-test {'PASSED' if ok else 'FAILED'} ({APP_NAME} {VERSION})")
    text = "\n".join(lines)
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    _say(text)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openmeridian", description="Lightweight ERP for small engineering businesses")
    ap.add_argument("file", nargs="?", help=".meridian company file to open")
    ap.add_argument("--version", "-V", action="store_true", help="show the version")
    ap.add_argument("--self-test", nargs="?", const="", metavar="REPORT", help="check this install works")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        _say(f"{APP_NAME} {VERSION}")
        return 0
    if args.self_test is not None:
        return self_test(args.self_test)
    try:
        import PySide6  # noqa: F401
    except ImportError:
        if sys.stderr is not None:
            print("OpenMeridian's window needs PySide6: pip install \"openmeridian[gui]\"", file=sys.stderr)
        return 3
    from .gui.app import main as gui_main
    return gui_main(args.file)
