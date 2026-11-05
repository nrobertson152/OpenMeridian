"""A small invented company to explore: a builder of hydraulic power units."""
from __future__ import annotations

from datetime import date, timedelta

from .company import Company
from .values import parse_money as M
from .values import parse_qty as Q


def build(path: str) -> Company:
    c = Company.create(path, "Northline Hydraulics (sample)")
    c.set_setting("address", "100 Example Way\nSpringfield")
    c.set_setting("tax_percent", "7")
    acme = c.add_contact("customer", "Acme Manufacturing", "Jo Lee", "jo@example.com", "555-0100", "1 Works Road\nMilltown", 30)
    bay = c.add_contact("customer", "Bayside Marine", "Sam Ortiz", "sam@example.com", "555-0101", "9 Harbor St\nPort Ellis", 15)
    delta = c.add_contact("supplier", "Delta Motion Supply", "Pat Gray", "orders@example.com", "555-0200", "44 Valve Ave\nTulsa", 30)
    iron = c.add_contact("supplier", "Ironbridge Steel", "Ana Ruiz", "sales@example.org", "555-0201", "2 Mill Lane\nGary", 30)
    def item(num, desc, kind="buy", cost="0", price="0", rp="0", rq="0", sup=None, lead=0, b=""):
        return c.add_item(num, desc, kind, "EA", M(cost), M(price), Q(rp), Q(rq), sup, lead, b)
    pump = item("PMP-10", "Gear pump, 10 cc/rev", cost="185", rp="4", rq="10", sup=delta, lead=10, b="A1")
    motor = item("MTR-7K5", "Electric motor, 7.5 kW", cost="620", rp="2", rq="4", sup=delta, lead=21, b="A2")
    relief = item("VLV-RV160", "Relief valve, 160 bar", cost="74", rp="5", rq="10", sup=delta, lead=7, b="B1")
    dcv = item("VLV-D03", "Directional valve, 4/3, D03", cost="145", rp="4", rq="8", sup=delta, lead=14, b="B2")
    tank = item("TNK-100", "Reservoir, 100 L", cost="240", rp="2", rq="4", sup=iron, lead=14, b="C1")
    frame = item("FRM-200", "Skid frame, welded", cost="310", rp="1", rq="3", sup=iron, lead=14, b="C2")
    hose = item("HSE-08", "Hose kit, -08", cost="48", rp="10", rq="20", sup=delta, lead=5, b="B4")
    hpu = item("HPU-75", "Hydraulic power unit, 7.5 kW", "make", price="4250", rp="1", rq="2", b="F1")
    manifold = item("MAN-02", "Valve manifold assembly", "make", price="980", b="F2")
    for child, qty in ((pump, "1"), (motor, "1"), (tank, "1"), (frame, "1"), (manifold, "1"), (hose, "2")):
        c.set_bom_line(hpu, child, Q(qty))
    for child, qty in ((relief, "1"), (dcv, "2")):
        c.set_bom_line(manifold, child, Q(qty))
    po = c.create_purchase_order(delta, reference="Stock")
    for it, qty, cost in ((pump, "6", "185"), (motor, "2", "620"), (relief, "6", "74"), (dcv, "6", "145"), (hose, "12", "48")):
        c.add_purchase_line(po, it, Q(qty), M(cost))
    c.place_purchase_order(po)
    c.receive_purchase_order(po)
    po2 = c.create_purchase_order(iron, reference="Stock")
    c.add_purchase_line(po2, tank, Q("3"), M("240"))
    c.add_purchase_line(po2, frame, Q("2"), M("310"))
    c.place_purchase_order(po2)
    c.receive_purchase_order(po2)
    wo = c.create_work_order(manifold, Q("2"))
    c.release_work_order(wo, rw_note="No controlled document linked")
    c.complete_work_order(wo)
    wo2 = c.create_work_order(hpu, Q("1"), (date.today() + timedelta(days=7)).isoformat())
    c.release_work_order(wo2, rw_note="No controlled document linked")
    c.complete_work_order(wo2)
    so = c.create_sales_order(acme, (date.today() + timedelta(days=14)).isoformat(), "PO 44182")
    c.add_sales_line(so, hpu, Q("1"))
    c.confirm_sales_order(so)
    c.ship_sales_order(so)
    c.invoice_sales_order(so)
    so2 = c.create_sales_order(bay, (date.today() + timedelta(days=21)).isoformat(), "Refit 12")
    c.add_sales_line(so2, hpu, Q("2"))
    c.add_sales_line(so2, manifold, Q("1"))
    c.confirm_sales_order(so2)
    so3 = c.create_sales_order(acme, reference="Quote")
    c.add_sales_line(so3, pump, Q("2"), M("260"))
    po3 = c.create_purchase_order(delta, (date.today() - timedelta(days=3)).isoformat(), "Replenish")
    c.add_purchase_line(po3, motor, Q("4"), M("615"))
    c.place_purchase_order(po3)
    wo3 = c.create_work_order(manifold, Q("3"), (date.today() + timedelta(days=5)).isoformat())
    c.release_work_order(wo3, rw_note="No controlled document linked")
    c.create_work_order(hpu, Q("2"), (date.today() + timedelta(days=20)).isoformat())
    return c
