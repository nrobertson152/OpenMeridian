"""Units a work order builds, by serial, and registering them in RevisionWorx: the one thing OpenMeridian writes there
(docs/COMPANY_FILE.md, format 2). Format-1 files are upgraded when opened, with a verified copy kept first."""
import hashlib
import os
import shutil
import sqlite3

import pytest
from conftest import FakeRevisionWorx, Q, release

from openmeridian import db
from openmeridian import revisionworx as rw
from openmeridian.company import MISSING_NOTE, Company, ERPError, today

FORMAT1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "format1.meridian")


def _columns(path):
    con = sqlite3.connect(path)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {n: [r[1] for r in con.execute(f"PRAGMA table_info({n})")] for n in names}
    finally:
        con.close()


def _rows(path, table, columns):
    con = sqlite3.connect(path)
    try:
        return con.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid").fetchall()  # noqa: S608 - names from the file
    finally:
        con.close()


def _schema(path):
    con = sqlite3.connect(path)
    try:
        return sorted(con.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall())
    finally:
        con.close()


@pytest.fixture
def old_file(tmp_path):
    """A company file made by the released OpenMeridian (format 1): the sample company."""
    path = tmp_path / "Acme.meridian"
    shutil.copy(FORMAT1, path)
    return path


# ---------------------------------------------------------------- format 1 to 2
def test_the_fixture_is_a_format_1_file():
    assert _columns(FORMAT1)["items"][-1] != "tracking" and "wo_units" not in _columns(FORMAT1)
    con = sqlite3.connect(FORMAT1)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    con.close()


def test_a_format_1_file_is_upgraded_with_a_verified_copy_of_it_kept_first(old_file, tmp_path):
    before = _columns(old_file)
    original = {t: _rows(old_file, t, cols) for t, cols in before.items()}
    c = Company.open(str(old_file))
    try:
        assert c.conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 2
        kept = tmp_path / "Acme (format 1 backup).meridian"
        con = sqlite3.connect(kept)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        con.close()
        assert {t: _rows(kept, t, cols) for t, cols in _columns(kept).items()} == original, "the copy is the file as it was"
        # every row the file had is still there, as it was; the upgrade adds a line to the log and the company's id
        for table, cols in before.items():
            now = _rows(old_file, table, cols)
            if table == "audit":
                assert now[:-1] == original[table]
                assert now[-1][3] == "format.upgrade" and now[-1][4] == (
                    "format 1 to 2; the file as it was is kept as Acme (format 1 backup).meridian")
            elif table == "settings":
                assert [r for r in now if r[0] != "company_id"] == original[table]
            else:
                assert now == original[table], table
        assert len(c.setting("company_id")) == 32 and int(c.setting("company_id"), 16) >= 0
        assert {i["tracking"] for i in c.items()} == {"none"}
        assert c.summary()["stock_value"] > 0 and c.units_built(c.work_orders()[0]["id"]) == []
    finally:
        c.close()
    # an upgraded file is the same as a new one, and opening it again changes nothing
    new = tmp_path / "new.meridian"
    Company.create(str(new), "New").close()
    assert _schema(old_file) == _schema(new)
    Company.open(str(old_file)).close()
    assert sorted(p.name for p in tmp_path.glob("*backup*")) == ["Acme (format 1 backup).meridian"]


def test_an_upgrade_that_cant_keep_its_copy_changes_nothing(old_file, monkeypatch):
    original = old_file.read_bytes()

    def no_room(conn, dest):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(db, "backup", no_room)
    with pytest.raises(db.CompanyFileError, match="couldn't be kept beside it first .*No space.*Nothing was changed"):
        Company.open(str(old_file))
    assert old_file.read_bytes() == original


def test_an_upgrade_step_that_fails_leaves_the_file_as_it_was(old_file, monkeypatch):
    original = old_file.read_bytes()
    monkeypatch.setitem(db.MIGRATIONS, 2, db.MIGRATIONS[2] + "\nINSERT INTO no_such_table VALUES (1);\n")
    with pytest.raises(db.CompanyFileError, match="couldn't be upgraded, so it was left as it was"):
        Company.open(str(old_file))
    assert old_file.read_bytes() == original
    assert "tracking" not in _columns(old_file)["items"] and "wo_units" not in _columns(old_file)


def test_a_file_another_openmeridian_upgraded_meanwhile_is_left_alone(old_file, tmp_path):
    conn = db._connect(str(old_file))            # this one saw format 1...
    Company.open(str(old_file)).close()          # ...and another upgraded it first
    db._upgrade(conn, str(old_file))
    conn.close()
    assert sorted(p.name for p in tmp_path.glob("*backup*")) == ["Acme (format 1 backup).meridian"]
    assert [r[0] for r in _rows(old_file, "audit", ["action"])].count("format.upgrade") == 1


