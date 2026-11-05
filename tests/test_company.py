import os
import sqlite3

import pytest
from conftest import M, Q

from openmeridian import db
from openmeridian.company import Company, ERPError


# ---- the file
def test_reopen_keeps_everything(tmp_path):
    p = str(tmp_path / "a.meridian")
    c = Company.create(p, "Acme")
    c.add_item("P1", "Thing", cost=M("1.50"))
    c.close()
    c = Company.open(p)
    assert c.setting("company_name") == "Acme" and c.item_by_number("p1")["cost"] == 150
    c.close()


def test_create_refuses_to_overwrite(tmp_path):
    p = tmp_path / "a.meridian"
    p.write_text("precious")
    with pytest.raises(db.CompanyFileError):
        Company.create(str(p), "Acme")
    assert p.read_text() == "precious"


@pytest.mark.parametrize("content", [b"", b"not a database at all, just some text", b"SQLite format 3\x00garbage" * 20])
def test_junk_is_refused_with_a_message(tmp_path, content):
    p = tmp_path / "bad.meridian"
    p.write_bytes(content)
    with pytest.raises(db.CompanyFileError):
        Company.open(str(p))


def test_other_sqlite_file_is_refused(tmp_path):
    p = tmp_path / "other.meridian"
    s = sqlite3.connect(p)
    s.execute("CREATE TABLE t (x)")
    s.commit()
    s.close()
    with pytest.raises(db.CompanyFileError, match="not an OpenMeridian"):
        Company.open(str(p))


def test_newer_format_is_refused_not_guessed(tmp_path):
    p = str(tmp_path / "a.meridian")
    Company.create(p, "A").close()
    s = sqlite3.connect(p)
    s.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    s.close()
    with pytest.raises(db.CompanyFileError, match="newer"):
        Company.open(p)


def test_backup_is_complete_and_never_overwrites(setup, tmp_path):
    dest = str(tmp_path / "b.meridian")
    setup.c.backup(dest)
    b = Company.open(dest)
    assert b.item_by_number("A")["on_hand"] == Q("10")
    b.close()
    with pytest.raises(db.CompanyFileError):
        setup.c.backup(dest)
    assert not os.path.exists(dest + ".tmp")


def test_failed_change_leaves_nothing_behind(setup):
    c = setup.c
    so = c.create_sales_order(setup.cus)
    c.add_sales_line(so, setup.a, Q("1"))
    c.add_sales_line(so, setup.b, Q("999"))
    c.confirm_sales_order(so)
    before = (c.on_hand(setup.a), c.on_hand(setup.b), len(c.moves()))
    with pytest.raises(ERPError):
        c.ship_sales_order(so)      # the first line could ship; the second can't, so neither may
    assert (c.on_hand(setup.a), c.on_hand(setup.b), len(c.moves())) == before
    assert all(l["shipped"] == 0 for l in c.sales_lines(so))


# ---- the ledger can't be rewritten
def test_ledger_and_log_cannot_be_altered(setup):
    for sql in ("UPDATE stock_moves SET qty = 1", "DELETE FROM stock_moves", "UPDATE audit SET detail = ''", "DELETE FROM audit"):
        with pytest.raises(sqlite3.IntegrityError):
            setup.c.conn.execute(sql)


def test_stock_is_only_ever_the_ledger(setup):
    c = setup.c
    assert c.on_hand(setup.a) == sum(m["qty"] for m in c.moves(setup.a))


def test_adjustment_needs_a_reason_and_cant_go_negative(setup):
    c = setup.c
    with pytest.raises(ERPError, match="why"):
        c.adjust_stock(setup.a, Q("1"), "  ")
    with pytest.raises(ERPError):
        c.adjust_stock(setup.a, Q("-11"), "count")
    c.adjust_stock(setup.a, Q("-1"), "dropped one")
    assert c.on_hand(setup.a) == Q("9") and c.moves(setup.a)[0]["note"] == "dropped one"


# ---- items and BOMs
def test_item_numbers_are_unique_ignoring_case(company):
    company.add_item("ABC")
    with pytest.raises(ERPError, match="already"):
        company.add_item("abc")
    with pytest.raises(ERPError):
        company.add_item("   ")


def test_bom_cycles_are_refused(setup):
    c = setup.c
    y = c.add_item("Y", kind="make")
    c.set_bom_line(y, setup.x, Q("1"))
    with pytest.raises(ERPError, match="part of itself"):
        c.set_bom_line(setup.x, y, Q("1"))
    with pytest.raises(ERPError, match="part of itself"):
        c.set_bom_line(setup.a, y, Q("1"))
    with pytest.raises((ERPError, sqlite3.IntegrityError)):
        c.set_bom_line(setup.a, setup.a, Q("1"))


