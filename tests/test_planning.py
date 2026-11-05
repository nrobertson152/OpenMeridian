from conftest import M, Q

from openmeridian import planning


def _by(rows):
    return {r.number: r for r in rows}


def test_nothing_needed_means_nothing_suggested(setup):
    assert planning.plan(setup.c) == []


def test_sale_beyond_stock_suggests_buying_the_shortfall(setup):
    c = setup.c
    so = c.create_sales_order(setup.cus)
    c.add_sales_line(so, setup.a, Q("14"))
    c.confirm_sales_order(so)
    r = _by(planning.plan(c))["A"]
    assert r.qty == Q("4") and r.kind == "buy" and r.supplier_id == setup.sup


def test_open_supply_counts(setup):
    c = setup.c
    so = c.create_sales_order(setup.cus)
    c.add_sales_line(so, setup.a, Q("14"))
    c.confirm_sales_order(so)
    po = c.create_purchase_order(setup.sup)
    c.add_purchase_line(po, setup.a, Q("3"))
    c.place_purchase_order(po)
    assert _by(planning.plan(c))["A"].qty == Q("1")


def test_reorder_point_and_quantity(setup):
    c = setup.c
    c.update_item(setup.a, reorder_point=Q("15"), reorder_qty=Q("50"))
    assert _by(planning.plan(c))["A"].qty == Q("50")


def test_made_item_explodes_through_levels(setup):
    """Selling 5 assemblies needs 10 of A (have 10) and 5 of B (have 10): no parts. Selling 8 needs 16 of A: buy 6."""
    c = setup.c
    so = c.create_sales_order(setup.cus)
    c.add_sales_line(so, setup.x, Q("8"))
    c.confirm_sales_order(so)
    rows = _by(planning.plan(c))
    assert rows["X"].qty == Q("8") and rows["X"].kind == "make"
    assert rows["A"].qty == Q("6") and "B" not in rows


def test_three_levels_and_shared_parts(setup):
    c = setup.c
    y = c.add_item("Y", kind="make")
    c.set_bom_line(y, setup.x, Q("2"))
    c.set_bom_line(y, setup.a, Q("1"))
    so = c.create_sales_order(setup.cus)
    c.add_sales_line(so, y, Q("3"))
    c.confirm_sales_order(so)
    rows = _by(planning.plan(c))
    assert rows["Y"].qty == Q("3") and rows["X"].qty == Q("6")
    # A: 3 for Y directly + 12 for 6 X = 15, against 10 in stock
    assert rows["A"].qty == Q("5")


def test_create_orders_groups_by_supplier_and_stays_draft(setup):
    c = setup.c
    so = c.create_sales_order(setup.cus)
    c.add_sales_line(so, setup.x, Q("20"))
    c.confirm_sales_order(so)
    res = planning.create_orders(c, planning.plan(c))
    assert len(res["purchase_orders"]) == 1 and len(res["work_orders"]) == 1
    po = res["purchase_orders"][0]
    assert c.purchase_order(po)["status"] == "draft" and len(c.purchase_lines(po)) == 2
    assert c.work_order(res["work_orders"][0])["status"] == "draft"


def test_item_with_no_supplier_is_reported_not_dropped(company):
    c = company
    cus = c.add_contact("customer", "C")
    i = c.add_item("I", cost=M("1"))
    so = c.create_sales_order(cus)
    c.add_sales_line(so, i, Q("1"))
    c.confirm_sales_order(so)
    res = planning.create_orders(c, planning.plan(c))
    assert res["no_supplier"] == ["I"] and not res["purchase_orders"]
