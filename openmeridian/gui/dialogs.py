"""Forms and dialogs. They collect values; company.py decides what's allowed."""
from __future__ import annotations

import platform
import webbrowser

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import APP_NAME, COPYRIGHT, DONATE_URL, LICENSE_NAME, LICENSE_URL, VERSION, tracing
from ..company import ERPError
from ..report_csv import to_csv
from ..values import ValueProblem, fmt_qty, parse_money, parse_qty
from . import theme as th
from .widgets import Combo, StatusBlock, button, label


def money_text(cents) -> str:
    return f"{cents / 100:.2f}"


class FormDialog(QDialog):
    def __init__(self, app, title, ok_text="Save"):
        super().__init__(app.window)
        self.app = app
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(18, 16, 18, 14)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(8)
        self.outer.addLayout(self.form)
        self.message = label("", "small", wrap=True)
        self.message.setStyleSheet(f"color: {app.theme.ui['danger']};")
        self.message.hide()
        self.outer.addWidget(self.message)
        self.buttons = QDialogButtonBox()
        self.ok_button = self.buttons.addButton(ok_text, QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_button.setObjectName("primary")
        self.buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        self.outer.addSpacing(6)
        self.outer.addWidget(self.buttons)
        self.result_value = None

    def line(self, text, value="", hint="") -> QLineEdit:
        w = QLineEdit(str(value))
        if hint:
            w.setPlaceholderText(hint)
        self.form.addRow(text, w)
        return w

    def combo(self, text, choices, current=None) -> QComboBox:
        w = Combo()
        for lab, data in choices:
            w.addItem(lab, data)
        if current is not None:
            i = w.findData(current)
            if i >= 0:
                w.setCurrentIndex(i)
        self.form.addRow(text, w)
        return w

    def area(self, text, value="") -> QPlainTextEdit:
        w = QPlainTextEdit(str(value))
        w.setFixedHeight(62)
        self.form.addRow(text, w)
        return w

    def submit(self):
        try:
            self.result_value = self.apply()
        except (ERPError, ValueProblem) as e:
            self.message.setText(str(e))
            self.message.show()
            return
        self.accept()

    def apply(self):
        raise NotImplementedError


class ItemDialog(FormDialog):
    def __init__(self, app, item=None):
        super().__init__(app, "Edit item" if item else "New item")
        self.item = item
        i = item or {}
        self.number = self.line("Item number", i.get("number", ""), "Part number")
        self.desc = self.line("Description", i.get("description", ""))
        self.kind = self.combo("Type", [("Buy", "buy"), ("Make", "make")], i.get("kind", "buy"))
        self.tracking = self.combo("Tracking", [("None", "none"), ("Serial numbers: each unit made has one", "serial"),
                                                ("Lots: each receipt, use and shipment says which", "lot")],
                                   i.get("tracking", "none"))

        def made_only():                    # serial numbers are for units made; a bought item has none here
            make = self.kind.currentData() == "make"
            self.tracking.model().item(self.tracking.findData("serial")).setEnabled(make)
            if not make and self.tracking.currentData() == "serial":
                self.tracking.setCurrentIndex(self.tracking.findData("none"))
        self.kind.currentIndexChanged.connect(lambda _i: made_only())
        made_only()
        self.unit = self.line("Unit", i.get("unit", "EA"))
        self.cost = self.line("Cost", money_text(i.get("cost", 0)))
        self.price = self.line("Price", money_text(i.get("price", 0)))
        self.rp = self.line("Reorder point", fmt_qty(i.get("reorder_point", 0)))
        self.rq = self.line("Reorder quantity", fmt_qty(i.get("reorder_qty", 0)))
        sup = [("None", None)] + [(c["name"], c["id"]) for c in app.company.contacts("supplier")]
        self.supplier = self.combo("Supplier", sup, i.get("supplier_id"))
        self.lead = self.line("Lead time (days)", i.get("lead_days", 0))
        self.bin = self.line("Bin", i.get("bin", ""))
        self.notes = self.area("Notes", i.get("notes", ""))

    def apply(self):
        c = self.app.company
        try:
            lead = int(self.lead.text() or 0)
        except ValueError:
            raise ERPError("Enter the lead time as whole days.") from None
        f = dict(number=self.number.text(), description=self.desc.text(), kind=self.kind.currentData(), unit=self.unit.text(),
                 cost=parse_money(self.cost.text(), "the cost"), price=parse_money(self.price.text(), "the price"),
                 reorder_point=parse_qty(self.rp.text(), "the reorder point"), reorder_qty=parse_qty(self.rq.text(), "the reorder quantity"),
                 supplier_id=self.supplier.currentData(), lead_days=lead, bin=self.bin.text(), notes=self.notes.toPlainText(),
                 tracking=self.tracking.currentData())
        if self.item:
            c.update_item(self.item["id"], **f)
            return self.item["id"]
        return c.add_item(**f)


class ContactDialog(FormDialog):
    def __init__(self, app, kind, contact=None):
        super().__init__(app, f"Edit {kind}" if contact else f"New {kind}")
        self.kind, self.contact = kind, contact
        c = contact or {}
        self.name = self.line("Name", c.get("name", ""))
        self.person = self.line("Contact", c.get("contact", ""))
        self.email = self.line("Email", c.get("email", ""))
        self.phone = self.line("Phone", c.get("phone", ""))
        self.address = self.area("Address", c.get("address", ""))
        self.terms = self.line("Payment terms (days)", c.get("terms_days", 30))
        self.notes = self.area("Notes", c.get("notes", ""))

    def apply(self):
        try:
            days = int(self.terms.text() or 0)
        except ValueError:
            raise ERPError("Enter the payment terms as whole days.") from None
        if days < 0:
            raise ERPError("Payment terms can't be negative.")
        f = dict(name=self.name.text(), contact=self.person.text(), email=self.email.text(), phone=self.phone.text(),
                 address=self.address.toPlainText(), terms_days=days, notes=self.notes.toPlainText())
        if self.contact:
            self.app.company.update_contact(self.contact["id"], **f)
            return self.contact["id"]
        return self.app.company.add_contact(self.kind, **f)


class OrderDialog(FormDialog):
    """New sales or purchase order header."""

    def __init__(self, app, kind):
        super().__init__(app, "New sales order" if kind == "sale" else "New purchase order", "Create")
        self.kind = kind
        ckind = "customer" if kind == "sale" else "supplier"
        people = app.company.contacts(ckind)
        self.party = self.combo(ckind.capitalize(), [(c["name"], c["id"]) for c in people])
        self.due = self.line("Due date", "", "YYYY-MM-DD")
        self.ref = self.line("Reference", "")
        if not people:
            self.message.setText(f"Add a {ckind} first.")
            self.message.show()
            self.ok_button.setEnabled(False)

    def apply(self):
        c = self.app.company
        fn = c.create_sales_order if self.kind == "sale" else c.create_purchase_order
        return fn(self.party.currentData(), self.due.text(), self.ref.text())


def _item_choices(app, kinds=None):
    return [(f"{i['number']}  {i['description']}", i["id"]) for i in app.company.items() if not kinds or i["kind"] in kinds]


class LineDialog(FormDialog):
    def __init__(self, app, kind, order_id):
        super().__init__(app, "Add line", "Add")
        self.kind, self.order_id = kind, order_id
        self.item_box = self.combo("Item", _item_choices(app))
        self.item_box.setEditable(True)
        self.item_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.qty = self.line("Quantity", "1")
        self.amount = self.line("Unit price" if kind == "sale" else "Unit cost", "")
        self.item_box.currentIndexChanged.connect(self._fill)
        self._fill()

    def _fill(self):
        it = self.app.company.item(self.item_box.currentData()) if self.item_box.currentData() else None
        if it:
            self.amount.setText(money_text(it["price"] if self.kind == "sale" else it["cost"]))

    def apply(self):
        c = self.app.company
        if not self.item_box.currentData():
            raise ERPError("Choose an item.")
        fn = c.add_sales_line if self.kind == "sale" else c.add_purchase_line
        return fn(self.order_id, self.item_box.currentData(), parse_qty(self.qty.text()), parse_money(self.amount.text()))


def _fixed(text) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemFlag.ItemIsEnabled)
    return it


