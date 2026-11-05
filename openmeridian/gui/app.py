"""Main window: sidebar navigation, a page, status bar. Menu and status bar as in OpenSchematix and RevisionWorx."""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import tempfile
import traceback
import webbrowser

from PySide6.QtCore import QMarginsF, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPageLayout, QPageSize, QPainter, QPdfWriter, QPixmap, QShortcut, QTextDocument
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, COMPANY_EXTENSION, DONATE_URL, VERSION
from .. import db, documents
from .. import revisionworx as rw
from ..company import Company, ERPError
from ..report_csv import to_csv
from ..sample import build as build_sample
from ..settings import Settings
from . import dialogs as dlg
from . import icons as ic
from . import pages
from . import theme as th
from .widgets import button, label

NAV = [(None, [("dashboard", "Overview", "dashboard")]),
       ("Engineering", [("items", "Items", "items"), ("engineering", "RevisionWorx", "engineering")]),
       ("Sales", [("sales", "Sales orders", "sales"), ("invoices", "Invoices", "invoices"), ("customers", "Customers", "customers")]),
       ("Purchasing", [("purchasing", "Purchase orders", "purchasing"), ("suppliers", "Suppliers", "suppliers")]),
       ("Operations", [("production", "Work orders", "production"), ("planning", "Planning", "planning"), ("stock", "Stock ledger", "stock")])]


def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "openmeridian", "resources", name)
        if os.path.exists(p):
            return p
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", name)


class _Signals(QObject):
    finished = Signal(object, object)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            res, err = self.fn(), None
        except Exception as e:  # noqa: BLE001 - reported to the window, never lost in a thread
            res, err = None, e
        self.signals.finished.emit(res, err)


