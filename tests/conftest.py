import json
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OPENMERIDIAN_CONFIG_DIR"] = tempfile.mkdtemp(prefix="openmeridian-test-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openmeridian import revisionworx as rw  # noqa: E402
from openmeridian.company import Company  # noqa: E402
from openmeridian.values import parse_money as M  # noqa: E402
from openmeridian.values import parse_qty as Q  # noqa: E402


@pytest.fixture
def company(tmp_path):
    c = Company.create(str(tmp_path / "t.meridian"), "Test Co")
    yield c
    c.close()


@pytest.fixture
def setup(company):
    """A supplier, a customer, parts in stock and a made item with a BOM."""
    c = company
    sup = c.add_contact("supplier", "Supplier")
    cus = c.add_contact("customer", "Customer", terms_days=30)
    a = c.add_item("A", "Part A", "buy", cost=M("10"), price=M("20"), supplier_id=sup)
    b = c.add_item("B", "Part B", "buy", cost=M("5"), supplier_id=sup)
    x = c.add_item("X", "Assembly", "make", price=M("100"))
    c.set_bom_line(x, a, Q("2"))
    c.set_bom_line(x, b, Q("1"))
    po = c.create_purchase_order(sup)
    c.add_purchase_line(po, a, Q("10"), M("10"))
    c.add_purchase_line(po, b, Q("10"), M("5"))
    c.place_purchase_order(po)
    c.receive_purchase_order(po)
    return type("S", (), dict(c=c, sup=sup, cus=cus, a=a, b=b, x=x))


CSV = """parent_number,find_number,child_number,child_revision,quantity,unit,description,part_unit
,,HPU-SKID,A,,,Skid-mounted HPU,EA
,,FRAME,A,,,Frame,EA
,,MOTOR,,,,Motor,EA
HPU-SKID,1,FRAME,A,1,EA,,
HPU-SKID,2,MOTOR,,2,EA,,
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    cmd = rw.find_cli()
    if cmd is None:
        pytest.skip("RevisionWorx is not installed here")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    ws = tmp_path / "eng"
    ws.mkdir()
    (ws / "Projects").mkdir()

    def run(*a):
        r = subprocess.run([*cmd, "--json", "-w", str(ws), *a], capture_output=True, text=True, check=True)
        return json.loads(r.stdout)
    subprocess.run([*cmd, "init", str(ws), "--name", "T"], capture_output=True, check=True)
    run("root", "add", "Projects", str(ws / "Projects"))
    prj = run("project", "new", "--name", "Pump", "--number", "J1")
    folder = next((ws / "Projects").rglob("J1 Pump"))
    f = folder / "skid.csv"
    f.write_text(CSV, encoding="utf-8")
    doc = run("doc", "register", prj["id"], str(f), "--number", "BOM-1", "--title", "Skid BOM", "--scheme", "alpha", "-m", "first")
    return type("W", (), dict(path=str(ws), run=staticmethod(run), doc=doc["document"]["id"], rev=doc["revision"]["id"], folder=folder, file=f))


def release(w, rev):
    for state in ("in_review", "approved", "released"):
        w.run("rev", "transition", rev, state)