class QuantitiesDialog(QDialog):
    """Ship or receive: one row per line, filled in with everything outstanding. Partial quantities are fine.

    Receiving (``lots_in`` true), a line of an item tracked by lot has a Lot cell for the lot it came in as. Shipping, it
    has a row under it for each of its lots in stock, filled in oldest first for someone to check: the line ships what
    those rows say."""

    def __init__(self, app, title, intro, rows, apply_fn, ok_text, lots_in=False):
        super().__init__(app.window)
        self.setWindowTitle(title)
        self.setMinimumWidth(600)
        self.app, self.rows, self.apply_fn, self.lots_in = app, rows, apply_fn, lots_in
        c = app.company
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.addWidget(label(intro, "muted", wrap=True))
        tracked = any(r["tracking"] == "lot" for r in rows)
        heads = ["Item", "Description", "Outstanding", "This time"] + (["Lot"] if lots_in and tracked else [])
        self.table = QTableWidget(0, len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.line_row, self.lot_rows = {}, {}          # line id -> its table row; line id -> [(table row, lot)]
        self.lot_edits: dict[int, QLineEdit] = {}     # receiving: line id -> where its lot is typed
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.line_row[row["id"]] = r
            for col, v in enumerate((row["number"], row["description"], fmt_qty(row["left"]))):
                self.table.setItem(r, col, _fixed(v))
            if row["tracking"] != "lot":
                self.table.setItem(r, 3, QTableWidgetItem(fmt_qty(row["left"])))
                if len(heads) > 4:
                    self.table.setItem(r, 4, _fixed("—"))
            elif lots_in:
                self.table.setItem(r, 3, QTableWidgetItem(fmt_qty(row["left"])))
                lot = QLineEdit()
                lot.setPlaceholderText("Supplier's lot")
                lot.setToolTip("The lot it came in as: the supplier's lot or batch number")
                self.lot_edits[row["id"]] = lot
                self.table.setCellWidget(r, 4, lot)
            else:
                picks = dict(c.suggest_lots(row["item_id"], row["left"]))
                self.lot_rows[row["id"]] = []
                for have in c.lots(row["item_id"], in_stock=True):
                    s = self.table.rowCount()
                    self.table.insertRow(s)
                    self.table.setItem(s, 0, _fixed(""))
                    self.table.setItem(s, 1, _fixed(f"lot {have['lot']}, {fmt_qty(have['on_hand'])} on hand"))
                    self.table.setItem(s, 2, _fixed(""))
                    self.table.setItem(s, 3, QTableWidgetItem(fmt_qty(picks.get(have["lot"], 0))))
                    self.lot_rows[row["id"]].append((s, have["lot"]))
                if not self.lot_rows[row["id"]]:
                    s = self.table.rowCount()
                    self.table.insertRow(s)
                    self.table.setItem(s, 1, _fixed("no lots in stock"))
                    for col in (0, 2):
                        self.table.setItem(s, col, _fixed(""))
                    self.table.setItem(s, 3, _fixed(""))
                self.table.setItem(r, 3, _fixed(fmt_qty(sum(picks.values()))))
        self.table.itemChanged.connect(self._totals)
        if len(heads) > 4:
            self.table.setColumnWidth(4, 170)
            self.setMinimumWidth(760)
        self.table.setFixedHeight(min(360, 40 + 30 * self.table.rowCount()))
        lay.addWidget(self.table)
        if tracked and not lots_in:
            lay.addWidget(label("Lots are filled in oldest first. Change them to the lots that are going.", "small", wrap=True))
        self.message = label("", "small", wrap=True)
        self.message.setStyleSheet(f"color: {app.theme.ui['danger']};")
        self.message.hide()
        lay.addWidget(self.message)
        box = QDialogButtonBox()
        okb = box.addButton(ok_text, QDialogButtonBox.ButtonRole.AcceptRole)
        okb.setObjectName("primary")
        box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.submit)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _lot_picks(self, line_id):
        return [(lot, parse_qty(self.table.item(s, 3).text())) for s, lot in self.lot_rows[line_id]]

    def _totals(self, item):
        """A line shipping from lots ships what its lot rows add up to."""
        for line_id, lot_rows in self.lot_rows.items():
            if any(s == item.row() for s, _lot in lot_rows):
                try:
                    total = fmt_qty(sum(q for _lot, q in self._lot_picks(line_id)))
                except ValueProblem:
                    total = "?"
                self.table.blockSignals(True)
                self.table.item(self.line_row[line_id], 3).setText(total)
                self.table.blockSignals(False)

    def submit(self):
        try:
            q, lots = {}, {}
            for row in self.rows:
                if row["id"] in self.lot_rows:
                    lots[row["id"]] = [(lot, n) for lot, n in self._lot_picks(row["id"]) if n]
                    q[row["id"]] = sum(n for _lot, n in lots[row["id"]])
                else:
                    q[row["id"]] = parse_qty(self.table.item(self.line_row[row["id"]], 3).text())
                    if row["id"] in self.lot_edits:
                        lots[row["id"]] = self.lot_edits[row["id"]].text()
            self.apply_fn(q, lots)
        except (ERPError, ValueProblem) as e:
            self.message.setText(str(e))
            self.message.show()
            return
        self.accept()


