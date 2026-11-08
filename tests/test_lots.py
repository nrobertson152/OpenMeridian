"""Lots (docs/COMPANY_FILE.md, format 3): every move of an item tracked by lot says which lot, the file refuses one that
doesn't or that takes more than a lot has, and a lot can be traced to what it went into and who it went to. Format-2
files are upgraded when opened, with a verified copy kept first."""
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from conftest import FakeRevisionWorx, M, Q

from openmeridian import company as company_module
from openmeridian import db, tracing
from openmeridian.company import Company, ERPError

FORMAT2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "format2.meridian")


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
    """A company file made by OpenMeridian with format 2: the sample company, then an HPU-75 made with serial number
    NH-26-0001 on WO-00004 and registered in RevisionWorx."""
    path = tmp_path / "Northline.meridian"
    shutil.copy(FORMAT2, path)
    return path


@pytest.fixture
def plant(company):
    """Hoses bought in lots, a hose kit made in lots from them and bolts, and a power unit made with serial numbers
    from a kit and bolts."""
    c = company
    sup = c.add_contact("supplier", "Hose Co")
    cus = c.add_contact("customer", "Acme")
    other = c.add_contact("customer", "Bayside")
    hose = c.add_item("HSE", "Hose", "buy", cost=M("5"), tracking="lot")
    bolt = c.add_item("BLT", "Bolt", "buy", cost=M("1"))
    kit = c.add_item("KIT", "Hose kit", "make", price=M("40"), tracking="lot")
    hpu = c.add_item("HPU", "Power unit", "make", price=M("900"), tracking="serial")
    c.set_bom_line(kit, hose, Q("2"))
    c.set_bom_line(kit, bolt, Q("4"))
    c.set_bom_line(hpu, kit, Q("1"))
    c.set_bom_line(hpu, bolt, Q("2"))
    po = c.create_purchase_order(sup)
    hl = c.add_purchase_line(po, hose, Q("10"), M("5"))
    bl = c.add_purchase_line(po, bolt, Q("100"), M("1"))
    c.place_purchase_order(po)
    c.receive_purchase_order(po, {hl: Q("6"), bl: Q("100")}, {hl: "H-2611"})
    c.receive_purchase_order(po, {hl: Q("4")}, {hl: "H-2612"})
    return type("P", (), dict(c=c, sup=sup, cus=cus, other=other, hose=hose, bolt=bolt, kit=kit, hpu=hpu, po=po, hl=hl))


def _released(c, item, qty):
    wo = c.create_work_order(item, Q(qty))
    c.release_work_order(wo)
    return wo


def _moves(c, item):
    return [(m["kind"], m["qty"], m["lot"], m["ref"], m["batch"]) for m in reversed(c.moves(item))]


# ---------------------------------------------------------------- format 2 to 3
def test_the_fixture_is_a_format_2_file():
    con = sqlite3.connect(FORMAT2)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        assert con.execute("SELECT serial, rw_unit FROM wo_units").fetchall() == [("NH-26-0001", "unt_%032x" % 1)]
    finally:
        con.close()
    assert "batch" not in _columns(FORMAT2)["stock_moves"] and "lot" in _columns(FORMAT2)["stock_moves"]


def test_a_format_2_file_is_upgraded_with_a_verified_copy_of_it_kept_first(old_file, tmp_path):
    before = _columns(old_file)
    original = {t: _rows(old_file, t, cols) for t, cols in before.items()}
    txid = None
    c = Company.open(str(old_file))
    try:
        assert c.conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 3
        kept = tmp_path / "Northline (format 2 backup).meridian"
        con = sqlite3.connect(kept)
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        con.close()
        assert {t: _rows(kept, t, cols) for t, cols in _columns(kept).items()} == original, "the copy is the file as it was"
        for table, cols in before.items():
            now = _rows(old_file, table, cols)
            if table == "audit":
                assert now[:-1] == original[table]
                assert now[-1][3] == "format.upgrade" and now[-1][4] == (
                    "format 2 to 3; the file as it was is kept as Northline (format 2 backup).meridian")
            else:
                assert now == original[table], table
        assert {r[0] for r in c.conn.execute("SELECT batch FROM stock_moves")} == {0}, "earlier moves name no completion"
        # the unit made in format 2 is still registered, and its completion keeps its txid there
        wo = c.conn.execute("SELECT id FROM work_orders WHERE number = 'WO-00004'").fetchone()[0]
        assert [(u["serial"], u["batch"], u["rw_unit"]) for u in c.units_built(wo)] == [("NH-26-0001", 1, "unt_%032x" % 1)]
        txid = c.register_txid(wo, 1)
        fake = FakeRevisionWorx()
        assert c.register_units(wo, fake) == {"registered": [], "refused": []} and fake.calls == []
    finally:
        c.close()
    assert len(txid) == 32
    new = tmp_path / "new.meridian"
    Company.create(str(new), "New").close()
    assert _schema(old_file) == _schema(new), "an upgraded file is the same as a new one"
    Company.open(str(old_file)).close()
    assert sorted(p.name for p in tmp_path.glob("*backup*")) == ["Northline (format 2 backup).meridian"]


