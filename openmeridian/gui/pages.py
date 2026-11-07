"""The pages of the program. Each is a thin view: all rules are in company.py."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import planning
from .. import revisionworx as rw
from ..values import fmt_qty, line_total
from . import dialogs as dlg
from . import icons as ic
from .widgets import Column, KeyValues, ListPage, MiniTable, StatusBlock, button, label


def _today():
    return date.today().isoformat()


def qty_sort(key):
    return lambda r: r[key]


STATE_NAMES = {"wip": "Work in progress", "in_review": "In review", "approved": "Approved", "released": "Released", "superseded": "Superseded", "obsolete": "Obsolete"}


def state_name(state: str) -> str:
    return STATE_NAMES.get(state, state or "no state")


MOVE_KINDS = {"receipt": "Receipt", "shipment": "Shipment", "produce": "Made", "consume": "Used", "adjust": "Adjustment", "adjustment": "Adjustment"}
ACTIONS = {"company.create": "Company created", "settings": "Settings changed", "contact.add": "Contact added", "contact.update": "Contact edited",
           "item.add": "Item added", "item.update": "Item edited", "bom.set": "BOM changed", "bom.remove": "BOM line removed", "bom.import": "BOM imported",
           "stock.adjust": "Stock adjusted", "so.create": "Sales order created", "so.confirm": "Sales order confirmed", "so.ship": "Shipped", "so.cancel": "Sales order cancelled",
           "invoice.create": "Invoiced", "invoice.paid": "Invoice paid", "invoice.void": "Invoice voided", "po.create": "Purchase order created", "po.place": "Ordered",
           "po.receive": "Received", "po.cancel": "Purchase order cancelled", "wo.create": "Work order created", "wo.release": "Released", "wo.complete": "Completed",
           "wo.cancel": "Work order cancelled"}
QUIET_DETAIL = ("settings", "item.update", "contact.update", "bom.set", "bom.remove")


def activity_text(a) -> str:
    when = a["time"][5:16].replace("T", "  ")
    what = ACTIONS.get(a["action"], a["action"])
    detail = "" if a["action"] in QUIET_DETAIL else a["detail"]
    return f"{when}   {what}  {detail}"[:80]


# ================================================================ dashboard
class StatCard(QFrame):
    def __init__(self, title, value, note, on_click=None):
        super().__init__()
        self.setObjectName("statCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(1)
        lay.addWidget(label(title, "statLabel"))
        lay.addWidget(label(value, "statValue"))
        lay.addWidget(label(note, "statLabel"))
        self.on_click = on_click
        if on_click:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self.on_click and self.rect().contains(e.position().toPoint()):
            self.on_click()
        super().mouseReleaseEvent(e)


class DashboardPage(QWidget):
    title = "Overview"

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)
        self.heading = label("Overview", "pageTitle")
        self.sub = label("", "pageSub")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(self.heading)
        titles.addWidget(self.sub)
        outer.addLayout(titles)
        self.cards = QGridLayout()
        self.cards.setSpacing(10)
        outer.addLayout(self.cards)
        lower = QHBoxLayout()
        lower.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(label("NEEDS ATTENTION", "sectionTitle"))
        self.attention = QListWidget()
        self.attention.setObjectName("card")
        self.attention.itemActivated.connect(self._open)
        self.attention.itemClicked.connect(self._open)
        left.addWidget(self.attention, 1)
        right = QVBoxLayout()
        right.addWidget(label("RECENT ACTIVITY", "sectionTitle"))
        self.activity = QListWidget()
        self.activity.setObjectName("card")
        self.activity.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        right.addWidget(self.activity, 1)
        lower.addLayout(left, 3)
        lower.addLayout(right, 2)
        outer.addLayout(lower, 1)

    def refresh(self, keep=None):
        c = self.app.company
        if c is None:
            return
        while self.cards.count():
            w = self.cards.takeAt(0).widget()
            if w:
                w.deleteLater()
        s = c.summary()
        self.sub.setText(f"{c.setting('company_name')}. Today is {date.today():%A, %B %d}.".replace(" 0", " "))
        go = self.app.go
        plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"  # noqa: E731
        cards = [("Stock value", c.money(s["stock_value"]), "At average cost", lambda: go("stock")),
                 ("Sales to ship", c.money(s["open_sales_value"]), plural(s["open_sales"], "confirmed order"), lambda: go("sales")),
                 ("Owed to you", c.money(s["receivable"]), plural(s["open_invoices"], "open invoice"), lambda: go("invoices")),
                 ("On order", c.money(s["open_purchase_value"]), plural(s["open_purchases"], "purchase order"), lambda: go("purchasing")),
                 ("Being made", str(s["open_work"]), plural(s["open_work"], "released work order"), lambda: go("production"))]
        for i, (t, v, n, fn) in enumerate(cards):
            self.cards.addWidget(StatCard(t, v, n, fn), 0, i)
            self.cards.setColumnStretch(i, 1)
        self.attention.clear()
        eng = self.app.pages.get("engineering")
        rows = c.attention() + [("warning", d.text, d.page, d.record_id) for d in (eng.drift if eng else [])]
        marks = {"danger": "error", "warning": "warning"}
        t = self.app.theme
        for sev, text, page, rid in rows:
            it = QListWidgetItem(ic.icon(marks.get(sev, "info"), t.ui["text"], t.ui[sev], 18), text)
            it.setData(Qt.ItemDataRole.UserRole, (page, rid))
            self.attention.addItem(it)
        if not rows:
            it = QListWidgetItem(ic.icon("check", t.ui["text"], t.ui["success"], 18), "Nothing needs attention right now.")
            self.attention.addItem(it)
        self.activity.clear()
        for a in c.activity(30):
            self.activity.addItem(activity_text(a))

    def _open(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.app.go(data[0], data[1])


# ================================================================ items
class ItemsPage(ListPage):
    title = "Items"
    subtitle = "Everything you buy, make and sell"
    primary_label = "New item"
    empty_text = "No items yet. Add your first one, or import a BOM from RevisionWorx."

    def columns(self):
        return [Column("Item", lambda r: r["number"], 120), Column("Description", lambda r: r["description"], stretch=True),
                Column("Type", lambda r: r["kind"], 72, chip=True),
                Column("On hand", lambda r: fmt_qty(r["on_hand"]), 76, right=True, sort=qty_sort("on_hand")),
                Column("Free", lambda r: fmt_qty(r["on_hand"] - r["allocated"]), 70, right=True, sort=lambda r: r["on_hand"] - r["allocated"],
                       warn=lambda r: r["on_hand"] < r["allocated"]),
                Column("On order", lambda r: fmt_qty(r["on_order"]), 76, right=True, sort=qty_sort("on_order"))]

    def filters(self):
        return [("All", None), ("Bought", "buy"), ("Made", "make"), ("Below reorder", "low")]

    def load(self):
        rows = self.app.company.items(self.text())
        if self.filter_key in ("buy", "make"):
            rows = [r for r in rows if r["kind"] == self.filter_key]
        elif self.filter_key == "low":
            rows = [r for r in rows if r["reorder_point"] and r["on_hand"] - r["allocated"] + r["on_order"] < r["reorder_point"]]
        return rows

    def on_primary(self):
        d = dlg.ItemDialog(self.app)
        if d.exec():
            self.app.after_change()
            self.select_key(d.result_value)

    def on_activate(self):
        if self.current():
            self._edit(self.current())

    def _edit(self, r):
        if dlg.ItemDialog(self.app, self.app.company.item(r["id"])).exec():
            self.app.after_change()

    def fill(self, r):
        c, p, app = self.app.company, self.panel, self.app
        p.title(r["number"], r["description"])
        free = r["on_hand"] - r["allocated"]
        if r["reorder_point"] and free + r["on_order"] < r["reorder_point"]:
            what = "Make more" if r["kind"] == "make" else "Order more"
            p.add(StatusBlock(app.theme, "warning", "Below its reorder point", f"{fmt_qty(free)} free and {fmt_qty(r['on_order'])} on the way, against a reorder point of {fmt_qty(r['reorder_point'])}. {what}, or see Planning."))
        elif free < 0:
            p.add(StatusBlock(app.theme, "danger", "More is promised than you have", f"{fmt_qty(-free)} short once allocated orders ship."))
        else:
            p.add(StatusBlock(app.theme, "ok", f"{fmt_qty(r['on_hand'])} {r['unit']} on hand", f"{fmt_qty(free)} free after {fmt_qty(r['allocated'])} allocated."))
        more = [("Adjust stock…", lambda: self._adjust(r)), ("-", None),
                ("Deactivate" if r["active"] else "Reactivate", lambda: app.act(lambda: c.update_item(r["id"], active=0 if r["active"] else 1)))]
        if r["kind"] == "make":
            p.actions(("New work order", lambda: app.pages["production"].new_for(r["id"])), [("Edit", lambda: self._edit(r))], more)
        else:
            p.actions(("New purchase order", lambda: app.pages["purchasing"].new_for(r)), [("Edit", lambda: self._edit(r))], more)
        tabs = QTabWidget()
        p.add(tabs)
        o = QWidget()
        ol = QVBoxLayout(o)
        ol.setContentsMargins(0, 8, 0, 0)
        facts = [("Cost", c.money(r["cost"])), ("Price", c.money(r["price"])), ("Reorder", f"at {fmt_qty(r['reorder_point'])}, order {fmt_qty(r['reorder_qty'])}"),
                 ("Supplier", r["supplier"] or "—"), ("Lead time", f"{r['lead_days']} days"), ("Bin", r["bin"] or "—")]
        if r["kind"] == "make":
            facts.append(("Serial numbers", "Each unit made has one" if r["tracking"] == "serial" else "No"))
        if r["notes"]:
            facts.append(("Notes", r["notes"]))
        ol.addWidget(KeyValues(facts))
        ol.addStretch(1)
        tabs.addTab(o, "Details")
        tabs.addTab(self._bom_tab(r), "BOM")
        tabs.addTab(self._engineering_tab(r), "Engineering")
        moves = c.moves(r["id"], 40)
        m = MiniTable(["When", "Change", "Kind", "Ref"], [(x["time"][:10], fmt_qty(x["qty"]), MOVE_KINDS.get(x["kind"], x["kind"]),
                                                          " · ".join(t for t in (x["ref"] or x["note"], x["serial"]) if t)) for x in moves],
                      right=(1,), max_rows=8)
        h = QWidget()
        hl = QVBoxLayout(h)
        hl.setContentsMargins(0, 8, 0, 0)
        hl.addWidget(m if moves else label("No stock movements yet.", "muted"))
        hl.addStretch(1)
        tabs.addTab(h, "Ledger")
        used = c.where_used(r["id"])
        if used:
            p.section("Used in")
            p.add(MiniTable(["Item", "Description", "Qty"], [(u["number"], u["description"], fmt_qty(u["qty"])) for u in used], right=(2,),
                            on_activate=lambda i: app.go("items", used[i]["id"]), max_rows=5))

    def _bom_tab(self, r):
        c, app = self.app.company, self.app
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 0)
        lines = c.bom(r["id"])
        if lines:
            t = MiniTable(["Find", "Item", "Description", "Qty"], [(b["find_number"], b["number"], b["description"], f'{fmt_qty(b["qty"])}') for b in lines], right=(3,),
                          on_activate=lambda i: app.go("items", lines[i]["child_id"]), max_rows=9)
            t.horizontalHeader().setSectionResizeMode(1, t.horizontalHeader().ResizeMode.ResizeToContents)
            t.horizontalHeader().setSectionResizeMode(2, t.horizontalHeader().ResizeMode.Stretch)
            l.addWidget(t)
            l.addWidget(label(f"Build cost from components: {c.money(c.rollup_cost(r['id']))}", "small"))
        else:
            l.addWidget(label("No bill of materials.", "muted"))
        if r["bom_rw_label"]:
            l.addWidget(label(f"Imported from RevisionWorx, Rev {r['bom_rw_label']}", "small"))
        row = QHBoxLayout()
        row.addWidget(button("Add line", lambda: self._add_bom(r)))
        if lines:
            row.addWidget(button("Remove line", lambda: self._remove_bom(t, lines)))
        row.addWidget(button("Import from RevisionWorx…", lambda: app.pages["engineering"].import_bom_flow(r)))
        row.addStretch(1)
        l.addLayout(row)
        l.addStretch(1)
        return w

    def _add_bom(self, r):
        if dlg.BomLineDialog(self.app, r["id"]).exec():
            self.app.after_change()

    def _remove_bom(self, table, lines):
        row = table.selected_row()
        if row < 0:
            self.app.toast("Select a line first.")
            return
        self.app.act(lambda: self.app.company.remove_bom_line(lines[row]["id"]))

    def _engineering_tab(self, r):
        app = self.app
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 0, 0)
        if r["rw_document"]:
            # What RevisionWorx last said, from the background fetch: moving through a list must never wait on a program.
            eng = app.pages["engineering"]
            doc = next((d for d in eng.docs if d.id == r["rw_document"]), None)
            name = r["rw_number"] or r["rw_document"]
            if doc:
                title, kind = doc.title or name, "ok" if doc.released_label else "warning"
                text = f"Released: Rev {doc.released_label}" if doc.released_label else f"Nothing released yet. Latest is Rev {doc.latest_label or '?'} ({state_name(doc.latest_state)})"
            elif eng.error or not app.company.setting("rw_workspace"):
                title, kind, text = name, "neutral", f"Linked to {name}. RevisionWorx isn't connected, so its revision can't be checked."
            elif eng.fetched:
                title, kind, text = name, "warning", f"Linked to {name}, but RevisionWorx has no such document now."
            else:
                title, kind, text = name, "neutral", f"Linked to {name}. Asking RevisionWorx…"
            l.addWidget(StatusBlock(app.theme, kind, title, text))
            for d in eng.drift:
                if d.page == "items" and d.record_id == r["id"]:
                    l.addWidget(StatusBlock(app.theme, "warning", "Out of step with engineering", d.text))
            if doc:
                l.addWidget(KeyValues([("Number", doc.number or "—"), ("File", doc.rel_path), ("Latest", f"Rev {doc.latest_label} ({state_name(doc.latest_state)})")]))
            row = QHBoxLayout()
            row.addWidget(button("Change link…", lambda: app.pages["engineering"].link_flow(r)))
            row.addWidget(button("Remove link", lambda: app.act(lambda: app.company.update_item(r["id"], rw_document="", rw_number=""))))
            row.addStretch(1)
            l.addLayout(row)
        else:
            l.addWidget(label("Link this item to its controlled document, and work orders will record which released revision they build.", "muted", wrap=True))
            row = QHBoxLayout()
            row.addWidget(button("Link a document…", lambda: app.pages["engineering"].link_flow(r)))
            row.addStretch(1)
            l.addLayout(row)
        l.addStretch(1)
        return w

    def _adjust(self, r):
        if dlg.AdjustDialog(self.app, self.app.company.item(r["id"])).exec():
            self.app.after_change()


# ================================================================ contacts
class ContactsPage(ListPage):
    kind = "customer"
    primary_label = ""

    def columns(self):
        return [Column("Name", lambda r: r["name"], stretch=True), Column("Contact", lambda r: r["contact"], 130),
                Column("Email", lambda r: r["email"], 170), Column("Phone", lambda r: r["phone"], 100)]

    def load(self):
        return self.app.company.contacts(self.kind, self.text())

    def on_primary(self):
        d = dlg.ContactDialog(self.app, self.kind)
        if d.exec():
            self.app.after_change()
            self.select_key(d.result_value)

    def on_activate(self):
        r = self.current()
        if r and dlg.ContactDialog(self.app, self.kind, r).exec():
            self.app.after_change()

    def fill(self, r):
        p, c = self.panel, self.app.company
        p.title(r["name"], r["contact"])
        new_label = "New sales order" if self.kind == "customer" else "New purchase order"
        target = "sales" if self.kind == "customer" else "purchasing"
        p.actions((new_label, lambda: self.app.pages[target].new_for_party(r["id"])), [("Edit", self.on_activate)])
        p.add(KeyValues([("Email", r["email"] or "—"), ("Phone", r["phone"] or "—"), ("Address", r["address"] or "—"), ("Terms", f"{r['terms_days']} days")]
                        + ([("Notes", r["notes"])] if r["notes"] else [])))
        p.section("Orders")
        if self.kind == "customer":
            orders = [o for o in c.sales_orders() if o["customer_id"] == r["id"]]
        else:
            orders = [o for o in c.purchase_orders() if o["supplier_id"] == r["id"]]
        if orders:
            p.add(MiniTable(["Order", "Date", "Status", "Total"], [(o["number"], o["order_date"], o["status"].capitalize(), c.money(o["total"])) for o in orders], right=(3,),
                            on_activate=lambda i: self.app.go(target, orders[i]["id"]), max_rows=8))
        else:
            p.add(label("No orders yet.", "muted"))


class CustomersPage(ContactsPage):
    kind = "customer"
    title = "Customers"
    subtitle = "Who you sell to"
    primary_label = "New customer"
    empty_text = "No customers yet."


class SuppliersPage(ContactsPage):
    kind = "supplier"
    title = "Suppliers"
    subtitle = "Who you buy from"
    primary_label = "New supplier"
    empty_text = "No suppliers yet."


# ================================================================ sales
def _lines_section(page, p, lines, editable, right_cols, headers, cells, remove_fn, add_fn):
    p.section("Lines")
    if lines:
        t = MiniTable(headers, [cells(l) for l in lines], right=right_cols, max_rows=10)
        p.add(t)
    else:
        t = None
        p.add(label("No lines yet.", "muted"))
    if editable:
        row = QHBoxLayout()
        row.addWidget(button("Add line", add_fn))
        if lines:
            def rm():
                r = t.selected_row()
                if r < 0:
                    page.app.toast("Select a line first.")
                    return
                page.app.act(lambda: remove_fn(lines[r]["id"]))
            row.addWidget(button("Remove line", rm))
        row.addStretch(1)
        h = QWidget()
        h.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        p.add(h)


class SalesPage(ListPage):
    title = "Sales orders"
    subtitle = "What customers have asked for"
    primary_label = "New sales order"
    empty_text = "No sales orders yet."

    def columns(self):
        return [Column("Order", lambda r: r["number"], 100), Column("Customer", lambda r: r["customer"], stretch=True),
                Column("Due", lambda r: r["due_date"], 100), Column("Status", lambda r: r["status"], 96, chip=True),
                Column("Total", lambda r: self.app.company.money(r["total"]), 96, right=True, sort=qty_sort("total"))]

    def filters(self):
        return [("All", None), ("Draft", "draft"), ("Confirmed", "confirmed"), ("Shipped", "shipped")]

    def load(self):
        return self.app.company.sales_orders(self.filter_key, self.text())

    def filter_counts(self):
        rows = self.app.company.sales_orders()
        return {"draft": sum(r["status"] == "draft" for r in rows), "confirmed": sum(r["status"] == "confirmed" for r in rows)}

    def on_primary(self):
        d = dlg.OrderDialog(self.app, "sale")
        if d.exec():
            self.app.after_change()
            self.search.clear()
            self.select_key(d.result_value)

    def new_for_party(self, party_id):
        self.app.go("sales")
        d = dlg.OrderDialog(self.app, "sale")
        i = d.party.findData(party_id)
        if i >= 0:
            d.party.setCurrentIndex(i)
        if d.exec():
            self.app.after_change()
            self.select_key(d.result_value)

    def fill(self, r):
        c, p, app = self.app.company, self.panel, self.app
        lines = c.sales_lines(r["id"])
        p.title(r["number"], r["customer"] + (f" · {r['reference']}" if r["reference"] else ""))
        status = r["status"]
        to_ship = sum(l["qty"] - l["shipped"] for l in lines)
        to_inv = sum(l["shipped"] - l["invoiced"] for l in lines)
        more = [("Export PDF…", lambda: app.export_pdf("sale", r["id"], r["number"]))]
        if status == "draft":
            p.add(StatusBlock(app.theme, "neutral", "Draft", "Nothing is reserved yet. Confirm it to allocate stock and plan for it."))
            p.actions(("Confirm order", lambda: app.act(lambda: c.confirm_sales_order(r["id"]))), (), more + [("-", None), ("Cancel order", lambda: self._cancel(r))])
        elif status == "confirmed":
            short = [l for l in lines if l["qty"] - l["shipped"] > c.on_hand(l["item_id"])]
            if short:
                p.add(StatusBlock(app.theme, "warning", "Waiting for stock", ", ".join(l["number"] for l in short[:4]) + " can't ship in full yet. Partial shipments are allowed."))
            else:
                p.add(StatusBlock(app.theme, "info", "Ready to ship", f"{fmt_qty(to_ship)} left to ship, and it's all in stock."))
            if to_inv:
                more = [("Create invoice for what's shipped", lambda: self._invoice(r))] + more
            p.actions(("Ship…", lambda: self._ship(r, lines)), (), more + [("-", None), ("Cancel order", lambda: self._cancel(r))])
        elif status == "shipped" and to_inv:
            p.add(StatusBlock(app.theme, "info", "Shipped, not invoiced", f"{fmt_qty(to_inv)} is ready to invoice."))
            p.actions(("Create invoice", lambda: self._invoice(r)), (), more)
        elif status == "shipped":
            p.add(StatusBlock(app.theme, "ok", "Complete", "Shipped and invoiced."))
            p.actions(None, (), more)
        else:
            p.add(StatusBlock(app.theme, "neutral", "Cancelled"))
            p.actions(None, (), more)
        p.add(KeyValues([("Order date", r["order_date"]), ("Due", r["due_date"] or "—"), ("Total", c.money(r["total"]))]))
        _lines_section(self, p, lines, status == "draft", (2, 3, 4), ["Item", "Description", "Qty", "Shipped", "Price"],
                       lambda l: (l["number"], l["description"], fmt_qty(l["qty"]), fmt_qty(l["shipped"]), c.money(l["unit_price"])), c.remove_sales_line,
                       lambda: self._add_line(r))
        invs = [v for v in c.invoices() if v["order_id"] == r["id"]]
        if invs:
            p.section("Invoices")
            p.add(MiniTable(["Invoice", "Issued", "Status", "Total"], [(v["number"], v["issued"], v["status"], c.money(v["total"])) for v in invs], right=(3,),
                            on_activate=lambda i: app.go("invoices", invs[i]["id"]), max_rows=4))

    def _add_line(self, r):
        if dlg.LineDialog(self.app, "sale", r["id"]).exec():
            self.app.after_change()

    def _ship(self, r, lines):
        rows = [{"id": l["id"], "number": l["number"], "description": l["description"], "left": l["qty"] - l["shipped"]} for l in lines if l["qty"] > l["shipped"]]
        d = dlg.QuantitiesDialog(self.app, f"Ship {r['number']}", "Stock leaves as soon as you ship. Change a quantity to ship part of a line.",
                                 rows, lambda q: self.app.company.ship_sales_order(r["id"], q), "Ship")
        if d.exec():
            self.app.after_change()

    def _invoice(self, r):
        new = self.app.act(lambda: self.app.company.invoice_sales_order(r["id"]))
        if new:
            self.app.toast("Invoice created", "success")

    def _cancel(self, r):
        if dlg.confirm(self.app, "Cancel order", f"Cancel {r['number']}?", "Cancel order"):
            self.app.act(lambda: self.app.company.cancel_sales_order(r["id"]))


class InvoicesPage(ListPage):
    title = "Invoices"
    subtitle = "What customers owe you"
    empty_text = "No invoices yet. Create one from a shipped sales order."

    def _status(self, r):
        return "overdue" if r["status"] == "open" and r["due"] < _today() else r["status"]

    def columns(self):
        return [Column("Invoice", lambda r: r["number"], 100), Column("Customer", lambda r: r["customer"], stretch=True),
                Column("Due", lambda r: r["due"], 100), Column("Status", self._status, 90, chip=True),
                Column("Total", lambda r: self.app.company.money(r["total"]), 96, right=True, sort=qty_sort("total"))]

    def filters(self):
        return [("All", None), ("Open", "open"), ("Paid", "paid"), ("Void", "void")]

    def load(self):
        return self.app.company.invoices(self.filter_key, self.text())

    def filter_counts(self):
        return {"open": sum(r["status"] == "open" for r in self.app.company.invoices())}

    def fill(self, r):
        c, p, app = self.app.company, self.panel, self.app
        p.title(r["number"], r["customer"])
        more = [("Export PDF…", lambda: app.export_pdf("invoice", r["id"], r["number"]))]
        st = self._status(r)
        if st == "overdue":
            p.add(StatusBlock(app.theme, "danger", "Overdue", f"Was due {r['due']}."))
        elif st == "open":
            p.add(StatusBlock(app.theme, "warning", "Open", f"Due {r['due']}."))
        elif st == "paid":
            p.add(StatusBlock(app.theme, "ok", "Paid", f"Paid {r['paid_on']}."))
        else:
            p.add(StatusBlock(app.theme, "neutral", "Void", "Its quantities can be invoiced again from the order."))
        if r["status"] == "open":
            p.actions(("Mark as paid", lambda: app.act(lambda: c.mark_invoice_paid(r["id"]))), (),
                      more + [("-", None), ("Void invoice", lambda: self._void(r))])
        else:
            p.actions(None, (), more)
        p.add(KeyValues([("Issued", r["issued"]), ("Due", r["due"]), ("Order", r["order_number"]), ("Subtotal", c.money(r["subtotal"])),
                         (f"Tax ({r['tax_percent']}%)", c.money(r["tax"])), ("Total", c.money(r["total"]))]))
        p.section("Lines")
        p.add(MiniTable(["Item", "Description", "Qty", "Amount"],
                        [(l["number"], l["description"], fmt_qty(l["qty"]), c.money(line_total(l["qty"], l["unit_price"]))) for l in c.invoice_lines(r["id"])], right=(2, 3)))

    def _void(self, r):
        if dlg.confirm(self.app, "Void invoice", f"Void {r['number']}? Its number stays used, and its quantities can be invoiced again.", "Void invoice"):
            self.app.act(lambda: self.app.company.void_invoice(r["id"]))


# ================================================================ purchasing
class PurchasingPage(ListPage):
    title = "Purchase orders"
    subtitle = "What you've asked suppliers for"
    primary_label = "New purchase order"
    empty_text = "No purchase orders yet."

    def _status(self, r):
        return "overdue" if r["status"] == "ordered" and r["due_date"] and r["due_date"] < _today() else r["status"]

    def columns(self):
        return [Column("Order", lambda r: r["number"], 100), Column("Supplier", lambda r: r["supplier"], stretch=True),
                Column("Due", lambda r: r["due_date"], 100), Column("Status", self._status, 92, chip=True),
                Column("Total", lambda r: self.app.company.money(r["total"]), 96, right=True, sort=qty_sort("total"))]

    def filters(self):
        return [("All", None), ("Draft", "draft"), ("Ordered", "ordered"), ("Received", "received")]

    def load(self):
        return self.app.company.purchase_orders(self.filter_key, self.text())

    def filter_counts(self):
        rows = self.app.company.purchase_orders()
        return {"draft": sum(r["status"] == "draft" for r in rows), "ordered": sum(r["status"] == "ordered" for r in rows)}

    def on_primary(self):
        d = dlg.OrderDialog(self.app, "purchase")
        if d.exec():
            self.app.after_change()
            self.search.clear()
            self.select_key(d.result_value)

    def new_for_party(self, party_id):
        self.app.go("purchasing")
        d = dlg.OrderDialog(self.app, "purchase")
        i = d.party.findData(party_id)
        if i >= 0:
            d.party.setCurrentIndex(i)
        if d.exec():
            self.app.after_change()
            self.select_key(d.result_value)

    def new_for(self, item):
        if item["supplier_id"]:
            self.new_for_party(item["supplier_id"])
        else:
            self.app.go("purchasing")
            self.on_primary()

    def fill(self, r):
        c, p, app = self.app.company, self.panel, self.app
        lines = c.purchase_lines(r["id"])
        p.title(r["number"], r["supplier"] + (f" · {r['reference']}" if r["reference"] else ""))
        st = self._status(r)
        more = [("Export PDF…", lambda: app.export_pdf("purchase", r["id"], r["number"]))]
        if st == "draft":
            p.add(StatusBlock(app.theme, "neutral", "Draft", "Mark it as ordered once it has gone to the supplier."))
            p.actions(("Mark as ordered", lambda: app.act(lambda: c.place_purchase_order(r["id"]))), (), more + [("-", None), ("Cancel order", lambda: self._cancel(r))])
        elif r["status"] == "ordered":
            left = sum(l["qty"] - l["received"] for l in lines)
            if st == "overdue":
                p.add(StatusBlock(app.theme, "danger", "Late", f"Was due {r['due_date']}, with {fmt_qty(left)} outstanding."))
            else:
                p.add(StatusBlock(app.theme, "info", "On order", f"{fmt_qty(left)} outstanding."))
            p.actions(("Receive…", lambda: self._receive(r, lines)), (), more + [("-", None), ("Cancel order", lambda: self._cancel(r))])
        elif r["status"] == "received":
            p.add(StatusBlock(app.theme, "ok", "Received in full"))
            p.actions(None, (), more)
        else:
            p.add(StatusBlock(app.theme, "neutral", "Cancelled"))
            p.actions(None, (), more)
        p.add(KeyValues([("Order date", r["order_date"]), ("Due", r["due_date"] or "—"), ("Total", c.money(r["total"]))]))
        _lines_section(self, p, lines, r["status"] == "draft", (2, 3, 4), ["Item", "Description", "Qty", "Rcvd", "Cost"],
                       lambda l: (l["number"], l["description"], fmt_qty(l["qty"]), fmt_qty(l["received"]), c.money(l["unit_cost"])), c.remove_purchase_line,
                       lambda: self._add_line(r))

    def _add_line(self, r):
        if dlg.LineDialog(self.app, "purchase", r["id"]).exec():
            self.app.after_change()

    def _receive(self, r, lines):
        rows = [{"id": l["id"], "number": l["number"], "description": l["description"], "left": l["qty"] - l["received"]} for l in lines if l["qty"] > l["received"]]
        d = dlg.QuantitiesDialog(self.app, f"Receive {r['number']}", "Stock comes in at the order's cost. Change a quantity if only part arrived.",
                                 rows, lambda q: self.app.company.receive_purchase_order(r["id"], q), "Receive")
        if d.exec():
            self.app.after_change()

    def _cancel(self, r):
        if dlg.confirm(self.app, "Cancel order", f"Cancel {r['number']}?", "Cancel order"):
            self.app.act(lambda: self.app.company.cancel_purchase_order(r["id"]))


# ================================================================ production
class ProductionPage(ListPage):
    title = "Work orders"
    subtitle = "What you're making"
    primary_label = "New work order"
    empty_text = "No work orders yet."

    def columns(self):
        return [Column("Order", lambda r: r["number"], 100), Column("Item", lambda r: r["item_number"], 110),
                Column("Description", lambda r: r["description"], stretch=True),
                Column("Qty", lambda r: f'{fmt_qty(r["done"])} / {fmt_qty(r["qty"])}', 70, right=True),
                Column("Rev", lambda r: r["build_rw_label"], 44), Column("Status", lambda r: r["status"], 92, chip=True)]

    def filters(self):
        return [("All", None), ("Draft", "draft"), ("Released", "released"), ("Complete", "complete")]

    def load(self):
        return self.app.company.work_orders(self.filter_key, self.text())

    def filter_counts(self):
        rows = self.app.company.work_orders()
        return {"draft": sum(r["status"] == "draft" for r in rows), "released": sum(r["status"] == "released" for r in rows)}

    def on_primary(self):
        d = dlg.WorkOrderDialog(self.app)
        if d.exec():
            self.app.after_change()
            self.search.clear()
            self.select_key(d.result_value)

    def new_for(self, item_id):
        self.app.go("production")
        d = dlg.WorkOrderDialog(self.app, item_id)
        if d.exec():
            self.app.after_change()
            self.select_key(d.result_value)

    def fill(self, r):
        c, p, app = self.app.company, self.panel, self.app
        p.title(r["number"], f"{fmt_qty(r['qty'])} × {r['item_number']} {r['description']}")
        comps = c.work_order_components(r["id"])
        short = [b for b in comps if b["needed"] > b["on_hand"]]
        units = c.units_built(r["id"])
        rw_on = bool(c.setting("rw_workspace"))
        unregistered = [u for u in units if not u["rw_unit"]] if rw_on else []
        register = ("Register in RevisionWorx", lambda: self._register(r))
        if r["status"] == "draft":
            if short:
                p.add(StatusBlock(app.theme, "warning", "Parts are short", ", ".join(b["number"] for b in short[:4]) + ". You can still release it; completing it needs the parts."))
            else:
                p.add(StatusBlock(app.theme, "neutral", "Draft", "Release it to allocate parts and record the revision being built."))
            p.actions(("Release", lambda: self._release(r)), (), [("Cancel work order", lambda: self._cancel(r))])
        elif r["status"] == "released":
            if r["build_rw_note"]:
                p.add(StatusBlock(app.theme, "warning", "Released without a controlled revision", r["build_rw_note"]))
            elif r["build_rw_label"]:
                p.add(StatusBlock(app.theme, "info", f"Building to Rev {r['build_rw_label']}", "Recorded from RevisionWorx when this was released."))
            if short:
                p.add(StatusBlock(app.theme, "warning", "Parts are short", ", ".join(f"{b['number']} ({fmt_qty(b['on_hand'])} of {fmt_qty(b['needed'])})" for b in short[:4])))
            if unregistered:
                p.add(self._unregistered_block(units, unregistered))
            p.actions(("Complete…", lambda: self._complete(r)), [register] if unregistered else (),
                      [("Cancel work order", lambda: self._cancel(r))])
        elif r["status"] == "complete":
            if unregistered:
                p.add(self._unregistered_block(units, unregistered))
                p.actions(register)
            else:
                p.add(StatusBlock(app.theme, "ok", "Complete", f"Built to Rev {r['build_rw_label']}." if r["build_rw_label"] else "Finished goods are in stock."))
        else:
            p.add(StatusBlock(app.theme, "neutral", "Cancelled"))
        p.add(KeyValues([("Made", f"{fmt_qty(r['done'])} of {fmt_qty(r['qty'])} {r['unit']}"), ("Created", r["created"]), ("Due", r["due_date"] or "—"),
                         ("Document", r["rw_number"] or "Not linked")]))
        if units:
            p.section(f"Units built ({len(units)})")
            if rw_on:
                rows = [(u["serial"], u["made"], "Registered" if u["rw_unit"] else "Not registered") for u in units]
                p.add(MiniTable(["Serial", "Made", "RevisionWorx"], rows, max_rows=8))
            else:
                p.add(MiniTable(["Serial", "Made"], [(u["serial"], u["made"]) for u in units], max_rows=8))
        p.section("Components for what's left")
        if comps:
            p.add(MiniTable(["Item", "Description", "Need", "Have"], [(b["number"], b["description"], fmt_qty(b["needed"]), fmt_qty(b["on_hand"])) for b in comps], right=(2, 3),
                            on_activate=lambda i: app.go("items", comps[i]["child_id"]), max_rows=8))
        else:
            p.add(label("This item has no bill of materials.", "muted"))

    def _release(self, r):
        app = self.app
        stamp = {"rw_document": "", "rw_revision": "", "rw_label": "", "rw_note": ""}
        if r["rw_document"]:
            client = app.rw_client()
            try:
                if not client or not client.available:
                    raise rw.RevisionWorxError("RevisionWorx isn't connected.")
                det = client.detail(r["rw_document"])
                stamp = rw.build_stamp(det)
                if det.released is None and not dlg.confirm(
                        app, "No released revision", f"{det.document.number or det.document.title} has no released revision. Release this work order anyway? That will be recorded on it.", "Release anyway"):
                    return
            except rw.RevisionWorxError as e:
                if not dlg.confirm(app, "Can't check the revision", f"{e}\n\nRelease without recording a revision? That will be recorded on it.", "Release anyway"):
                    return
                stamp = {"rw_document": r["rw_document"], "rw_revision": "", "rw_label": "", "rw_note": "Released while RevisionWorx couldn't be checked"}
        app.act(lambda: app.company.release_work_order(r["id"], **stamp))

    def _complete(self, r):
        app = self.app
        d = dlg.CompleteDialog(app, r, app.company.item(r["item_id"]))
        if d.exec():
            app.after_change()
            if app.company.units_built(r["id"]) and app.company.setting("rw_workspace"):
                self._register(r)

    def _register(self, r):
        """Register in RevisionWorx the units this work order made that it doesn't have yet (the one thing OpenMeridian
        writes there). What RevisionWorx refuses stays listed on the work order, with why."""
        app = self.app
        client = app.rw_client()
        if not client or not client.available:
            app.toast("Not registered in RevisionWorx: it isn't connected. Use Register in RevisionWorx once it is.", "warning")
            app.after_change()
            return
        out = app.run_guarded(lambda: app.company.register_units(r["id"], client))
        if out is None:
            app.after_change()
            return
        if out["refused"]:
            why = "; ".join(f"{', '.join(s)}: {w}" for s, w in out["refused"])
            app.error(f"RevisionWorx didn't register {why}\n\nNothing about them changed in RevisionWorx. They stay "
                      "listed on the work order, not registered; register them again once that's sorted.")
        elif out["registered"]:
            app.toast(f"Registered in RevisionWorx: {', '.join(out['registered'])}", "success")
        app.after_change()

    def _unregistered_block(self, units, unregistered):
        """Units made here that RevisionWorx's unit register doesn't have yet, and why, as RevisionWorx said it."""
        n = len(unregistered)
        if n == 1:
            what, unsent = f"{unregistered[0]['serial']} isn't", "It hasn't been sent yet."
        else:
            what = f"The {n} units made aren't" if n == len(units) else f"{n} of the {len(units)} units made aren't"
            unsent = "They haven't been sent yet."
        why = next((u["rw_note"] for u in unregistered if u["rw_note"]), "")
        why = why[:1].upper() + why[1:]
        return StatusBlock(self.app.theme, "warning", "Not in RevisionWorx yet",
                           f"{what} in its unit register. {why or unsent}")

    def _cancel(self, r):
        if dlg.confirm(self.app, "Cancel work order", f"Cancel {r['number']}?", "Cancel work order"):
            self.app.act(lambda: self.app.company.cancel_work_order(r["id"]))


# ================================================================ planning
class PlanningPage(ListPage):
    title = "Planning"
    subtitle = "What to buy and make to cover demand and reorder points"
    primary_label = "Create all orders"
    empty_text = "Nothing to buy or make. Stock and open orders cover every demand."
    select_text = "Select a row to see why it's suggested."

    def columns(self):
        return [Column("Item", lambda r: r.number, 110), Column("Description", lambda r: r.description, stretch=True), Column("Do", lambda r: r.kind, 66, chip=True),
                Column("Qty", lambda r: fmt_qty(r.qty), 70, right=True, sort=lambda r: r.qty), Column("Supplier", lambda r: r.supplier, 150)]

    def key_of(self, row):
        return row.item_id

    def load(self):
        t = self.text().casefold()
        rows = planning.plan(self.app.company)
        return [r for r in rows if t in r.number.casefold() or t in r.description.casefold()]

    def fill(self, r):
        p, app = self.panel, self.app
        p.title(r.number, r.description)
        verb = "Make" if r.kind == "make" else "Buy"
        p.add(StatusBlock(app.theme, "warning", f"{verb} {fmt_qty(r.qty)} {r.unit}", f"Earliest {r.earliest} if {'started' if r.kind == 'make' else 'ordered'} today."))
        p.add(KeyValues([("Demand", fmt_qty(r.demand)), ("On hand", fmt_qty(r.on_hand)), ("On order", fmt_qty(r.on_order)), ("Reorder point", fmt_qty(r.reorder_point)),
                         ("Supplier", r.supplier or ("—" if r.kind == "make" else "None set")), ("Unit cost", app.company.money(r.unit_cost))]))
        p.actions(("Create order for this", lambda: self._create([r])), [("Open item", lambda: app.go("items", r.item_id))])
        if r.kind == "buy" and r.supplier_id is None:
            p.add(label("Set a supplier on this item first, so it can go on a purchase order.", "small", wrap=True))

    def on_primary(self):
        rows = planning.plan(self.app.company)
        if not rows:
            self.app.toast("Nothing to order.")
            return
        if dlg.confirm(self.app, "Create orders", f"Create draft orders for {len(rows)} suggestions? Nothing goes to a supplier until you mark it as ordered.", "Create drafts"):
            self._create(rows)

    def _create(self, rows):
        res = self.app.act(lambda: planning.create_orders(self.app.company, rows))
        if res:
            msg = f"{len(res['purchase_orders'])} purchase and {len(res['work_orders'])} work orders created as drafts."
            if res["no_supplier"]:
                msg += " No supplier set for: " + ", ".join(res["no_supplier"])
            self.app.toast(msg, "warning" if res["no_supplier"] else "success")


# ================================================================ stock ledger
class StockPage(ListPage):
    title = "Stock ledger"
    subtitle = "Every movement, permanently. Corrections are new entries, never edits."
    show_panel = False
    empty_text = "No stock movements yet."

    def columns(self):
        return [Column("When", lambda r: r["time"].replace("T", " ")[:16], 150), Column("Item", lambda r: r["number"], 110),
                Column("Description", lambda r: r["description"], stretch=True), Column("Kind", lambda r: MOVE_KINDS.get(r["kind"], r["kind"]), 90),
                Column("Change", lambda r: fmt_qty(r["qty"]), 76, right=True, sort=qty_sort("qty")),
                Column("Cost", lambda r: self.app.company.money(r["unit_cost"]), 80, right=True, sort=qty_sort("unit_cost")),
                Column("Reference", lambda r: r["ref"] or r["note"], 180), Column("By", lambda r: r["user"], 80)]

    def filters(self):
        return [("All", None), ("Receipts", "receipt"), ("Shipments", "shipment"), ("Production", "produce"), ("Consumed", "consume"), ("Adjustments", "adjust")]

    def load(self):
        t = self.text().casefold()
        rows = self.app.company.moves(limit=3000)
        if self.filter_key:
            rows = [r for r in rows if r["kind"] == self.filter_key]
        return [r for r in rows if t in r["number"].casefold() or t in r["description"].casefold() or t in r["ref"].casefold()]

    def key_of(self, row):
        return row["id"]

    def on_activate(self):
        r = self.current()
        if r:
            self.app.go("items", r["item_id"])


# ================================================================ engineering (RevisionWorx)
class EngineeringPage(ListPage):
    title = "RevisionWorx"
    subtitle = "Controlled documents from RevisionWorx. Read only: engineering's record stays there."
    empty_text = "No documents."
    no_match_text = "No documents match."
    select_text = "Select a document to see its revisions."

    def __init__(self, app):
        self.docs = []
        self.changes = []
        self.drift = []
        self.error = ""
        self.fetched = False
        super().__init__(app)

    def add_header_buttons(self, head):
        self.refresh_btn = button("Refresh", self.fetch)
        self.open_btn = button("Open RevisionWorx", self.app.open_revisionworx)
        head.addWidget(self.refresh_btn)
        head.addWidget(self.open_btn)

    def columns(self):
        return [Column("Number", lambda r: r.number, 110), Column("Title", lambda r: r.title, stretch=True), Column("Type", lambda r: r.type_id, 90),
                Column("Latest", lambda r: r.latest_label, 56), Column("State", lambda r: state_name(r.latest_state), 120),
                Column("Released", lambda r: r.released_label or "—", 70)]

    def filters(self):
        return [("All", None), ("Released", "released"), ("Not released", "unreleased")]

    def key_of(self, row):
        return row.id

    def load(self):
        t = self.text().casefold()
        rows = self.docs
        if self.filter_key == "released":
            rows = [d for d in rows if d.released_label]
        elif self.filter_key == "unreleased":
            rows = [d for d in rows if not d.released_label]
        return [d for d in rows if t in d.number.casefold() or t in d.title.casefold() or t in d.rel_path.casefold()]

    def refresh(self, keep=None):
        if self.app.company is None:
            return
        ws = self.app.company.setting("rw_workspace")
        if not ws:
            self.empty_text = "Not connected. Choose your RevisionWorx workspace in Settings to link items, stamp work orders and import BOMs."
        elif self.error:
            self.empty_text = self.error
        else:
            self.empty_text = "This RevisionWorx workspace has no documents yet."
        self.sub.setText(f"Controlled documents from {ws}. Read only." if ws else "Connect RevisionWorx in Settings")
        super().refresh(keep)

    def fetch(self):
        """Ask RevisionWorx in the background, so the window never waits on it."""
        client = self.app.rw_client()
        self.docs, self.changes, self.drift, self.error, self.fetched = [], [], [], "", False
        if client is None:
            self.app.update_rw_status("", [])
            self.refresh()
            return
        company_path = self.app.company.path

        def work():
            from ..company import Company
            comp = Company.open(company_path)
            try:
                return client.documents(), client.changes(), rw.find_drift(comp, client)
            finally:
                comp.close()

        def done(res, err):
            if self.app.company is None or self.app.company.path != company_path:
                return      # another company was opened while RevisionWorx was answering: this isn't about it
            if err:
                self.error = str(err)
            else:
                self.docs, self.changes, self.drift = res
                self.fetched = True
            self.app.update_rw_status(self.error, self.drift)
            self.refresh()
            current = self.app.pages.get(self.app.current_key)
            if current is not self:
                current.refresh()       # the Overview and an open Engineering tab show what just arrived
        self.app.background(work, done)

    def fill(self, d):
        p, app = self.panel, self.app
        p.title(d.title or d.number, f"{d.number} · {d.rel_path}" if d.number else d.rel_path)
        if self.drift:
            p.add(StatusBlock(app.theme, "warning", f"{len(self.drift)} record{'s' if len(self.drift) != 1 else ''} out of step with engineering", "; ".join(x.text for x in self.drift[:3])))
        if d.released_label:
            p.add(StatusBlock(app.theme, "ok", f"Released: Rev {d.released_label}", f"Latest is Rev {d.latest_label} ({state_name(d.latest_state)})."))
        else:
            p.add(StatusBlock(app.theme, "warning", "Nothing released", f"Latest is Rev {d.latest_label or '—'} ({state_name(d.latest_state)})."))
        linked = [i for i in app.company.items() if i["rw_document"] == d.id or i["bom_rw_document"] == d.id]
        p.actions(("Import BOM to an item…", lambda: self.import_bom_flow(None, d.id)), [("Link to item…", lambda: self._link_to_item(d))])
        if d.checked_out_by:
            p.add(label(f"Checked out by {d.checked_out_by}", "small"))
        if linked:
            p.section("Linked items")
            p.add(MiniTable(["Item", "Description"], [(i["number"], i["description"]) for i in linked], on_activate=lambda n: app.go("items", linked[n]["id"]), max_rows=6))
        if self.changes:
            p.section("Open engineering changes")
            p.add(MiniTable(["Number", "Title", "Status"], [(c.number, c.title, c.status.replace("_", " ").capitalize()) for c in self.changes], max_rows=6))

    def link_flow(self, item):
        client = self.app.rw_client()
        if client is None or not client.available:
            self.app.toast("Connect RevisionWorx in Settings first.", "warning")
            return
        docs = self.app.run_guarded(client.documents)
        if docs is None:
            return
        d = dlg.PickDialog(self.app, f"Link {item['number']} to a document", [(f"{x.number or '—'}   {x.title}   Rev {x.released_label or x.latest_label}", x) for x in docs], "Search documents")
        if d.exec() and d.chosen:
            self.app.act(lambda: self.app.company.update_item(item["id"], rw_document=d.chosen.id, rw_number=d.chosen.number or d.chosen.title))

    def _link_to_item(self, doc):
        rows = [(f"{i['number']}   {i['description']}", i) for i in self.app.company.items()]
        d = dlg.PickDialog(self.app, f"Link {doc.number or doc.title} to an item", rows, "Search items")
        if d.exec() and d.chosen:
            self.app.act(lambda: self.app.company.update_item(d.chosen["id"], rw_document=doc.id, rw_number=doc.number or doc.title))

    def import_bom_flow(self, item=None, doc_id=None):
        app = self.app
        client = app.rw_client()
        if client is None or not client.available:
            app.toast("Connect RevisionWorx in Settings first.", "warning")
            return
        if doc_id is None:
            docs = app.run_guarded(client.documents)
            if docs is None:
                return
            d = dlg.PickDialog(app, "Choose the BOM document", [(f"{x.number or '—'}   {x.title}   {x.rel_path}", x) for x in docs], "Search documents")
            if not d.exec() or not d.chosen:
                return
            doc_id = d.chosen.id
        try:
            bom = client.read_bom(doc_id)
        except rw.RevisionWorxError as e:
            if "no released revision" not in str(e):
                app.error(str(e))
                return
            if not dlg.confirm(app, "No released revision", f"{e}\n\nImport the latest revision anyway? It isn't released, so it may still change.", "Import latest"):
                return
            bom = app.run_guarded(lambda: client.read_bom(doc_id, allow_unreleased=True))
            if bom is None:
                return
        c = app.company
        new = [p["number"] for p in bom["parts"] if c.item_by_number(p["number"]) is None]
        src = bom["source"]
        text = (f"Import the BOM for {bom['root']} from {src['number'] or 'this document'}, Rev {src['label']}?\n\n{len(bom['lines'])} lines, {len(new)} new items."
                " Existing BOMs for items in it are replaced. Stock, costs and prices don't change.")
        if dlg.confirm(app, "Import BOM", text, "Import"):
            res = app.act(lambda: c.import_bom(bom["root"], bom["parts"], bom["lines"], src))
            if res:
                app.toast(f"Imported {res['lines']} lines from Rev {src['label']}.", "success")
                app.go("items", res["root"])