class CompleteDialog(FormDialog):
    """Complete a work order: how many were made and, for an item made with serial numbers, the serial of each. A
    component tracked by lot says which lots went in (filled in oldest first, for someone to check), and an item made
    that is tracked by lot is given its lot."""

    def __init__(self, app, wo, item):
        super().__init__(app, f"Complete {wo['number']}", "Complete")
        self.wo, self.item = wo, item
        c = app.company
        left = wo["qty"] - wo["done"]
        intro = "Components leave stock and finished goods come in at their actual cost."
        if item["tracking"] == "serial":
            intro += (f" Each {item['number']} made has its own serial number: one per line, as on its plate."
                      + (" They're registered in RevisionWorx's unit register as built." if c.setting("rw_workspace")
                         else ""))
        self.form.addRow(label(intro, "muted", wrap=True))
        self.qty = self.line("Made this time", fmt_qty(left))
        self.serials = self.area("Serial numbers") if item["tracking"] == "serial" else None
        if self.serials is not None:
            self.serials.setFixedHeight(110)
            self.serials.setPlaceholderText("NH-26-0001\nNH-26-0002")
        self.made_lot = self.line("Lot made", c.default_made_lot(wo["id"])) if item["tracking"] == "lot" else None
        self.tracked = [b for b in c.bom(wo["item_id"]) if c.item(b["child_id"])["tracking"] == "lot"]
        self.lot_rows: list[tuple[int, int, str]] = []     # (table row, component item id, lot)
        self.lots = None
        if self.tracked:
            self.form.addRow(label("Lots used, filled in oldest first. Change them to the lots that went in.", "small", wrap=True))
            self.lots = QTableWidget(0, 4)
            self.lots.setHorizontalHeaderLabels(["Component", "Lot", "On hand", "Used"])
            self.lots.verticalHeader().setVisible(False)
            self.lots.setShowGrid(False)
            self.lots.verticalHeader().setDefaultSectionSize(28)
            self.lots.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            self.lots.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
            for b in self.tracked:
                for have in c.lots(b["child_id"], in_stock=True):
                    r = self.lots.rowCount()
                    self.lots.insertRow(r)
                    for col, v in enumerate((b["number"], have["lot"], fmt_qty(have["on_hand"]))):
                        self.lots.setItem(r, col, _fixed(v))
                    self.lots.setItem(r, 3, QTableWidgetItem(""))
                    self.lot_rows.append((r, b["child_id"], have["lot"]))
                if not any(cid == b["child_id"] for _r, cid, _l in self.lot_rows):
                    r = self.lots.rowCount()
                    self.lots.insertRow(r)
                    for col, v in enumerate((b["number"], "no lots in stock", "", "")):
                        self.lots.setItem(r, col, _fixed(v))
            self.lots.setFixedHeight(min(240, 34 + 28 * max(1, self.lots.rowCount())))
            self.form.addRow(self.lots)
            self.qty.textChanged.connect(lambda _t: self._fill_lots())
            self._fill_lots()

    def _fill_lots(self):
        """Oldest lots first for what this many takes, as a starting point."""
        try:
            q = parse_qty(self.qty.text())
        except ValueProblem:
            return
        c = self.app.company
        uses = {b["child_id"]: b["use"] for b in c.work_order_uses(self.wo["id"], max(q, 0))}
        for b in self.tracked:
            picks = dict(c.suggest_lots(b["child_id"], uses.get(b["child_id"], 0)))
            for r, cid, lot in self.lot_rows:
                if cid == b["child_id"]:
                    self.lots.item(r, 3).setText(fmt_qty(picks.get(lot, 0)))

    def apply(self):
        q = parse_qty(self.qty.text(), "the quantity made")
        serials = None if self.serials is None else self.serials.toPlainText().splitlines()
        lots = {}
        for r, cid, lot in self.lot_rows:
            n = parse_qty(self.lots.item(r, 3).text() or "0", f"the quantity of lot {lot} used")
            lots.setdefault(cid, [])
            if n:
                lots[cid].append((lot, n))
        made = None if self.made_lot is None else self.made_lot.text()
        self.app.company.complete_work_order(self.wo["id"], q, serials, lots or None, made)
        return q