def test_a_completion_after_the_upgrade_carries_on_the_numbering_of_the_ones_before(old_file):
    c = Company.open(str(old_file))
    try:
        hpu = c.item_by_number("HPU-75")
        wo = c.conn.execute("SELECT id FROM work_orders WHERE number = 'WO-00004'").fetchone()[0]
        for b in c.work_order_components(wo):                  # the sample has used up some of the parts
            if b["on_hand"] < b["needed"]:
                c.adjust_stock(b["child_id"], b["needed"] - b["on_hand"], "found")
        c.complete_work_order(wo, Q("1"), ["NH-26-0002"])
        assert [(u["serial"], u["batch"]) for u in c.units_built(wo)] == [("NH-26-0001", 1), ("NH-26-0002", 2)]
        assert sorted({(m["kind"], m["batch"]) for m in c.moves() if m["ref"] == "WO-00004"}) == [
            ("consume", 0), ("consume", 2), ("produce", 0), ("produce", 2)], "the earlier completion's moves name none"
        assert c.item(hpu["id"])["on_hand"] == Q("2")
    finally:
        c.close()


def test_an_item_marked_lot_outside_openmeridian_in_format_2_goes_back_to_untracked(old_file):
    con = sqlite3.connect(old_file)
    con.execute("UPDATE items SET tracking = 'lot' WHERE number = 'HSE-08'")      # OpenMeridian refused to, in format 2
    had = con.execute("SELECT SUM(m.qty) FROM stock_moves m JOIN items i ON i.id = m.item_id WHERE i.number = 'HSE-08'").fetchone()[0]
    con.commit()
    con.close()
    c = Company.open(str(old_file))
    try:
        hose = c.item_by_number("HSE-08")
        assert hose["tracking"] == "none" and hose["on_hand"] == had == Q("8")
        c.adjust_stock(hose["id"], Q("-1"), "count")             # its stock, which names no lot, can still move
    finally:
        c.close()


def test_an_upgrade_from_format_2_that_fails_leaves_the_file_as_it_was(old_file, monkeypatch):
    original = old_file.read_bytes()
    monkeypatch.setitem(db.MIGRATIONS, 3, db.MIGRATIONS[3] + "\nINSERT INTO no_such_table VALUES (1);\n")
    with pytest.raises(db.CompanyFileError, match="couldn't be upgraded, so it was left as it was"):
        Company.open(str(old_file))
    assert old_file.read_bytes() == original
    assert "batch" not in _columns(old_file)["stock_moves"]


# ---------------------------------------------------------------- the rules, in the program and in the file
def test_bought_and_made_items_can_be_tracked_by_lot_while_none_is_in_stock(setup):
    s, c = setup, setup.c
    c.update_item(s.x, tracking="lot")
    assert c.item(s.x)["tracking"] == "lot"
    new = c.add_item("NEW", "Bought in lots", "buy", tracking="lot")
    assert c.item(new)["tracking"] == "lot"
    with pytest.raises(ERPError, match="has to be zero before it starts or stops being tracked"):
        c.update_item(s.a, tracking="lot")                      # 10 on hand
    with pytest.raises(ERPError, match="by serial number, by lot, or not at all"):
        c.update_item(s.a, tracking="batch")
    with pytest.raises(sqlite3.IntegrityError, match="only while none of it is in stock"):
        c.conn.execute("UPDATE items SET tracking = 'lot' WHERE id = ?", (s.a,))
    assert c.item(s.a)["tracking"] == "none"


def test_the_file_refuses_a_move_that_breaks_the_lot_rules(plant):
    p, c = plant, plant.c
    insert = ("INSERT INTO stock_moves (time, item_id, qty, kind, lot) VALUES ('2026-11-08T09:00:00', ?, ?, 'adjust', ?)")
    with pytest.raises(sqlite3.IntegrityError, match="names its lot"):
        c.conn.execute(insert, (p.hose, Q("1"), ""))
    with pytest.raises(sqlite3.IntegrityError, match="no other move names one"):
        c.conn.execute(insert, (p.bolt, Q("1"), "B-1"))
    with pytest.raises(sqlite3.IntegrityError, match="cannot give more than it has"):
        c.conn.execute(insert, (p.hose, -Q("7"), "H-2611"))
    with pytest.raises(sqlite3.IntegrityError, match="cannot give more than it has"):
        c.conn.execute(insert, (p.hose, -Q("1"), "NO-SUCH-LOT"))
    c.conn.execute(insert, (p.hose, -Q("6"), "H-2611"))       # exactly what it has is fine
    assert c.lot_on_hand(p.hose, "H-2611") == 0


