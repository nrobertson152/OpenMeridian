"""Forms and dialogs. They collect values; company.py decides what's allowed."""
from __future__ import annotations

import platform
import webbrowser

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import APP_NAME, COPYRIGHT, DONATE_URL, LICENSE_NAME, LICENSE_URL, VERSION
from ..company import ERPError
from ..values import ValueProblem, fmt_qty, parse_money, parse_qty
from . import theme as th
from .widgets import Combo, button, label


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
        self.tracking = self.combo("Serial numbers", [("No", "none"), ("Yes: each unit made has one", "serial")],
                                   i.get("tracking", "none"))

        def made_only():                    # serial numbers are for units made; a bought item has none here
            make = self.kind.currentData() == "make"
            self.tracking.setEnabled(make)
            if not make:
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


class QuantitiesDialog(QDialog):
    """Ship or receive: one row per line, filled in with everything outstanding. Partial quantities are fine."""

    def __init__(self, app, title, intro, rows, apply_fn, ok_text):
        super().__init__(app.window)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.rows, self.apply_fn = rows, apply_fn
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.addWidget(label(intro, "muted", wrap=True))
        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels(["Item", "Description", "Outstanding", "This time"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        for r, row in enumerate(rows):
            for c, v in enumerate((row["number"], row["description"], fmt_qty(row["left"]))):
                it = QTableWidgetItem(v)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r, c, it)
            self.table.setItem(r, 3, QTableWidgetItem(fmt_qty(row["left"])))
        self.table.setFixedHeight(min(320, 40 + 30 * len(rows)))
        lay.addWidget(self.table)
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

    def submit(self):
        try:
            q = {row["id"]: parse_qty(self.table.item(r, 3).text()) for r, row in enumerate(self.rows)}
            self.apply_fn(q)
        except (ERPError, ValueProblem) as e:
            self.message.setText(str(e))
            self.message.show()
            return
        self.accept()


class CompleteDialog(FormDialog):
    """Complete a work order: how many were made and, for an item made with serial numbers, the serial of each."""

    def __init__(self, app, wo, item):
        super().__init__(app, f"Complete {wo['number']}", "Complete")
        self.wo, self.item = wo, item
        left = wo["qty"] - wo["done"]
        intro = "Components leave stock and finished goods come in at their actual cost."
        if item["tracking"] == "serial":
            intro += (f" Each {item['number']} made has its own serial number: one per line, as on its plate."
                      + (" They're registered in RevisionWorx's unit register as built." if app.company.setting("rw_workspace")
                         else ""))
        self.form.addRow(label(intro, "muted", wrap=True))
        self.qty = self.line("Made this time", fmt_qty(left))
        self.serials = self.area("Serial numbers") if item["tracking"] == "serial" else None
        if self.serials is not None:
            self.serials.setFixedHeight(110)
            self.serials.setPlaceholderText("NH-26-0001\nNH-26-0002")

    def apply(self):
        q = parse_qty(self.qty.text(), "the quantity made")
        serials = None if self.serials is None else self.serials.toPlainText().splitlines()
        self.app.company.complete_work_order(self.wo["id"], q, serials)
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
    def __init__(self, app, item):
        super().__init__(app, f"Adjust stock: {item['number']}", "Post to ledger")
        self.item = item
        self.form.addRow("On hand", QLabel(fmt_qty(item["on_hand"])))
        self.delta = self.line("Change by", "", "e.g. 5 or -2")
        self.note = self.line("Reason", "", "Goes in the ledger")

    def apply(self):
        self.app.company.adjust_stock(self.item["id"], parse_qty(self.delta.text()), self.note.text())


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