class WorkOrderDialog(FormDialog):
    def __init__(self, app, item_id=None):
        super().__init__(app, "New work order", "Create")
        self.item_box = self.combo("Make", _item_choices(app, ("make",)), item_id)
        self.qty = self.line("Quantity", "1")
        self.due = self.line("Due date", "", "YYYY-MM-DD")
        if self.item_box.count() == 0:
            self.message.setText("No item is set up to be made yet.")
            self.message.show()
            self.ok_button.setEnabled(False)

    def apply(self):
        return self.app.company.create_work_order(self.item_box.currentData(), parse_qty(self.qty.text()), self.due.text())


class BomLineDialog(FormDialog):
    def __init__(self, app, parent_id):
        super().__init__(app, "Add BOM line", "Add")
        self.parent_id = parent_id
        self.child = self.combo("Component", [c for c in _item_choices(app) if c[1] != parent_id])
        self.qty = self.line("Quantity each", "1")
        self.find = self.line("Find number", "")

    def apply(self):
        if not self.child.currentData():
            raise ERPError("Choose a component.")
        self.app.company.set_bom_line(self.parent_id, self.child.currentData(), parse_qty(self.qty.text()), self.find.text())


class AdjustDialog(FormDialog):
    def __init__(self, app, item, lot=""):
        super().__init__(app, f"Adjust stock: {item['number']}", "Post to ledger")
        self.item = item
        self.form.addRow("On hand", QLabel(fmt_qty(item["on_hand"])))
        self.lot = None
        if item["tracking"] == "lot":           # a lot in stock, or a new one typed in when stock goes up
            self.lot = self.combo("Lot", [(f"{l['lot']}", l["lot"]) for l in app.company.lots(item["id"], in_stock=True)])
            self.lot.setEditable(True)
            self.lot.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            self.lot.lineEdit().setPlaceholderText("Choose a lot in stock, or type a new one")
            self.lot.setCurrentIndex(-1)
            self.lot.setCurrentText(lot)
        self.delta = self.line("Change by", "", "e.g. 5 or -2")
        self.note = self.line("Reason", "", "Goes in the ledger")

    def apply(self):
        self.app.company.adjust_stock(self.item["id"], parse_qty(self.delta.text()), self.note.text(),
                                      lot=self.lot.currentText() if self.lot is not None else "")