def test_receiving_says_the_lot_and_one_lot_is_one_whatever_its_case(plant):
    p, c = plant, plant.c
    assert [(l["lot"], l["on_hand"]) for l in c.lots(p.hose)] == [("H-2611", Q("6")), ("H-2612", Q("4"))]
    assert c.purchase_order(p.po)["status"] == "received"
    assert "PO-00001: HSE lot H-2612" in [a["detail"] for a in c.activity(5)]
    po = c.create_purchase_order(p.sup)
    line = c.add_purchase_line(po, p.hose, Q("5"))
    bolts = c.add_purchase_line(po, p.bolt, Q("5"))
    c.place_purchase_order(po)
    before = len(c.moves())
    for lots, why in (({}, "say which lot it came in as"), ({line: "  "}, "say which lot it came in as"),
                      ({line: "H\x07"}, "control character"), ({line: "H" * 101}, "longer than a lot can be"),
                      ({line: "H-1", bolts: "B-1"}, "BLT isn't tracked by lot"), ({999: "H-1"}, "isn't on this order")):
        with pytest.raises(ERPError, match=why):
            c.receive_purchase_order(po, None, lots)
    assert len(c.moves()) == before, "a refused receipt receives nothing"
    c.receive_purchase_order(po, {line: Q("5")}, {line: "  h-2611 "})
    assert [(l["lot"], l["on_hand"]) for l in c.lots(p.hose)] == [("H-2611", Q("11")), ("H-2612", Q("4"))]


def test_adjusting_says_which_lot(plant):
    p, c = plant, plant.c
    with pytest.raises(ERPError, match="say which lot is being adjusted"):
        c.adjust_stock(p.hose, Q("-1"), "damaged")
    with pytest.raises(ERPError, match="H-2612 has 4 on hand, so it can't go down by 5"):
        c.adjust_stock(p.hose, -Q("5"), "damaged", lot="H-2612")
    with pytest.raises(ERPError, match="BLT isn't tracked by lot"):
        c.adjust_stock(p.bolt, Q("1"), "found", lot="B-1")
    c.adjust_stock(p.hose, -Q("1"), "damaged", lot="h-2612")
    c.adjust_stock(p.hose, Q("2"), "found on the shelf, labelled", lot="H-0001")
    assert {l["lot"]: l["on_hand"] for l in c.lots(p.hose)} == {"H-2611": Q("6"), "H-2612": Q("3"), "H-0001": Q("2")}
    assert c.activity(1)[0]["detail"] == "HSE 2 lot H-0001: found on the shelf, labelled"


def test_completing_says_which_lots_were_used_and_the_kit_comes_in_as_its_own_lot(plant):
    p, c = plant, plant.c
    wo = _released(c, p.kit, "4")                              # 8 hoses and 16 bolts
    assert c.suggest_lots(p.hose, Q("8")) == [("H-2611", Q("6")), ("H-2612", Q("2"))], "oldest first"
    before = len(c.moves())
    for lots, why in (({}, "say which lots the 8 used came from .0 given"),
                      ({p.hose: [("H-2611", Q("6"))]}, "say which lots the 8 used came from .6 given"),
                      ({p.hose: [("H-2612", Q("8"))]}, "H-2612 has 4 on hand, not 8"),
                      ({p.hose: [("H-9", Q("8"))]}, "has no lot H-9 in stock"),
                      ({p.hose: [("H-2611", Q("6")), ("H-2612", Q("2"))], p.bolt: [("B-1", Q("16"))]}, "BLT isn't tracked by lot"),
                      ({p.hose: [("H-2611", Q("8"))], p.hpu: [("X", Q("1"))]}, "isn't one of KIT's components")):
        with pytest.raises(ERPError, match=why):
            c.complete_work_order(wo, Q("4"), lots=lots)
    assert len(c.moves()) == before and c.work_order(wo)["done"] == 0, "a refused completion changes nothing"

    c.complete_work_order(wo, Q("3"), lots={p.hose: [("h-2611", Q("4")), ("H-2611", Q("2"))]})   # the same lot, twice
    c.complete_work_order(wo, Q("1"), lots={p.hose: [("H-2612", Q("2"))]})
    assert _moves(c, p.kit) == [("produce", Q("3"), "WO-00001", "WO-00001", 1), ("produce", Q("1"), "WO-00001-2", "WO-00001", 2)]
    assert _moves(c, p.hose)[-2:] == [("consume", -Q("6"), "H-2611", "WO-00001", 1), ("consume", -Q("2"), "H-2612", "WO-00001", 2)]
    assert [m[4] for m in _moves(c, p.bolt)[-2:]] == [1, 2], "an untracked component's moves carry the completion too"
    assert c.work_order_lots(wo) == [
        {"batch": 1, "kind": "consume", "item_id": p.hose, "number": "HSE", "lot": "H-2611", "qty": Q("6")},
        {"batch": 1, "kind": "produce", "item_id": p.kit, "number": "KIT", "lot": "WO-00001", "qty": Q("3")},
        {"batch": 2, "kind": "consume", "item_id": p.hose, "number": "HSE", "lot": "H-2612", "qty": Q("2")},
        {"batch": 2, "kind": "produce", "item_id": p.kit, "number": "KIT", "lot": "WO-00001-2", "qty": Q("1")}]
    assert c.activity(1)[0]["detail"] == "WO-00001, 1 made as lot WO-00001-2"