def test_backup_names_never_take_an_existing_file(tmp_path):
    p = str(tmp_path / "Acme.meridian")
    first = db.upgrade_backup_name(p, 1)
    open(first, "w").close()
    assert db.upgrade_backup_name(p, 1) == str(tmp_path / "Acme (format 1 backup 2).meridian")


# ---------------------------------------------------------------- serial numbers
def _serial_wo(s, qty="3", **stamp):
    s.c.update_item(s.x, tracking="serial")
    wo = s.c.create_work_order(s.x, Q(qty))
    s.c.release_work_order(wo, **stamp)
    return wo


def test_serial_numbers_are_for_items_made_and_stock_must_be_zero_to_change(setup):
    s, c = setup, setup.c
    with pytest.raises(ERPError, match="items you make"):
        c.update_item(s.a, tracking="serial")
    with pytest.raises(ERPError, match="by lot isn't available"):
        c.update_item(s.x, tracking="lot")
    with pytest.raises(ERPError, match="items you make"):
        c.add_item("NEW", "Bought", "buy", tracking="serial")
    c.update_item(s.x, tracking="serial")
    assert c.item(s.x)["tracking"] == "serial"
    with pytest.raises(ERPError, match="items you make"):
        c.update_item(s.x, kind="buy")
    c.adjust_stock(s.x, Q("1"), "found one")
    with pytest.raises(ERPError, match="has to be zero"):
        c.update_item(s.x, tracking="none")
    assert c.item(s.x)["tracking"] == "serial"


def test_completing_needs_one_new_serial_per_unit_made(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s)
    for serials, why in ((["NH-1"], "one serial number for each of the 3.*1 given"),
                         (["NH-1", "NH-2", "nh-1"], "nh-1 is given twice"),
                         (["NH-1", "NH-2", "NH\x07"], "control character"),
                         (["NH-1", "NH-2", "N" * 101], "longer than a serial number can be")):
        with pytest.raises(ERPError, match=why):
            c.complete_work_order(wo, Q("3"), serials)
    with pytest.raises(ERPError, match="whole units"):
        c.complete_work_order(wo, Q("1.5"), ["NH-1"])
    assert c.units_built(wo) == [] and c.item(s.x)["on_hand"] == 0, "a refused completion changes nothing"

    c.complete_work_order(wo, Q("2"), ["  NH-26-0001 ", "", "NH-26-0002"])
    units = c.units_built(wo)
    assert [(u["serial"], u["batch"], u["made"], u["model"], u["name"], u["rw_unit"]) for u in units] == [
        ("NH-26-0001", 1, today(), "X", "Assembly", ""), ("NH-26-0002", 1, today(), "X", "Assembly", "")]
    assert c.item(s.x)["on_hand"] == Q("2")
    moves = c.conn.execute("SELECT qty, serial FROM stock_moves WHERE item_id = ? AND kind = 'produce' ORDER BY id",
                           (s.x,)).fetchall()
    assert [tuple(m) for m in moves] == [(Q("1"), "NH-26-0001"), (Q("1"), "NH-26-0002")]
    assert "NH-26-0001, NH-26-0002" in c.conn.execute("SELECT detail FROM audit WHERE action = 'wo.complete'").fetchone()[0]

    # a serial names one unit, whichever item it is
    y = c.add_item("Y", "Other", "make", tracking="serial")
    c.set_bom_line(y, s.b, Q("1"))
    wo2 = c.create_work_order(y, Q("1"))
    c.release_work_order(wo2)
    with pytest.raises(ERPError, match="NH-26-0001 was already given, to the X made on WO-"):
        c.complete_work_order(wo2, Q("1"), ["nh-26-0001"])
    c.complete_work_order(wo, Q("1"), ["NH-26-0003"])
    assert [u["batch"] for u in c.units_built(wo)] == [1, 1, 2] and c.work_order(wo)["status"] == "complete"
    z = c.add_item("Z", "Not serialised", "make")
    c.set_bom_line(z, s.b, Q("1"))
    wo3 = c.create_work_order(z, Q("1"))
    c.release_work_order(wo3)
    with pytest.raises(ERPError, match="Z isn't made with serial numbers"):
        c.complete_work_order(wo3, Q("1"), ["S-1"])


def test_serials_are_stored_composed_so_they_match_revisionworx(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s, "1")
    c.complete_work_order(wo, Q("1"), ["Café-1"])          # e + combining accent, as some keyboards type it
    assert c.units_built(wo)[0]["serial"] == "Café-1"