class Toast(QFrame):
    """Quiet confirmation in the corner, like OpenSchematix's."""

    def __init__(self, parent, text, theme, kind):
        super().__init__(parent)
        u = theme.ui
        color = {"success": u["success"], "warning": u["warning"], "error": u["danger"]}.get(kind, u["info"])
        self.setStyleSheet(f"Toast {{ background: {u['surface']}; border: 1px solid {u['border_strong']}; border-left: 4px solid {color}; border-radius: 6px; }} QLabel {{ background: transparent; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setMaximumWidth(420)
        lay.addWidget(lab)
        self.adjustSize()
        self.show()
        self.raise_()
        QTimer.singleShot(4000, self.deleteLater)


class StartPage(QWidget):
    """No company open: the same welcome as OpenSchematix and RevisionWorx. One card, a few clear ways in."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.addStretch(2)
        h = QHBoxLayout()
        h.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setFixedWidth(440)
        self.lay = QVBoxLayout(self.card)
        self.lay.setContentsMargins(28, 24, 28, 24)
        self.lay.setSpacing(8)
        h.addWidget(self.card)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(3)
        self.rebuild()

    def rebuild(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        app = self.app
        pm = QPixmap(resource("openmeridian-64.png"))
        if not pm.isNull():
            logo = QLabel()
            logo.setPixmap(pm)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lay.addWidget(logo)
        t = label(APP_NAME, "pageTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.addWidget(t)
        s = label("Stock, orders and production for small engineering businesses.", "muted", wrap=True)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.addWidget(s)
        self.lay.addSpacing(10)
        self.lay.addWidget(button("Create a company…", app.new_company, primary=True))
        self.lay.addWidget(button("Open a company file…", app.open_dialog))
        self.lay.addWidget(button("Explore a sample company", app.open_sample))
        rec = [p for p in app.settings["recent"] if os.path.exists(p)][:4]
        if rec:
            self.lay.addSpacing(8)
            self.lay.addWidget(label("RECENT", "sectionTitle"))
            for p in rec:
                self.lay.addWidget(button(os.path.basename(p), lambda x=p: app.open_path(x), name="link"))


class Sidebar(QFrame):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("sidebar")
        self.setFixedWidth(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(1)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 8)
        pm = QPixmap(resource("openmeridian-64.png"))
        if not pm.isNull():
            logo = QLabel()
            logo.setPixmap(pm.scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            head.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.name = label(APP_NAME, "companyName", wrap=True)
        self.file = label("", "companyFile", wrap=True)
        col.addWidget(self.name)
        col.addWidget(self.file)
        head.addLayout(col, 1)
        lay.addLayout(head)
        self.search_btn = QPushButton("  Search everything    Ctrl+K")
        self.search_btn.setObjectName("navSearch")
        self.search_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.search_btn.clicked.connect(app.global_search)
        lay.addWidget(self.search_btn)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        self.icons = {}
        for group, entries in NAV:
            if group:
                lay.addWidget(label(group.upper(), "navGroup"))
            else:
                lay.addSpacing(8)
            for key, text, icon in entries:
                b = QPushButton(text)
                b.setObjectName("navButton")
                b.setCheckable(True)
                b.setIconSize(QSize(18, 18))
                b.clicked.connect(lambda _=False, k=key: app.go(k))
                self.group.addButton(b)
                self.buttons[key] = b
                self.icons[key] = icon
                lay.addWidget(b)
        lay.addStretch(1)
        self.rw_status = label("", "small", wrap=True)
        self.rw_status.setContentsMargins(6, 0, 6, 6)
        lay.addWidget(self.rw_status)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("navButton")
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.clicked.connect(app.open_settings)
        lay.addWidget(self.settings_btn)
        self.apply_icons()

    def apply_icons(self):
        u = self.app.theme.ui
        for key, b in self.buttons.items():
            b.setIcon(ic.icon(self.icons[key], u["muted"], u["accent"], 18))
        self.settings_btn.setIcon(ic.icon("settings", u["muted"], u["accent"], 18))
        self.search_btn.setIcon(ic.icon("search", u["muted"], u["accent"], 16))
        self.search_btn.setStyleSheet(f"QPushButton {{ text-align: left; background: {u['input']}; color: {u['muted']}; font-size: 9pt; padding: 6px 8px; }}")


class App:
    """Everything the pages need; the window itself is `self.window`."""

    def __init__(self, qapp, settings=None):
        self.qapp = qapp
        self.settings = settings or Settings()
        self.theme = th.resolve(self.settings["theme"])
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(th.stylesheet(self.theme))
        qapp.setWindowIcon(QIcon(resource("openmeridian-256.png")))
        self.resource = resource
        self.company = None
        self.pool = QThreadPool.globalInstance()
        self._jobs = set()
        self.window = QMainWindow()
        self.window.setWindowTitle(APP_NAME)
        self.window.resize(1360, 840)
        self.window.setMinimumSize(1040, 640)
        self.window.closeEvent = self._close_event
        self.root = QStackedWidget()
        self.window.setCentralWidget(self.root)
        self.start = StartPage(self)
        self.root.addWidget(self.start)
        self.shell = QWidget()
        h = QHBoxLayout(self.shell)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = Sidebar(self)
        h.addWidget(self.sidebar)
        self.page_stack = QStackedWidget()
        h.addWidget(self.page_stack, 1)
        self.root.addWidget(self.shell)
        self.pages = {}
        for key, cls in (("dashboard", pages.DashboardPage), ("items", pages.ItemsPage), ("engineering", pages.EngineeringPage),
                         ("sales", pages.SalesPage), ("invoices", pages.InvoicesPage), ("customers", pages.CustomersPage),
                         ("purchasing", pages.PurchasingPage), ("suppliers", pages.SuppliersPage), ("production", pages.ProductionPage),
                         ("planning", pages.PlanningPage), ("stock", pages.StockPage)):
            self.pages[key] = cls(self)
            self.page_stack.addWidget(self.pages[key])
        self._build_menu()
        self.status = self.window.statusBar()
        self.status.setSizeGripEnabled(False)
        self.status_text = QLabel("Ready.")
        self.status.addWidget(self.status_text, 1)
        self.status_user = QLabel("")
        self.status.addPermanentWidget(self.status_user)
        self.current_key = "dashboard"
        self.keys()
        geo = self.settings["geometry"]
        if geo:
            try:
                self.window.restoreGeometry(bytes.fromhex(geo))
            except ValueError:
                pass

    # ---- menu and keys
    def _build_menu(self):
        m = self.window.menuBar()
        f = m.addMenu("&File")
        f.addAction("New company…", self.new_company)
        act = f.addAction("Open…", self.open_dialog)
        act.setShortcut(QKeySequence.StandardKey.Open)
        f.addAction("Open sample company", self.open_sample)
        self.recent_menu = f.addMenu("Open recent")
        f.addSeparator()
        self.backup_action = f.addAction("Back up company…", self.backup)
        self.export_action = f.addAction("Export this list (CSV)…", self.export_list)
        self.close_action = f.addAction("Close company", self.close_company)
        f.addSeparator()
        act = f.addAction("Settings…", self.open_settings)
        act.setShortcut("Ctrl+,")
        act = f.addAction("Quit", self.window.close)
        act.setShortcut(QKeySequence.StandardKey.Quit)
        v = m.addMenu("&View")
        act = v.addAction("Search everything…", self.global_search)
        act.setShortcut("Ctrl+K")
        act = v.addAction("Refresh", self.after_change)
        act.setShortcut("F5")
        v.addSeparator()
        tm = v.addMenu("Theme")
        for key, t in th.THEMES.items():
            tm.addAction(t["label"], lambda k=key: self.set_theme(k))
        c = m.addMenu("&Connect")
        c.addAction("Open RevisionWorx", self.open_revisionworx)
        c.addAction("RevisionWorx documents", lambda: self.go("engineering"))
        h = m.addMenu("&Help")
        h.addAction("Keyboard shortcuts…", self.show_shortcuts)
        h.addSeparator()
        h.addAction("Support development…", lambda: webbrowser.open(DONATE_URL))
        h.addAction(f"About {APP_NAME}", lambda: dlg.AboutDialog(self).exec())
        self._rebuild_recent()

    def _rebuild_recent(self):
        self.recent_menu.clear()
        for p in self.settings["recent"]:
            self.recent_menu.addAction(p, lambda x=p: self.open_path(x))
        if not self.settings["recent"]:
            self.recent_menu.addAction("(none)").setEnabled(False)

    def keys(self):
        order = ["dashboard", "items", "sales", "purchasing", "production", "planning", "stock", "invoices", "engineering"]
        for i, k in enumerate(order, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self.window, lambda key=k: self.go(key) if self.company else None)
        QShortcut(QKeySequence("Ctrl+F"), self.window, self._focus_filter)
        QShortcut(QKeySequence("Ctrl+N"), self.window, self._new_here)

    def _focus_filter(self):
        p = self.pages.get(self.current_key)
        if p is not None and hasattr(p, "search"):
            p.search.setFocus()
            p.search.selectAll()

    def _new_here(self):
        p = self.pages.get(self.current_key)
        if self.company and p is not None and getattr(p, "primary_btn", None):
            p.on_primary()

    def show_shortcuts(self):
        QMessageBox.information(self.window, "Keyboard shortcuts", "Ctrl+K\tSearch everything\nCtrl+F\tFilter this list\nCtrl+N\tNew, on this page\nEnter\tOpen the selected row\n"
                                "F5\tRefresh\nCtrl+1…9\tGo to a page\nCtrl+,\tSettings\nCtrl+Q\tQuit")

    # ---- files
    def new_company(self):
        p, _ = QFileDialog.getSaveFileName(self.window, "Create a company file", self._dir() + "/company" + COMPANY_EXTENSION, f"OpenMeridian company (*{COMPANY_EXTENSION})")
        if not p:
            return
        if not p.lower().endswith(COMPANY_EXTENSION):
            p += COMPANY_EXTENSION
        name = os.path.splitext(os.path.basename(p))[0]
        try:
            c = Company.create(p, name)
        except (ERPError, db.CompanyFileError, OSError) as e:
            self.error(str(e))
            return
        self._activate(c)
        self.open_settings()

    def _dir(self):
        rec = self.settings["recent"]
        return os.path.dirname(rec[0]) if rec else os.path.expanduser("~")

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self.window, "Open a company file", self._dir(), f"OpenMeridian company (*{COMPANY_EXTENSION});;All files (*)")
        if p:
            self.open_path(p)

    def open_path(self, path) -> bool:
        try:
            c = Company.open(path)
        except (db.CompanyFileError, ERPError, OSError) as e:
            self.error(str(e))
            return False
        self._activate(c)
        return True

    def open_sample(self):
        d = tempfile.mkdtemp(prefix="openmeridian-sample-")
        self._activate(build_sample(os.path.join(d, "Sample company" + COMPANY_EXTENSION)), remember=False)
        self.set_status("This is a sample company in a temporary folder. Nothing here is real, and it isn't kept.")

    def _activate(self, company, remember=True):
        if self.company:
            self.company.close()
        self.company = company
        if remember:
            self.settings.add_recent(company.path)
            self.settings.save()
            self._rebuild_recent()
        self.root.setCurrentWidget(self.shell)
        self.sidebar.name.setText(company.setting("company_name"))
        self.sidebar.file.setText(os.path.basename(company.path))
        self.sidebar.name.setToolTip(company.path)
        self.window.setWindowTitle(f"{company.setting('company_name')} — {APP_NAME}")
        self.status_user.setText(f"{company.user}  ·  {APP_NAME} {VERSION}")
        self.go("dashboard")
        self.pages["engineering"].fetch()

    def close_company(self):
        if self.company:
            self.company.close()
            self.company = None
        self.start.rebuild()
        self.root.setCurrentWidget(self.start)
        self.window.setWindowTitle(APP_NAME)

    def backup(self):
        if not self.company:
            return
        base = os.path.splitext(self.company.path)[0] + " backup" + COMPANY_EXTENSION
        p, _ = QFileDialog.getSaveFileName(self.window, "Back up the company", base, f"OpenMeridian company (*{COMPANY_EXTENSION})", options=QFileDialog.Option.DontConfirmOverwrite)
        if p:
            try:
                self.company.backup(p)
                self.toast("Backup written and checked.", "success")
            except (db.CompanyFileError, OSError) as e:
                self.error(str(e))

    def export_list(self):
        p = self.pages.get(self.current_key)
        if not self.company or p is None or not hasattr(p, "model"):
            self.toast("Open a list first.")
            return
        path, _ = QFileDialog.getSaveFileName(self.window, "Export this list", f"{p.title}.csv", "CSV file (*.csv)")
        if path:
            try:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    f.write(to_csv([c.title for c in p.model.columns], [[str(c.get(r)) for c in p.model.columns] for r in p.model.rows]))
                self.toast(f"Saved {os.path.basename(path)}", "success")
            except OSError as e:
                self.error(str(e))

    def export_pdf(self, kind, rid, number):
        c = self.company
        html = {"sale": documents.sales_order_html, "purchase": documents.purchase_order_html, "invoice": documents.invoice_html}[kind](c, rid)
        path, _ = QFileDialog.getSaveFileName(self.window, "Export PDF", f"{number}.pdf", "PDF file (*.pdf)")
        if not path:
            return
        self.write_pdf(html, path)
        self.toast(f"Saved {os.path.basename(path)}", "success")

    @staticmethod
    def write_pdf(html, path):
        w = QPdfWriter(path)
        w.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        w.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter)
        doc = QTextDocument()
        doc.setHtml(html)
        doc.setPageSize(w.pageLayout().paintRectPixels(w.resolution()).size().toSizeF())
        doc.print_(w)

    # ---- navigation and refresh
    def go(self, key, record=None):
        if self.company is None:
            return
        self.current_key = key
        page = self.pages[key]
        self.page_stack.setCurrentWidget(page)
        page.setFocus()     # never leaves the ring on the search box when a company opens
        b = self.sidebar.buttons.get(key)
        if b:
            b.setChecked(True)
        if record is not None and hasattr(page, "search"):
            page.search.blockSignals(True)
            page.search.clear()
            page.search.blockSignals(False)
            if getattr(page, "filter_buttons", None):
                first = next(iter(page.filter_buttons))
                page.filter_key = first
                page.filter_buttons[first][0].setChecked(True)
        page.refresh(keep=record)
        self.set_status("Ready.")

    def after_change(self):
        """Something changed: redraw what's on screen, from the file."""
        if self.company is None:
            return
        self.sidebar.name.setText(self.company.setting("company_name"))
        self.pages[self.current_key].refresh()

    def act(self, fn):
        """Run a change. A refusal is a message, never a crash; the file is untouched by a refused change."""
        try:
            res = fn()
        except (ERPError, ValueError) as e:
            self.error(str(e))
            return None
        self.after_change()
        return res if res is not None else True

    def run_guarded(self, fn):
        try:
            return fn()
        except (ERPError, rw.RevisionWorxError, OSError) as e:
            self.error(str(e))
            return None

    def error(self, text):
        m = QMessageBox(self.window)
        m.setIcon(QMessageBox.Icon.Warning)
        m.setWindowTitle(APP_NAME)
        m.setText(text)
        m.exec()

    def set_status(self, text):
        self.status_text.setText(text)

    def toast(self, text, kind="info"):
        t = Toast(self.page_stack if self.company else self.root, text, self.theme, kind)
        host = t.parentWidget()
        t.move(host.width() - t.width() - 18, host.height() - t.height() - 18)

    def open_settings(self):
        d = dlg.SettingsDialog(self)
        if d.exec() and self.company:
            self.window.setWindowTitle(f"{self.company.setting('company_name')} — {APP_NAME}")
            self.pages["engineering"].fetch()
            self.after_change()

    def set_theme(self, name):
        self.theme = th.resolve(name)
        self.settings["theme"] = self.theme.name
        self.qapp.setStyleSheet(th.stylesheet(self.theme))
        self.sidebar.apply_icons()
        for p in self.pages.values():
            if hasattr(p, "rule"):
                p.rule.setStyleSheet(f"background: {self.theme.ui['border']};")
        self.start.rebuild()
        self.settings.save()
        self.after_change()

    def global_search(self):
        if not self.company:
            return
        c = self.company
        rows = []
        for group, entries in NAV:
            for key, text, _i in entries:
                rows.append((f"Go to {text}", (key, None)))
        for i in c.items():
            rows.append((f"Item  {i['number']}  {i['description']}", ("items", i["id"])))
        for o in c.sales_orders():
            rows.append((f"Sales order  {o['number']}  {o['customer']}  {o['reference']}", ("sales", o["id"])))
        for o in c.purchase_orders():
            rows.append((f"Purchase order  {o['number']}  {o['supplier']}  {o['reference']}", ("purchasing", o["id"])))
        for w in c.work_orders():
            rows.append((f"Work order  {w['number']}  {w['item_number']}", ("production", w["id"])))
        for v in c.invoices():
            rows.append((f"Invoice  {v['number']}  {v['customer']}", ("invoices", v["id"])))
        for k in ("customer", "supplier"):
            for p in c.contacts(k):
                rows.append((f"{k.capitalize()}  {p['name']}", (k + "s", p["id"])))
        d = dlg.PickDialog(self, "Search everything", rows, "Type an item, order, customer or page")
        if d.exec() and d.chosen:
            self.go(d.chosen[0], d.chosen[1])

    # ---- RevisionWorx
    def rw_client(self):
        if not self.company:
            return None
        ws = self.company.setting("rw_workspace")
        return rw.Client(ws, configured=self.settings["revisionworx_path"]) if ws else None

    def update_rw_status(self, error, drift):
        s = self.sidebar.rw_status
        if not self.company.setting("rw_workspace"):
            s.setText("RevisionWorx: not connected")
        elif error:
            s.setText("RevisionWorx: unavailable")
        elif drift:
            s.setText(f"RevisionWorx: {len(drift)} out of step")
        else:
            s.setText("RevisionWorx: connected")

    def open_revisionworx(self):
        cmd = rw.find_gui()
        if cmd is None:
            self.error("OpenMeridian can't find RevisionWorx's window. If it is installed, check that revisionworx-gui is on your PATH.")
            return
        ws = self.company.setting("rw_workspace") if self.company else ""
        kw = {"start_new_session": True} if not sys.platform.startswith("win") else {}
        try:
            subprocess.Popen([*cmd, *([ws] if ws else [])], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=rw.child_environment(), **kw)  # noqa: S603
        except OSError as e:
            self.error(f"RevisionWorx could not be started.\n\n{e}")

    def background(self, work, done):
        job = _Job(work)
        self._jobs.add(job)
        job.setAutoDelete(False)

        def finish(res, err):
            self._jobs.discard(job)
            if self.company is not None:
                done(res, err)
        job.signals.finished.connect(finish)
        self.pool.start(job)

    # ---- closing
    def _close_event(self, e):
        self.settings["geometry"] = bytes(self.window.saveGeometry()).hex()
        self.settings.save()
        self.pool.waitForDone(2000)
        if self.company:
            self.company.close()
            self.company = None
        e.accept()


def _exception_hook(exc, val, tb):
    text = "".join(traceback.format_exception(exc, val, tb))
    if sys.stderr is not None:
        sys.stderr.write(text)
    m = QMessageBox()
    m.setIcon(QMessageBox.Icon.Critical)
    m.setWindowTitle(APP_NAME)
    m.setText(f"Something went wrong. Your last completed change is saved.\n\n{val}")
    m.setDetailedText(text)
    m.exec()


def main(path=None) -> int:
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationDisplayName(APP_NAME)
    sys.excepthook = _exception_hook
    app = App(qapp)
    app.window.show()
    if path:
        QTimer.singleShot(0, lambda: app.open_path(path))
    return qapp.exec()


_ = (QAction, QColor, QFont, QPainter, QLineEdit, QScrollArea, csv, io)