def test_a_lot_made_can_be_named_and_an_untracked_item_cant_be_given_one(plant):
    p, c = plant, plant.c
    wo = _released(c, p.kit, "1")
    assert c.default_made_lot(wo) == "WO-00001"
    c.complete_work_order(wo, Q("1"), lots={p.hose: [("H-2611", Q("2"))]}, made_lot=" K 26/11 ")
    assert c.lots(p.kit)[0]["lot"] == "K 26/11"
    x = c.add_item("X", "Not tracked", "make")
    c.set_bom_line(x, p.bolt, Q("1"))
    wo2 = _released(c, x, "1")
    with pytest.raises(ERPError, match="X isn't tracked by lot"):
        c.complete_work_order(wo2, Q("1"), made_lot="X-1")


def test_shipping_says_which_lots_and_a_shortfall_ships_nothing(plant):
    p, c = plant, plant.c
    wo = _released(c, p.kit, "3")
    c.complete_work_order(wo, Q("2"), lots={p.hose: [("H-2611", Q("4"))]})
    c.complete_work_order(wo, Q("1"), lots={p.hose: [("H-2611", Q("2"))]})
    so = c.create_sales_order(p.cus)
    line = c.add_sales_line(so, p.kit, Q("3"))
    bolts = c.add_sales_line(so, p.bolt, Q("10"))
    c.confirm_sales_order(so)
    before = len(c.moves())
    for lots, why in (({}, "say which lots the 3 shipped came from"),
                      ({line: [("WO-00001", Q("3"))]}, "WO-00001 has 2 on hand, not 3"),
                      ({line: [("WO-00001", Q("2")), ("WO-00001-2", Q("1"))], bolts: [("B", Q("10"))]}, "BLT isn't tracked by lot")):
        with pytest.raises(ERPError, match=why):
            c.ship_sales_order(so, None, lots)
    assert len(c.moves()) == before and all(l["shipped"] == 0 for l in c.sales_lines(so))
    c.ship_sales_order(so, None, {line: c.suggest_lots(p.kit, Q("3"))})
    assert c.sales_order(so)["status"] == "shipped" and c.lots(p.kit, in_stock=True) == []
    assert c.activity(1)[0]["detail"] == "SO-00001: KIT lot WO-00001, KIT lot WO-00001-2"