def test_the_file_keeps_each_unit_built_as_it_was_made(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s, "1")
    c.complete_work_order(wo, Q("1"), ["NH-9"])
    uid = c.units_built(wo)[0]["id"]
    for sql in ("UPDATE wo_units SET serial = 'NH-10' WHERE id = ?", "UPDATE wo_units SET model = 'Z' WHERE id = ?",
                "UPDATE wo_units SET made = '2020-01-01' WHERE id = ?", "UPDATE wo_units SET work_order_id = 1 WHERE id = ?",
                "DELETE FROM wo_units WHERE id = ?"):
        with pytest.raises(sqlite3.IntegrityError):
            c.conn.execute(sql, (uid,))
    c.conn.execute("UPDATE wo_units SET rw_unit = ? WHERE id = ?", ("unt_" + "a" * 32, uid))
    for other in ("", "unt_" + "b" * 32):
        with pytest.raises(sqlite3.IntegrityError, match="keeps its id"):
            c.conn.execute("UPDATE wo_units SET rw_unit = ? WHERE id = ?", (other, uid))
    with pytest.raises(sqlite3.IntegrityError):
        c.conn.execute("INSERT INTO wo_units (work_order_id, item_id, serial, batch, made, model, name) "
                       "VALUES (?, ?, 'nh-9', 2, '2026-01-01', 'X', '')", (wo, s.x))


# ---------------------------------------------------------------- registering in RevisionWorx
DOC, REV = "doc_" + "1" * 32, "rev_" + "2" * 32


def test_units_are_registered_once_with_what_they_were_built_as(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s, rw_document=DOC, rw_revision=REV, rw_label="B")
    number = c.work_order(wo)["number"]
    c.complete_work_order(wo, Q("2"), ["NH-1", "NH-2"])
    c.update_item(s.x, number="X-2", description="Assembly, renamed after they were made")
    fake = FakeRevisionWorx()
    assert c.register_units(wo, fake) == {"registered": ["NH-1", "NH-2"], "refused": []}
    assert fake.calls == [(c.register_txid(wo, 1), ["NH-1", "NH-2"], {
        "model": "X", "name": "Assembly", "built": today(), "document": f"{DOC}@{REV}", "evidence": f"work-order:{number}"})]
    assert [u["rw_unit"] for u in c.units_built(wo)] == ["unt_%032x" % 0, "unt_%032x" % 1]
    assert c.register_units(wo, fake) == {"registered": [], "refused": []} and len(fake.calls) == 1, "nothing left to send"
    c.complete_work_order(wo, Q("1"), ["NH-3"])
    assert c.register_units(wo, fake) == {"registered": ["NH-3"], "refused": []}
    assert fake.calls[1][:2] == (c.register_txid(wo, 2), ["NH-3"]), "each completion is its own registration"
    log = [r[0] for r in c.conn.execute("SELECT detail FROM audit WHERE action = 'wo.register' ORDER BY id")]
    assert log == [f"{number}: NH-1, NH-2 in RevisionWorx", f"{number}: NH-3 in RevisionWorx"]


def test_a_work_order_released_without_a_revision_registers_no_drawing(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s, "1", rw_note="Released while RevisionWorx couldn't be checked")
    c.complete_work_order(wo, Q("1"), ["NH-1"])
    fake = FakeRevisionWorx()
    c.register_units(wo, fake)
    assert fake.calls[0][2]["document"] == ""


def test_a_refusal_stays_on_the_units_and_the_retry_sends_the_same_request(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s, "2")
    c.complete_work_order(wo, Q("2"), ["NH-1", "NH-2"])
    fake = FakeRevisionWorx()
    fake.refuse = ("serial NH-1 already belongs to NH-1 (unt_...)", "duplicate")
    out = c.register_units(wo, fake)
    assert out == {"registered": [], "refused": [(["NH-1", "NH-2"], "serial NH-1 already belongs to NH-1 (unt_...)")]}
    assert [(u["rw_unit"], u["rw_note"]) for u in c.units_built(wo)] == [("", "serial NH-1 already belongs to NH-1 (unt_...)")] * 2
    fake.refuse = None
    assert c.register_units(wo, fake) == {"registered": ["NH-1", "NH-2"], "refused": []}
    assert fake.calls[0] == fake.calls[1]
    assert all(u["rw_unit"] and not u["rw_note"] for u in c.units_built(wo))


def test_a_txid_revisionworx_already_has_for_other_units_says_what_happened(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s, "1")
    c.complete_work_order(wo, Q("1"), ["NH-1"])
    fake = FakeRevisionWorx()
    fake.done[c.register_txid(wo, 1)] = ((["NH-OTHER"], {}), [("NH-OTHER", "unt_" + "f" * 32)])  # from another copy of the file
    out = c.register_units(wo, fake)
    assert out["registered"] == [] and "another copy of this company file, or an older backup" in out["refused"][0][1]
    assert c.units_built(wo)[0]["rw_unit"] == ""