def test_rollup_cost(setup):
    assert setup.c.rollup_cost(setup.x) == M("25")     # 2 x 10 + 1 x 5


# ---- purchasing
def test_receipt_updates_average_cost(company):
    c = company
    s = c.add_contact("supplier", "S")
    i = c.add_item("I", cost=M("10"))
    po = c.create_purchase_order(s)
    c.add_purchase_line(po, i, Q("10"), M("10"))
    c.add_purchase_line(po, i, Q("10"), M("20"))
    c.place_purchase_order(po)
    c.receive_purchase_order(po)
    assert c.item(i)["cost"] == M("15") and c.stock_value() == M("300")


def test_partial_receipt_keeps_order_open(company):
    c = company
    s = c.add_contact("supplier", "S")
    i = c.add_item("I")
    po = c.create_purchase_order(s)
    line = c.add_purchase_line(po, i, Q("10"), M("1"))
    c.place_purchase_order(po)
    c.receive_purchase_order(po, {line: Q("4")})
    assert c.purchase_order(po)["status"] == "ordered" and c.on_hand(i) == Q("4") and c.item(i)["on_order"] == Q("6")
    with pytest.raises(ERPError, match="outstanding"):
        c.receive_purchase_order(po, {line: Q("7")})
    with pytest.raises(ERPError):
        c.cancel_purchase_order(po)
    c.receive_purchase_order(po)
    assert c.purchase_order(po)["status"] == "received" and c.item(i)["on_order"] == 0


def test_order_rules(company):
    c = company
    s = c.add_contact("supplier", "S")
    i = c.add_item("I")
    po = c.create_purchase_order(s)
    with pytest.raises(ERPError, match="at least one"):
        c.place_purchase_order(po)
    line = c.add_purchase_line(po, i, Q("1"), 100)
    c.place_purchase_order(po)
    with pytest.raises(ERPError):
        c.add_purchase_line(po, i, Q("1"))
    with pytest.raises(ERPError):
        c.remove_purchase_line(line)
    with pytest.raises(ERPError):
        c.add_purchase_line(c.create_purchase_order(s), i, 0)


def test_numbers_are_never_reused(company):
    c = company
    s = c.add_contact("supplier", "S")
    a, b = c.create_purchase_order(s), c.create_purchase_order(s)
    c.cancel_purchase_order(a)
    assert c.purchase_order(a)["number"] == "PO-00001" and c.purchase_order(b)["number"] == "PO-00002"
    assert c.purchase_order(c.create_purchase_order(s))["number"] == "PO-00003"


# ---- sales and invoices
def _sale(s, qty="3"):
    so = s.c.create_sales_order(s.cus, reference="R1")
    line = s.c.add_sales_line(so, s.a, Q(qty))
    s.c.confirm_sales_order(so)
    return so, line


def test_confirmed_sale_allocates_and_shipping_takes_stock(setup):
    c = setup.c
    so, _ = _sale(setup)
    assert c.item(setup.a)["allocated"] == Q("3") and c.on_hand(setup.a) == Q("10")
    c.ship_sales_order(so)
    assert c.item(setup.a)["allocated"] == 0 and c.on_hand(setup.a) == Q("7") and c.sales_order(so)["status"] == "shipped"


def test_price_defaults_from_item_and_can_be_overridden(setup):
    c = setup.c
    so = c.create_sales_order(setup.cus)
    c.add_sales_line(so, setup.a, Q("1"))
    c.add_sales_line(so, setup.a, Q("1"), M("15"))
    assert [l["unit_price"] for l in c.sales_lines(so)] == [M("20"), M("15")]


def test_invoice_covers_only_what_shipped_with_tax(setup):
    c = setup.c
    c.set_setting("tax_percent", "10")
    so, line = _sale(setup)
    c.ship_sales_order(so, {line: Q("1")})
    inv = c.invoice_sales_order(so)
    v = c.invoice(inv)
    assert v["subtotal"] == M("20") and v["tax"] == M("2") and v["total"] == M("22") and v["status"] == "open"
    with pytest.raises(ERPError, match="nothing shipped"):
        c.invoice_sales_order(so)
    c.ship_sales_order(so)
    assert c.invoice(c.invoice_sales_order(so))["subtotal"] == M("40")


def test_invoice_tax_rate_is_kept_when_the_setting_changes(setup):
    c = setup.c
    c.set_setting("tax_percent", "10")
    so, _ = _sale(setup)
    c.ship_sales_order(so)
    inv = c.invoice_sales_order(so)
    c.set_setting("tax_percent", "25")
    assert c.invoice(inv)["tax"] == M("6") and c.invoice(inv)["tax_percent"] == "10"