# ---------------------------------------------------------------- tracing
def test_a_recall_follows_a_lot_into_what_was_made_from_it_and_who_has_it(plant):
    p, c = plant, plant.c
    kits = _released(c, p.kit, "3")
    c.complete_work_order(kits, Q("3"), lots={p.hose: [("H-2611", Q("6"))]})          # KIT lot WO-00001, from H-2611
    units = _released(c, p.hpu, "2")
    c.complete_work_order(units, Q("2"), ["NH-1", "NH-2"], lots={p.kit: [("WO-00001", Q("2"))]})
    c.register_units(units, FakeRevisionWorx())
    so = c.create_sales_order(p.other)
    line = c.add_sales_line(so, p.kit, Q("1"))
    c.confirm_sales_order(so)
    c.ship_sales_order(so, None, {line: [("WO-00001", Q("1"))]})
    plain = c.add_item("PLAIN", "Untracked thing", "make")
    c.set_bom_line(plain, p.hose, Q("1"))
    loose = _released(c, plain, "2")
    c.complete_work_order(loose, Q("2"), lots={p.hose: [("H-2612", Q("2"))]})

    t = c.trace_lot(p.hose, "h-2611")
    assert (t["item"], t["lot"], t["on_hand"], t["cut_short"]) == ("HSE", "H-2611", 0, False)
    assert [(s["what"], s["qty"], s["ref"], s["who"]) for s in t["came"]] == [("Received", Q("6"), "PO-00001", "Hose Co")]
    used = t["went"]
    assert [(s["what"], s["qty"], s["ref"]) for s in used] == [("Used", Q("6"), "WO-00001 (completion 1)")]
    made = used[0]["children"]
    assert [(s["what"], s["item"], s["code"], s["qty"]) for s in made] == [("Made", "KIT", "WO-00001", Q("3"))]
    onward = made[0]["children"]
    assert [(s["kind"], s["item"], s["code"], s["qty"], s["ref"], s["who"]) for s in onward] == [
        ("used", "KIT", "WO-00001", Q("2"), "WO-00002 (completion 1)", ""),
        ("shipped", "KIT", "WO-00001", Q("1"), "SO-00001", "Bayside")]
    assert [(s["kind"], s["code"], s["note"]) for s in onward[0]["children"]] == [
        ("unit", "NH-1", "in RevisionWorx's unit register"), ("unit", "NH-2", "in RevisionWorx's unit register")]
    assert [(u["serial"], u["order"]) for u in t["units"]] == [("NH-1", "WO-00002"), ("NH-2", "WO-00002")]
    assert all(u["rw_unit"] for u in t["units"])
    assert t["shipments"] == [{"item": "KIT", "lot": "WO-00001", "qty": Q("1"), "order": "SO-00001", "customer": "Bayside",
                               "date": t["shipments"][0]["date"]}]
    assert t["in_stock"] == [] and t["untracked"] == []
    assert tracing.summary(t) == ("2 units were made from it (NH-1, NH-2); 1 shipment carried it or what was made from "
                                  "it, to Bayside.")
    rows = tracing.rows(t)
    assert rows[0] == ["Where it came from", "0", "Received", "HSE", "H-2611", "6", "PO-00001", "Hose Co", rows[0][8], ""]
    assert [r[1:5] for r in rows[1:]] == [["0", "Used", "HSE", "H-2611"], ["1", "Made", "KIT", "WO-00001"],
                                          ["2", "Used", "KIT", "WO-00001"], ["3", "Unit made", "HPU", "NH-1"],
                                          ["3", "Unit made", "HPU", "NH-2"], ["2", "Shipped", "KIT", "WO-00001"]]

    # the other lot went into something that isn't tracked, and the trail says it stops there; what's left is in stock
    t2 = c.trace_lot(p.hose, "H-2612")
    assert [s["kind"] for s in t2["went"]] == ["used", "stock"]
    assert t2["went"][0]["children"][0]["note"] == "not tracked by lot or serial, so it can't be followed further"
    assert t2["untracked"][0]["item"] == "PLAIN" and t2["in_stock"] == [{"item": "HSE", "lot": "H-2612", "qty": Q("2")}]
    assert tracing.summary(t2) == ("2 of it is still in stock. Some went into PLAIN, which isn't tracked by lot or "
                                   "serial, so where that went can't be followed.")
    with pytest.raises(ERPError, match="HSE has no lot H-9"):
        c.trace_lot(p.hose, "H-9")


def test_a_suppliers_lots_are_found_by_item_and_the_day_they_came_in(plant, monkeypatch):
    """A supplier announces a recall of lots it sent between two dates: find them, with the orders they came on."""
    p, c = plant, plant.c
    today = c.lots_received(p.sup)[0]["first"]
    other = c.add_contact("supplier", "Other Hoses")
    po2 = c.create_purchase_order(other)
    l2 = c.add_purchase_line(po2, p.hose, Q("5"), M("5"))
    c.place_purchase_order(po2)
    po3 = c.create_purchase_order(p.sup)
    l3 = c.add_purchase_line(po3, p.hose, Q("9"), M("5"))
    c.place_purchase_order(po3)
    monkeypatch.setattr(company_module, "_now", lambda: "2026-03-02T09:00:00")
    c.receive_purchase_order(po2, None, {l2: "OH-1"})
    c.receive_purchase_order(po3, {l3: Q("3")}, {l3: "h-2611"})                    # more of a lot that came before
    monkeypatch.setattr(company_module, "_now", lambda: "2026-04-15T09:00:00")
    c.receive_purchase_order(po3, {l3: Q("6")}, {l3: "H-2613"})
    rows = c.lots_received(p.sup)
    assert [(x["number"], x["lot"], x["received"], x["orders"], x["supplier"]) for x in rows] == [
        ("HSE", "H-2611", Q("9"), ["PO-00001", "PO-00003"], "Hose Co"), ("HSE", "H-2612", Q("4"), ["PO-00001"], "Hose Co"),
        ("HSE", "H-2613", Q("6"), ["PO-00003"], "Hose Co")]
    assert (rows[0]["first"], rows[0]["last"], rows[0]["on_hand"]) == ("2026-03-02", today, Q("9"))
    spring = c.lots_received(p.sup, since="2026-03-01", until="2026-04-30")
    assert [(x["lot"], x["received"], x["orders"]) for x in spring] == [("H-2611", Q("3"), ["PO-00003"]),
                                                                     ("H-2613", Q("6"), ["PO-00003"])]
    assert [x["lot"] for x in c.lots_received(other)] == ["OH-1"]
    assert [x["lot"] for x in c.lots_received(p.sup, p.bolt)] == []                # bolts aren't tracked by lot
    assert len(c.lots_received()) == 4