def test_a_unit_revisionworx_hasnt_listed_yet_is_picked_up_by_registering_again(setup):
    s, c = setup, setup.c
    wo = _serial_wo(s, "2")
    c.complete_work_order(wo, Q("2"), ["NH-1", "NH-2"])
    fake = FakeRevisionWorx()
    fake.unlisted = {"NH-2"}
    assert c.register_units(wo, fake) == {"registered": ["NH-1"], "refused": [(["NH-2"], MISSING_NOTE)]}
    fake.unlisted = set()
    assert c.register_units(wo, fake) == {"registered": ["NH-2"], "refused": []}
    assert fake.calls[1] == fake.calls[0], "the whole completion again, so RevisionWorx answers it as the same request"


def test_the_register_txid_is_the_same_for_every_attempt_and_its_own_per_completion(setup, tmp_path):
    s, c = setup, setup.c
    wo = _serial_wo(s, "2")
    cid = c.setting("company_id")
    want = hashlib.sha256(f"openmeridian/register/v1\0{cid}\0{c.work_order(wo)['number']}\0{1}".encode()).hexdigest()[:32]
    assert c.register_txid(wo, 1) == want and c.register_txid(wo, 2) != want and len(want) == 32
    other = Company.create(str(tmp_path / "other.meridian"), "Other")
    assert other.setting("company_id") != cid, "another company's work order of the same number is another registration"
    other.close()
    c.conn.execute("DELETE FROM settings WHERE key = 'company_id'")      # a file without one can't be told apart
    with pytest.raises(ERPError, match="no company id"):
        c.register_txid(wo, 1)


# ---------------------------------------------------------------- against the real RevisionWorx
def test_registering_in_the_real_revisionworx(workspace, company):
    w, c = workspace, company
    release(w, w.rev)
    client = rw.Client(w.path)
    x = c.add_item("HPU-75", "Hydraulic power unit", "make", tracking="serial")
    part = c.add_item("MOTOR", "Motor", "buy")
    c.adjust_stock(part, Q("5"), "opening")
    c.set_bom_line(x, part, Q("1"))
    c.update_item(x, rw_document=w.doc, rw_number="BOM-1")
    wo = c.create_work_order(x, Q("2"))
    c.release_work_order(wo, **rw.build_stamp(client.detail(w.doc)))
    number = c.work_order(wo)["number"]
    c.complete_work_order(wo, Q("2"), ["NH-26-0001", "-0002"])
    assert c.register_units(wo, client) == {"registered": ["NH-26-0001", "-0002"], "refused": []}
    ids = [u["rw_unit"] for u in c.units_built(wo)]
    unit = client._link("unit", "NH-26-0001")["unit"]
    assert unit["id"] == ids[0] and unit["status"] == "built" and unit["name"] == "Hydraulic power unit"
    assert unit["model"]["number"] == "HPU-75" and unit["identifiers"][0]["value"] == "NH-26-0001"
    assert [(d["document"]["id"], d["revision"]["id"]) for d in unit["documents"]] == [(w.doc, w.rev)]
    assert client._link("unit", "-0002")["unit"]["id"] == ids[1], "a serial starting with - stays a serial"
    first = unit["history"][0]
    assert {"kind": "work-order", "ref": number, "label": ""} in first["evidence"]

    # asked again (an answer lost on the way, say): the same units, nothing new
    again = client.register_units(c.register_txid(wo, 1), ["NH-26-0001", "-0002"], model="HPU-75",
                                  name="Hydraulic power unit", built=today(), document=f"{w.doc}@{w.rev}",
                                  evidence=f"work-order:{number}")
    assert [uid for _, uid in again] == ids and len(client._link("units")["units"]) == 2
    # the same completion with something else is refused, and RevisionWorx says why
    with pytest.raises(rw.RevisionWorxError) as e:
        client.register_units(c.register_txid(wo, 1), ["NH-26-0001"], model="HPU-75", name="", built=today())
    assert e.value.kind == "txid-used"

    # a serial RevisionWorx already has for another unit: refused there, kept here with RevisionWorx's reason
    client._link("unit-register", "--txid=" + "e" * 32, "--serial=NH-26-0003", "--model=OLD")
    wo2 = c.create_work_order(x, Q("1"))
    c.release_work_order(wo2)
    c.complete_work_order(wo2, Q("1"), ["NH-26-0003"])
    out = c.register_units(wo2, client)
    assert out["registered"] == [] and "NH-26-0003" in out["refused"][0][1]
    assert c.units_built(wo2)[0]["rw_unit"] == "" and "NH-26-0003" in c.units_built(wo2)[0]["rw_note"]
    assert len(client._link("units")["units"]) == 3, "nothing about it changed in RevisionWorx"