def test_void_lets_it_be_invoiced_again_and_paid_cant_be_voided(setup):
    c = setup.c
    so, _ = _sale(setup)
    c.ship_sales_order(so)
    inv = c.invoice_sales_order(so)
    c.void_invoice(inv)
    inv2 = c.invoice_sales_order(so)
    assert c.invoice(inv2)["number"] != c.invoice(inv)["number"]
    c.mark_invoice_paid(inv2)
    with pytest.raises(ERPError):
        c.void_invoice(inv2)
    with pytest.raises(ERPError):
        c.mark_invoice_paid(inv2)


def test_cant_cancel_after_shipping(setup):
    c = setup.c
    so, line = _sale(setup)
    c.ship_sales_order(so, {line: Q("1")})
    with pytest.raises(ERPError, match="shipped"):
        c.cancel_sales_order(so)


def test_bad_tax_rate_refused(company):
    for bad in ("abc", "-1", "101", "NaN"):
        with pytest.raises(ERPError):
            company.set_setting("tax_percent", bad)


# ---- production
def test_work_order_consumes_parts_and_makes_at_actual_cost(setup):
    c = setup.c
    w = c.create_work_order(setup.x, Q("2"))
    c.release_work_order(w)
    assert c.item(setup.a)["allocated"] == Q("4") and c.item(setup.x)["on_order"] == Q("2")
    c.complete_work_order(w)
    assert c.on_hand(setup.a) == Q("6") and c.on_hand(setup.b) == Q("8") and c.on_hand(setup.x) == Q("2")
    assert c.item(setup.x)["cost"] == M("25") and c.work_order(w)["status"] == "complete"
    assert c.item(setup.a)["allocated"] == 0


def test_partial_completion(setup):
    c = setup.c
    w = c.create_work_order(setup.x, Q("3"))
    c.release_work_order(w)
    c.complete_work_order(w, Q("1"))
    assert c.work_order(w)["status"] == "released" and c.work_order(w)["done"] == Q("1")
    assert [x["needed"] for x in c.work_order_components(w)] == [Q("4"), Q("2")]
    with pytest.raises(ERPError, match="left to make"):
        c.complete_work_order(w, Q("3"))
    with pytest.raises(ERPError, match="finished"):
        c.cancel_work_order(w)


def test_short_parts_consume_nothing(setup):
    c = setup.c
    w = c.create_work_order(setup.x, Q("6"))     # 12 of A needed, 10 in stock
    c.release_work_order(w)
    before = len(c.moves())
    with pytest.raises(ERPError, match="needed"):
        c.complete_work_order(w)
    assert len(c.moves()) == before and c.on_hand(setup.x) == 0


def test_no_bom_no_release(setup):
    c = setup.c
    w = c.create_work_order(setup.a, Q("1"))
    with pytest.raises(ERPError, match="no bill of materials"):
        c.release_work_order(w)


def test_release_records_the_revision(setup):
    c = setup.c
    w = c.create_work_order(setup.x, Q("1"))
    c.release_work_order(w, "doc_1", "rev_1", "B")
    r = c.work_order(w)
    assert (r["build_rw_document"], r["build_rw_revision"], r["build_rw_label"]) == ("doc_1", "rev_1", "B")


# ---- attention
def test_attention_finds_what_is_late(setup):
    c = setup.c
    po = c.create_purchase_order(setup.sup, due_date="2000-01-01")
    c.add_purchase_line(po, setup.a, Q("1"))
    c.place_purchase_order(po)
    so = c.create_sales_order(setup.cus, due_date="2000-01-01")
    c.add_sales_line(so, setup.a, Q("1"))
    c.confirm_sales_order(so)
    c.update_item(setup.b, reorder_point=Q("100"))
    text = " ".join(a[1] for a in c.attention())
    assert c.purchase_order(po)["number"] in text and c.sales_order(so)["number"] in text and "B is below" in text
    assert c.attention()[0][0] == "danger"


def test_bad_date_refused(setup):
    with pytest.raises(ERPError, match="YYYY-MM-DD"):
        setup.c.create_sales_order(setup.cus, due_date="next week")


def test_old_sqlite_is_a_message_not_a_crash(tmp_path, monkeypatch):
    p = str(tmp_path / "a.meridian")
    Company.create(p, "A").close()
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 35, 5))
    with pytest.raises(db.CompanyFileError, match="3.37"):
        Company.open(p)
    with pytest.raises(db.CompanyFileError, match="3.37"):
        Company.create(str(tmp_path / "b.meridian"), "B")