def test_lots_traced_together_say_what_they_reached_once(plant):
    p, c = plant, plant.c
    kits = _released(c, p.kit, "3")
    c.complete_work_order(kits, Q("3"), lots={p.hose: [("H-2611", Q("6"))]})
    units = _released(c, p.hpu, "2")
    c.complete_work_order(units, Q("2"), ["NH-1", "NH-2"], lots={p.kit: [("WO-00001", Q("2"))]})
    so = c.create_sales_order(p.other)
    line = c.add_sales_line(so, p.kit, Q("1"))
    c.confirm_sales_order(so)
    c.ship_sales_order(so, None, {line: [("WO-00001", Q("1"))]})
    plain = c.add_item("PLAIN", "Untracked thing", "make")
    c.set_bom_line(plain, p.hose, Q("1"))
    loose = _released(c, plain, "2")
    c.complete_work_order(loose, Q("2"), lots={p.hose: [("H-2612", Q("2"))]})

    r = c.trace_lots([(p.hose, "H-2611"), (p.hose, "H-2612"), (p.hose, "h-2611"), (p.kit, "WO-00001")])
    assert [(t["item"], t["lot"]) for t in r["traces"]] == [("HSE", "H-2611"), ("HSE", "H-2612"), ("KIT", "WO-00001")]
    assert [u["serial"] for u in r["units"]] == ["NH-1", "NH-2"]                    # reached twice, listed once
    assert [(s["item"], s["lot"], s["order"], s["customer"]) for s in r["shipments"]] == [
        ("KIT", "WO-00001", "SO-00001", "Bayside")]
    assert r["in_stock"] == [{"item": "HSE", "lot": "H-2612", "qty": Q("2")}]
    assert [u["item"] for u in r["untracked"]] == ["PLAIN"] and not r["cut_short"]
    assert r["lots"] == [{"item": "HSE", "lot": "H-2611"}, {"item": "KIT", "lot": "WO-00001"},
                         {"item": "HSE", "lot": "H-2612"}]
    assert tracing.recall_summary(r) == (
        "3 lots traced; 2 units were made from them (NH-1, NH-2); 1 shipment carried them or what was made from them, to "
        "Bayside; 2 of HSE lot H-2612 is still in stock. Some went into PLAIN, which isn't tracked by lot or serial, so "
        "where that went can't be followed.")
    rows = tracing.recall_rows(r)
    assert rows[0][:5] == ["HSE lot H-2611: Where it came from", "0", "Received", "HSE", "H-2611"]
    assert {row[0] for row in rows} == {f"{i} lot {l}: {s}" for i, l in (("HSE", "H-2611"), ("HSE", "H-2612"), ("KIT", "WO-00001"))
                                        for s in ("Where it came from", "Where it went")}
    with pytest.raises(ERPError, match="at least one lot"):
        c.trace_lots([])
    with pytest.raises(ERPError, match="HSE has no lot H-9"):
        c.trace_lots([(p.hose, "H-2611"), (p.hose, "H-9")])


def test_revisionworx_is_asked_about_every_lot_a_recall_reached(plant):
    p, c = plant, plant.c
    kits = _released(c, p.kit, "2")
    c.complete_work_order(kits, Q("2"), lots={p.hose: [("H-2611", Q("4"))]})
    r = c.trace_lots([(p.hose, "H-2611"), (p.hose, "H-2612")])
    spare = {"unit": _summary("unt_" + "9" * 32, "NH-9", "Bayside"), "position": "H3", "current": True,
             "fitted_on": "2026-11-20"}
    register = Register([], fitted={("kit", "wo-00001"): [spare]})
    found = tracing.in_revisionworx(r, register)
    assert register.asked == [("HSE", "H-2611", True), ("KIT", "WO-00001", True), ("HSE", "H-2612", True)]
    assert [(f["item"], f["lot"], f["unit"]["label"]) for f in found["fitted"]] == [("KIT", "WO-00001", "NH-9")]
    assert tracing.rw_summary(found, "them") == ("RevisionWorx records them, or lots made from them, fitted in NH-9, "
                                                 "which the stock ledger can't know.")


def test_tracing_a_made_lot_back_shows_what_went_into_it(plant):
    p, c = plant, plant.c
    wo = _released(c, p.kit, "4")
    c.complete_work_order(wo, Q("4"), lots={p.hose: [("H-2611", Q("6")), ("H-2612", Q("2"))]})
    t = c.trace_lot(p.kit, "WO-00001")
    made = t["came"]
    assert [(s["what"], s["qty"], s["ref"]) for s in made] == [("Made", Q("4"), "WO-00001 (completion 1)")]
    parts = made[0]["children"]
    assert [(s["item"], s["code"], s["qty"], s["note"]) for s in parts] == [
        ("BLT", "", Q("16"), "not tracked by lot or serial, so it can't be followed further"),
        ("HSE", "H-2611", Q("6"), ""), ("HSE", "H-2612", Q("2"), "")]
    assert [(s["what"], s["ref"], s["who"]) for s in parts[1]["children"]] == [("Received", "PO-00001", "Hose Co")]
    assert t["in_stock"] == [{"item": "KIT", "lot": "WO-00001", "qty": Q("4")}]