class PickDialog(QDialog):
    """Pick one row from a searchable list."""

    def __init__(self, app, title, rows, placeholder="Search"):
        super().__init__(app.window)
        self.setWindowTitle(title)
        self.resize(600, 440)
        self.rows, self.chosen = rows, None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        lay.addWidget(self.search)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.search.textChanged.connect(self._fill)
        self.list.itemDoubleClicked.connect(lambda _i: self._done())
        self.search.returnPressed.connect(self._done)
        self.search.installEventFilter(self)
        self._fill()
        self.search.setFocus()

    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.search and e.type() == e.Type.KeyPress and e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 1 if e.key() == Qt.Key.Key_Down else -1
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + step)))
            return True
        return super().eventFilter(obj, e)

    def _fill(self):
        self.list.clear()
        words = self.search.text().casefold().split()
        for text, data in self.rows:
            if all(w in text.casefold() for w in words):
                it = QListWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, data)
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _done(self):
        it = self.list.currentItem()
        if it:
            self.chosen = it.data(Qt.ItemDataRole.UserRole)
            self.accept()


class TraceDialog(QDialog):
    """Where a lot came from and where it went (Company.trace_lot), with what it reached said first, for a recall."""

    COLUMNS = ["What", "Item", "Lot or serial", "Qty", "Reference", "Customer or supplier", "Date", "Note"]

    def __init__(self, app, item_id, lot):
        super().__init__(app.window)
        self.app = app
        self.trace = t = app.company.trace_lot(item_id, lot)
        self.setWindowTitle(f"Trace lot {t['lot']} of {t['item']}")
        self.resize(980, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.addWidget(StatusBlock(app.theme, "info", f"Lot {t['lot']} of {t['item']} ({t['description']})", tracing.summary(t)))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLUMNS))
        self.tree.setHeaderLabels(self.COLUMNS)
        self.tree.setUniformRowHeights(True)
        for key, title in tracing.SECTIONS:
            top = QTreeWidgetItem([title])
            self.tree.addTopLevelItem(top)
            self._add(top, t[key])
            if not t[key]:
                top.addChild(QTreeWidgetItem(["Nothing recorded"]))
        self.tree.expandAll()
        for col in range(len(self.COLUMNS)):
            self.tree.resizeColumnToContents(col)
        lay.addWidget(self.tree, 1)
        lay.addWidget(label("A lot is followed whole: if more was added to a lot made from it, that is followed too, so a "
                            "recall is never too narrow. Units are listed where they were made; RevisionWorx's unit "
                            "register says where each one is now.", "small", wrap=True))
        box = QDialogButtonBox()
        save = box.addButton("Save as CSV…", QDialogButtonBox.ButtonRole.ActionRole)
        save.clicked.connect(self.save_csv)
        box.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _add(self, parent, steps):
        for s in steps:
            node = QTreeWidgetItem([s["what"], s["item"], s["code"], fmt_qty(s["qty"]) if s["qty"] else "", s["ref"],
                                    s["who"], s["date"], s["note"]])
            node.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            parent.addChild(node)
            self._add(node, s["children"])

    def save_csv(self, path=None):
        t = self.trace
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save the trace", f"Trace {t['item']} lot {t['lot']}.csv",
                                                  "CSV file (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(to_csv(tracing.HEADERS, tracing.rows(t)))
        except OSError as e:
            self.app.error(str(e))
            return
        self.app.toast("Trace saved", "success")


