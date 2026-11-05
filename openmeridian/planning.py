"""What to buy and make. Demand from confirmed sales and released work is netted against stock and open supply,
level by level down the bills of materials, so a planned assembly creates demand for its own components."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .values import QTY_SCALE


@dataclass
class Suggestion:
    item_id: int
    number: str
    description: str
    kind: str
    unit: str
    demand: int
    on_hand: int
    on_order: int
    reorder_point: int
    qty: int
    supplier_id: int | None
    supplier: str
    earliest: str      # today plus this item's own lead time; lower levels aren't added on
    unit_cost: int


def _levels(company, items) -> dict:
    """Lowest level of each item in any BOM: a component is always planned after everything that uses it."""
    children = {}
    for r in company.conn.execute("SELECT parent_id, child_id FROM bom_lines"):
        children.setdefault(r[0], []).append(r[1])
    level = {i["id"]: 0 for i in items}
    changed, guard = True, 0
    while changed and guard <= len(level) + 1:
        changed, guard = False, guard + 1
        for parent, kids in children.items():
            for kid in kids:
                if kid in level and level[kid] < level.get(parent, 0) + 1:
                    level[kid] = level.get(parent, 0) + 1
                    changed = True
    return level


def plan(company) -> list[Suggestion]:
    items = company.items()
    extra = {i["id"]: 0 for i in items}     # demand made by planned parents during this run
    out = []
    level = _levels(company, items)
    for i in sorted(items, key=lambda x: (level[x["id"]], x["number"].casefold())):
        demand = i["allocated"] + extra[i["id"]]
        available = i["on_hand"] + i["on_order"] - demand
        if available >= i["reorder_point"] and available >= 0:
            continue
        if available >= 0 and not i["reorder_point"]:
            continue
        short = i["reorder_point"] - available
        qty = max(short, i["reorder_qty"]) if short > 0 else 0
        if qty <= 0:
            continue
        if i["kind"] == "make":
            for b in company.bom(i["id"]):
                if b["child_id"] in extra:
                    extra[b["child_id"]] += (qty * b["qty"] + QTY_SCALE - 1) // QTY_SCALE
        earliest = (date.today() + timedelta(days=i["lead_days"])).isoformat()
        out.append(Suggestion(i["id"], i["number"], i["description"], i["kind"], i["unit"], demand, i["on_hand"], i["on_order"],
                              i["reorder_point"], qty, i["supplier_id"], i["supplier"] or "", earliest, i["cost"]))
    return out


def create_orders(company, suggestions: list[Suggestion]) -> dict:
    """Turn suggestions into draft orders: one purchase order per supplier, one work order per made item.
    All or nothing. Bought items with no supplier are reported and left out."""
    pos, wos, skipped = [], [], []
    with company.tx():
        by_supplier: dict = {}
        for s in suggestions:
            if s.kind == "make":
                wos.append(company.create_work_order(s.item_id, s.qty))
            elif s.supplier_id is None:
                skipped.append(s.number)
            else:
                by_supplier.setdefault(s.supplier_id, []).append(s)
        for supplier_id, rows in by_supplier.items():
            po = company.create_purchase_order(supplier_id, due_date=max(r.earliest for r in rows))
            for r in rows:
                company.add_purchase_line(po, r.item_id, r.qty, r.unit_cost)
            pos.append(po)
    return {"purchase_orders": pos, "work_orders": wos, "no_supplier": skipped}