def test_units_used_on_another_work_order_end_the_trail_saying_why(plant):
    p, c = plant, plant.c
    kits = _released(c, p.kit, "1")
    c.complete_work_order(kits, Q("1"), lots={p.hose: [("H-2611", Q("2"))]})
    units = _released(c, p.hpu, "1")
    c.complete_work_order(units, Q("1"), ["NH-1"], lots={p.kit: [("WO-00001", Q("1"))]})
    skid = c.add_item("SKID", "Skid with a power unit", "make", tracking="lot")
    c.set_bom_line(skid, p.hpu, Q("1"))
    top = _released(c, skid, "1")
    c.complete_work_order(top, Q("1"))
    assert [(u["serial"], u["order"]) for u in c.trace_lot(p.kit, "WO-00001")["units"]] == [("NH-1", "WO-00002")]
    came = c.trace_lot(skid, "WO-00003")["came"][0]["children"]
    assert [(s["item"], s["code"], s["note"]) for s in came] == [
        ("HPU", "", "which units isn't recorded when they're used, so they can't be followed further")]


def test_a_trace_that_goes_deeper_than_it_follows_says_where_it_stopped(plant, monkeypatch):
    p, c = plant, plant.c
    kits = _released(c, p.kit, "1")
    c.complete_work_order(kits, Q("1"), lots={p.hose: [("H-2611", Q("2"))]})
    monkeypatch.setattr(company_module, "TRACE_DEPTH", 1)
    t = c.trace_lot(p.hose, "H-2611")
    made = t["went"][0]["children"][0]
    assert (made["item"], made["code"], made["children"]) == ("KIT", "WO-00001", []) and t["cut_short"]
    assert tracing.summary(t).endswith("The trace stopped after many levels of assemblies; trace the last lots shown "
                                       "to go further.")
    back = c.trace_lot(p.kit, "WO-00001")["came"][0]["children"]
    assert [(s["item"], s["children"]) for s in back if s["code"]] == [("HSE", [])]


# ---------------------------------------------------------------- what RevisionWorx's register says of what a lot reached
class Register:
    """Answers as RevisionWorx's `link units` and `link where-used` do, from what it's given, and keeps what it was asked."""

    def __init__(self, units, fitted=None, features=("units", "unit-where-used")):
        self._units, self._fitted, self.features, self.asked = units, fitted or {}, set(features), []

    def has(self, feature):
        return feature in self.features

    def units(self):
        return self._units

    def where_used(self, part_number, lot="", history=True):
        self.asked.append((part_number, lot, history))
        return self._fitted.get((part_number.casefold(), lot.casefold()), [])


def _summary(uid, label, customer="", site="", status="in-service", serial=None):
    return {"id": uid, "label": label, "status": status, "customer": customer, "site": site, "location": "",
            "identifiers": [{"scheme": "serial", "value": serial or label, "issuer": ""}]}


def _recalled(plant):
    """Hose lot H-2611 made into kit lot WO-00001, two kits made into power units NH-1 and NH-2 (registered), one
    shipped to Bayside."""
    p, c = plant, plant.c
    kits = _released(c, p.kit, "3")
    c.complete_work_order(kits, Q("3"), lots={p.hose: [("H-2611", Q("6"))]})
    units = _released(c, p.hpu, "2")
    c.complete_work_order(units, Q("2"), ["NH-1", "NH-2"], lots={p.kit: [("WO-00001", Q("2"))]})
    c.register_units(units, FakeRevisionWorx())
    return c.trace_lot(p.hose, "H-2611"), {u["serial"]: u["rw_unit"] for u in c.units_built(units)}