class SettingsDialog(FormDialog):
    def __init__(self, app):
        super().__init__(app, "Settings", "Save")
        c = app.company
        self.name = self.address = self.currency = self.tax = self.workspace = None
        if c:
            self.name = self.line("Company name", c.setting("company_name"))
            self.address = self.area("Address", c.setting("address"))
            self.currency = self.line("Currency symbol", c.setting("currency"))
            self.tax = self.line("Tax rate (%)", c.setting("tax_percent"))
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            self.workspace = QLineEdit(c.setting("rw_workspace"))
            self.workspace.setPlaceholderText("Folder holding .revisionworx")
            h.addWidget(self.workspace, 1)
            h.addWidget(button("Browse…", self._browse))
            self.form.addRow("RevisionWorx workspace", row)
        self.rw_path = self.line("RevisionWorx program", app.settings["revisionworx_path"], "Blank = find it automatically")
        self.theme = self.combo("Theme", [(t["label"], k) for k, t in th.THEMES.items()], app.theme.name)
        self.setMinimumWidth(560)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the RevisionWorx workspace folder")
        if d:
            self.workspace.setText(d)

    def apply(self):
        app = self.app
        c = app.company
        if c:
            ws = self.workspace.text().strip()
            from ..revisionworx import is_workspace
            if ws and not is_workspace(ws):
                raise ERPError(f"{ws} isn't a RevisionWorx workspace: it has no .revisionworx folder.")
            with c.tx():
                c.set_setting("company_name", self.name.text())
                c.set_setting("address", self.address.toPlainText())
                c.set_setting("currency", self.currency.text().strip()[:3])
                c.set_setting("tax_percent", self.tax.text())
                c.set_setting("rw_workspace", ws)
        app.settings["revisionworx_path"] = self.rw_path.text().strip()
        app.set_theme(self.theme.currentData())
        app.settings.save()


