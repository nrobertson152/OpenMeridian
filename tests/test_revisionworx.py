"""Against the real RevisionWorx when it can be imported: real workspace, real revisions, real BOM reader."""
import subprocess

import pytest
from conftest import CSV, M, Q, release

from openmeridian import revisionworx as rw

def test_not_a_workspace_is_a_clear_message(tmp_path):
    with pytest.raises(rw.RevisionWorxError, match="not a RevisionWorx workspace"):
        rw.Client(str(tmp_path), cli=["whatever"]).documents()


def test_missing_program_is_a_clear_message(tmp_path):
    (tmp_path / ".revisionworx").mkdir()
    c = rw.Client(str(tmp_path), cli=None)
    c.cmd = None
    assert not c.available
    with pytest.raises(rw.RevisionWorxError, match="Settings"):
        c.documents()


def test_stamp_without_a_released_revision_says_so():
    doc = rw.Document("d", "N", "T", "f", "t", "A", "wip", "", "")
    s = rw.build_stamp(rw.DocumentDetail(doc, "", "unchanged"))
    assert s["rw_revision"] == "" and "no released revision" in s["rw_note"]
    assert "No controlled document" in rw.build_stamp(None)["rw_note"]


def test_documents_and_detail(workspace):
    c = rw.Client(workspace.path)
    docs = c.documents()
    assert [d.number for d in docs] == ["BOM-1"] and docs[0].latest_label
    det = c.detail(workspace.doc)
    assert det.released is None and "Nothing released" in det.state_sentence() and det.document.latest_state == "wip"


def test_unreleased_bom_is_refused_unless_asked(workspace):
    c = rw.Client(workspace.path)
    with pytest.raises(rw.RevisionWorxError, match="no released revision"):
        c.read_bom(workspace.doc)
    b = c.read_bom(workspace.doc, allow_unreleased=True)
    assert b["root"] == "HPU-SKID" and b["source"]["released"] is False


def test_released_bom_imports_with_its_revision_and_keeps_stock_and_costs(workspace, company):
    w = workspace
    release(w, w.rev)
    c = rw.Client(w.path)
    det = c.detail(w.doc)
    assert det.released is not None
    bom = c.read_bom(w.doc)
    assert bom["source"]["revision"] == w.rev and bom["source"]["released"] is True
    existing = company.add_item("MOTOR", "Our motor", cost=M("99"), price=M("150"))
    company.adjust_stock(existing, Q("3"), "opening")
    res = company.import_bom(bom["root"], bom["parts"], bom["lines"], bom["source"])
    assert sorted(res["created"]) == ["FRAME", "HPU-SKID"] and res["lines"] == 2
    root = company.item_by_number("HPU-SKID")
    assert root["kind"] == "make" and root["bom_rw_revision"] == w.rev and root["bom_rw_label"] == det.released.label
    lines = {l["number"]: l for l in company.bom(root["id"])}
    assert lines["MOTOR"]["qty"] == Q("2") and lines["FRAME"]["qty"] == Q("1")
    motor = company.item(existing)
    assert motor["cost"] == M("99") and motor["price"] == M("150") and motor["on_hand"] == Q("3") and motor["description"] == "Our motor"
    # importing replaces, never duplicates
    company.import_bom(bom["root"], bom["parts"], bom["lines"], bom["source"])
    assert len(company.bom(root["id"])) == 2


def test_new_release_shows_as_drift_and_stamp_records_rev(workspace, company):
    w = workspace
    release(w, w.rev)
    client = rw.Client(w.path)
    bom = client.read_bom(w.doc)
    company.import_bom(bom["root"], bom["parts"], bom["lines"], bom["source"])
    root = company.item_by_number("HPU-SKID")
    company.update_item(root["id"], rw_document=w.doc, rw_number="BOM-1")
    wo = company.create_work_order(root["id"], Q("1"))
    stamp = rw.build_stamp(client.detail(w.doc))
    company.release_work_order(wo, **stamp)
    first_label = company.work_order(wo)["build_rw_label"]
    assert first_label and rw.find_drift(company, client) == []
    # engineering issues and releases a new revision
    w.run("doc", "checkout", w.doc)
    w.file.write_text(CSV.replace("HPU-SKID,2,MOTOR,,2,", "HPU-SKID,2,MOTOR,,3,"), encoding="utf-8")
    new = w.run("doc", "checkin", w.doc, "-m", "second")
    release(w, new["id"])
    drift = rw.find_drift(company, client)
    pages = sorted(d.page for d in drift)
    assert pages == ["items", "production"]
    assert any(company.work_order(wo)["number"] in d.text and first_label in d.text for d in drift)
    # the old revision's quantity stays until someone imports the new one on purpose
    assert company.bom(root["id"])[1]["qty"] == Q("2")
    bom2 = client.read_bom(w.doc)
    company.import_bom(bom2["root"], bom2["parts"], bom2["lines"], bom2["source"])
    assert {l["number"]: l["qty"] for l in company.bom(root["id"])}["MOTOR"] == Q("3")


def test_open_changes_are_read(workspace):
    w = workspace
    client = rw.Client(w.path)
    assert client.changes() == []
    subprocess.run([*client.cmd, "-w", w.path, "change", "new-request", "Bigger motor", "--reason", "More power"], capture_output=True, check=True)
    rows = client.changes()
    assert len(rows) == 1 and rows[0].title == "Bigger motor" and rows[0].number and rows[0].status == "draft" and rows[0].kind == "ecr"