def test_a_recall_asks_revisionworx_where_each_unit_is_and_what_else_has_the_lots(plant):
    t, ids = _recalled(plant)
    assert t["lots"] == [{"item": "HSE", "lot": "H-2611"}, {"item": "KIT", "lot": "WO-00001"}]
    spare = {"unit": _summary("unt_" + "7" * 32, "NH-77", "Bayside", "Port Ellis"), "position": "K1", "fitted": 4,
             "current": True, "fitted_on": "2026-11-20", "removed": None, "serial": "", "lot": "WO-00001"}
    again = {"unit": _summary(ids["NH-1"], "NH-1"), "position": "K1", "fitted": 2, "current": True, "lot": "WO-00001"}
    register = Register([_summary(ids["NH-1"], "NH-1", "Acme", "Milltown"),
                         _summary("unt_" + "2" * 32, "NH-2 (as RevisionWorx calls it)", serial="nh-2")],
                        {("kit", "wo-00001"): [spare, again]})
    r = tracing.in_revisionworx(t, register)
    assert [(u["serial"], u["found"]["label"] if u["found"] else None) for u in r["units"]] == [
        ("NH-1", "NH-1"), ("NH-2", "NH-2 (as RevisionWorx calls it)")], "by the id it was registered with, or the serial"
    assert [(f["unit"]["label"], f["item"], f["lot"], f["position"]) for f in r["fitted"]] == [("NH-77", "KIT", "WO-00001", "K1")]
    assert register.asked == [("HSE", "H-2611", True), ("KIT", "WO-00001", True)], "every lot reached, ever fitted"
    assert tracing.rw_summary(r) == ("RevisionWorx has 2 of the 2 units made from it. It also records it, or a lot made "
                                     "from it, fitted in NH-77, which the stock ledger can't know.")
    rows = tracing.rw_rows(r)
    assert rows[0] == ["In RevisionWorx", "0", "Unit", "HPU", "NH-1", "1", "NH-1", "Acme, Milltown", "", "in-service"]
    assert rows[2] == ["In RevisionWorx", "0", "Fitted at K1", "KIT", "WO-00001", "", "NH-77", "Bayside, Port Ellis",
                       "2026-11-20", "fitted now; in-service"]


def test_a_unit_revisionworx_doesnt_have_and_an_older_revisionworx_are_said_plainly(plant):
    t, ids = _recalled(plant)
    old = Register([_summary(ids["NH-1"], "NH-1")], features=("units",))
    r = tracing.in_revisionworx(t, old)
    assert [u["found"] is None for u in r["units"]] == [False, True] and old.asked == [] and r["fitted"] == []
    assert tracing.rw_summary(r) == ("RevisionWorx has 1 of the 2 units made from it; not NH-2. This RevisionWorx can't "
                                     "say which other units have these lots fitted. Update it (1.0.0 or later) to see them.")
    assert tracing.rw_rows(r)[1][-1] == "not in RevisionWorx's unit register"
    # a lot that went into no unit: the register's answer stands on its own
    nothing = {"units": [], "fitted": [], "note": ""}
    assert tracing.rw_summary(nothing) == "RevisionWorx records it fitted in no unit."
    spare = {"unit": _summary("unt_" + "7" * 32, "NH-77"), "position": "K1", "current": True}
    assert tracing.rw_summary({"units": [], "fitted": [{"item": "KIT", "lot": "L", **spare}], "note": ""}) == (
        "RevisionWorx records it, or a lot made from it, fitted in NH-77, which the stock ledger can't know.")


def test_a_recall_asks_the_real_revisionworx_and_writes_nothing_there(workspace, plant):
    from openmeridian import revisionworx as rw
    w, p, c = workspace, plant, plant.c
    client = rw.Client(w.path)
    kits = _released(c, p.kit, "2")
    c.complete_work_order(kits, Q("2"), lots={p.hose: [("H-2611", Q("4"))]})
    units = _released(c, p.hpu, "1")
    c.complete_work_order(units, Q("1"), ["NH-26-0101"], lots={p.kit: [("WO-00001", Q("1"))]})
    assert c.register_units(units, client)["registered"] == ["NH-26-0101"]

    def unit(*args):                    # `revisionworx unit ...` takes no top-level --json
        subprocess.run([*rw.find_cli(), "-w", w.path, "unit", *args], capture_output=True, text=True, check=True)
    unit("update", "NH-26-0101", "--customer", "Acme", "--site", "Milltown")
    unit("new", "--serial", "NH-26-0900", "--model", "HPU", "--customer", "Bayside Marine", "--status", "in-service")
    unit("fit", "NH-26-0900", "K1", "--part-number", "KIT", "--lot", "WO-00001")       # a spare kit, fitted on site
    files = {f: f.stat().st_mtime_ns for f in (Path(w.path) / ".revisionworx").rglob("*") if f.is_file()}
    t = c.trace_lot(p.hose, "H-2611")
    r = tracing.in_revisionworx(t, client)
    assert [(u["serial"], u["found"]["customer"], u["found"]["site"]) for u in r["units"]] == [("NH-26-0101", "Acme", "Milltown")]
    assert [(f["unit"]["label"], f["unit"]["customer"], f["position"], f["current"]) for f in r["fitted"]] == [
        ("NH-26-0900", "Bayside Marine", "K1", True)]
    assert {f: f.stat().st_mtime_ns for f in (Path(w.path) / ".revisionworx").rglob("*") if f.is_file()} == files, \
        "asking wrote nothing in the workspace"