class AboutDialog(QDialog):
    """Same content and order as OpenSchematix's About page."""

    def __init__(self, app):
        super().__init__(app.window)
        self.setWindowTitle(f"About {APP_NAME}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        top = QHBoxLayout()
        pm = QPixmap(app.resource("openmeridian-64.png"))
        if not pm.isNull():
            logo = QLabel()
            logo.setPixmap(pm)
            top.addWidget(logo)
            top.addSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(APP_NAME, "detailTitle"))
        col.addWidget(label(f"Version {VERSION}"))
        col.addWidget(label("Lightweight ERP for small engineering businesses", "muted"))
        top.addLayout(col, 1)
        lay.addLayout(top)
        body = QLabel(f"{COPYRIGHT}\n\nFree and open-source software, licensed under the {LICENSE_NAME}. You may use, study, share and "
                      "modify it under the terms of that licence. It comes with ABSOLUTELY NO WARRANTY.\n\n"
                      "OpenMeridian keeps stock, orders and invoices in one file on your computer. It is not an accounting "
                      "system and doesn't file taxes. Keep backups, and have your accountant check anything you rely on.\n\n"
                      "OpenMeridian has no ads, no telemetry, no accounts and no feature limits. If it is useful to you, "
                      "you can support its development voluntarily.")
        body.setWordWrap(True)
        body.setMinimumWidth(500)
        lay.addSpacing(10)
        lay.addWidget(body)
        links = QHBoxLayout()
        links.addWidget(button("Support development (Ko-fi)", lambda: webbrowser.open(DONATE_URL), name="link"))
        links.addSpacing(10)
        links.addWidget(button("Licence text", lambda: webbrowser.open(LICENSE_URL), name="link"))
        links.addStretch(1)
        lay.addLayout(links)
        lay.addWidget(label(f"Python {platform.python_version()} · Qt {qVersion()} · PySide6 {pyside_version} · {platform.system()} {platform.release()}", "small"))
        box = QDialogButtonBox()
        close = box.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close.setObjectName("primary")
        box.rejected.connect(self.reject)
        lay.addWidget(box)


def confirm(app, title, text, ok="OK") -> bool:
    m = QMessageBox(app.window)
    m.setWindowTitle(title)
    m.setText(text)
    okb = m.addButton(ok, QMessageBox.ButtonRole.AcceptRole)
    m.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    m.exec()
    return m.clickedButton() is okb


__all__ = [n for n in dir() if not n.startswith("_")]
_ = QPushButton
