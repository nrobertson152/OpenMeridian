"""The real window, offscreen."""
import os

import pytest
from conftest import CSV, FakeRevisionWorx, M, Q, release

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QTabWidget  # noqa: E402

from openmeridian.company import Company  # noqa: E402
from openmeridian.gui import dialogs as dlg  # noqa: E402
from openmeridian.gui import theme as th  # noqa: E402
from openmeridian.gui.app import App  # noqa: E402
from openmeridian.settings import Settings  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app(qapp, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(App, "error", lambda self, text: errors.append(text))
    a = App(qapp, Settings(str(tmp_path / "settings.json")))
    a.errors = errors
    a.window.show()
    yield a
    a.window.close()
    a.window.deleteLater()      # a window left alive makes every later style change re-polish it
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def sample(app):
    app.open_sample()
    return app


def pump(qapp, n=3):
    for _ in range(n):
        qapp.processEvents()


def test_start_page_then_sample(app, qapp):
    assert app.root.currentWidget() is app.start
    app.open_sample()
    pump(qapp)
    assert app.root.currentWidget() is app.shell and app.current_key == "dashboard"
    assert app.pages["dashboard"].attention.count() > 0


def test_every_page_every_row_shows_a_panel(sample, qapp):
    for key, page in sample.pages.items():
        sample.go(key)
        pump(qapp, 1)
        if not hasattr(page, "proxy"):
            continue
        for r in range(page.proxy.rowCount()):
            page.table.selectRow(r)
            pump(qapp, 1)
            if page.show_panel:
                assert page.panel.lay.count() > 1, f"{key} row {r} has an empty panel"
    assert not sample.errors


def test_every_filter_works(sample, qapp):
    for key, page in sample.pages.items():
        if not hasattr(page, "filter_buttons"):
            continue
        sample.go(key)
        for f in page.filter_buttons:
            page.set_filter(f)
            pump(qapp, 1)
        if page.filter_buttons:
            page.set_filter(next(iter(page.filter_buttons)))


def test_filter_text_narrows_and_empty_state_shows(sample, qapp):
    page = sample.pages["items"]
    sample.go("items")
    n = page.proxy.rowCount()
    page.search.setText("HPU")
    assert 0 < page.proxy.rowCount() < n
    page.search.setText("zzzz-nothing")
    assert page.stack.currentWidget() is page.empty_label and "matches" in page.empty_label.text()
    page.search.clear()


def test_selection_survives_a_change(sample, qapp):
    page = sample.pages["sales"]
    sample.go("sales")
    page.table.selectRow(2)
    key = page.key_of(page.current())
    sample.after_change()
    assert page.key_of(page.current()) == key


def test_go_to_record_clears_filters(sample, qapp):
    c = sample.company
    i = c.item_by_number("PMP-10")
    page = sample.pages["items"]
    sample.go("items")
    page.search.setText("zzzz")
    sample.go("items", i["id"])
    assert page.current()["number"] == "PMP-10" and page.search.text() == ""


def test_full_sale_through_the_panel_buttons(sample, qapp, monkeypatch):
    c = sample.company
    page = sample.pages["sales"]
    item = c.item_by_number("PMP-10")
    cus = c.contacts("customer")[0]["id"]
    so = c.create_sales_order(cus)
    c.add_sales_line(so, item["id"], Q("1"))
    sample.go("sales", so)
    assert page.panel.primary_button.text() == "Confirm order"
    page.panel.primary_button.click()
    pump(qapp)
    assert c.sales_order(so)["status"] == "confirmed" and page.panel.primary_button.text() == "Ship…"
    monkeypatch.setattr(dlg.QuantitiesDialog, "exec", lambda self: (self.submit(), QDialog.DialogCode.Accepted)[1])
    page.panel.primary_button.click()
    pump(qapp)
    assert c.sales_order(so)["status"] == "shipped" and page.panel.primary_button.text() == "Create invoice"
    page.panel.primary_button.click()
    pump(qapp)
    assert c.invoices()[0]["order_id"] == so
    assert not sample.errors


def test_refused_action_is_a_message_and_changes_nothing(sample, qapp):
    c = sample.company
    so = c.create_sales_order(c.contacts("customer")[0]["id"])
    c.add_sales_line(so, c.item_by_number("MTR-7K5")["id"], Q("500"))
    c.confirm_sales_order(so)
    before = len(c.moves())
    sample.act(lambda: c.ship_sales_order(so))
    assert sample.errors and "on hand" in sample.errors[0] and len(c.moves()) == before


def test_item_dialog_validates_and_saves(sample, qapp):
    d = dlg.ItemDialog(sample)
    d.number.setText("NEW-1")
    d.cost.setText("not money")
    d.submit()
    assert d.message.isVisibleTo(d) and sample.company.item_by_number("NEW-1") is None
    d.cost.setText("12.50")
    d.lead.setText("3")
    d.submit()
    i = sample.company.item_by_number("NEW-1")
    assert i["cost"] == M("12.50") and i["lead_days"] == 3
    d2 = dlg.ItemDialog(sample)
    d2.number.setText("new-1")
    d2.submit()
    assert "already" in d2.message.text()


def test_edit_dialog_keeps_values_it_shows(sample, qapp):
    c = sample.company
    i = c.item_by_number("PMP-10")
    d = dlg.ItemDialog(sample, i)
    d.submit()
    j = c.item(i["id"])
    for k in ("number", "description", "kind", "cost", "price", "reorder_point", "reorder_qty", "supplier_id", "lead_days", "bin"):
        assert j[k] == i[k], k


def test_contact_order_and_settings_dialogs(sample, qapp):
    c = sample.company
    d = dlg.ContactDialog(sample, "customer")
    d.name.setText("Newco")
    d.submit()
    assert any(x["name"] == "Newco" for x in c.contacts("customer"))
    o = dlg.OrderDialog(sample, "sale")
    o.due.setText("soon")
    o.submit()
    assert "YYYY-MM-DD" in o.message.text()
    s = dlg.SettingsDialog(sample)
    s.workspace.setText("/definitely/not/a/workspace")
    s.submit()
    assert "isn't a RevisionWorx workspace" in s.message.text()
    s.workspace.setText("")
    s.tax.setText("8.5")
    s.submit()
    assert c.setting("tax_percent") == "8.5"


def test_every_theme_applies(sample, qapp):
    for k in th.THEMES:
        sample.set_theme(k)
        pump(qapp, 1)
        for kind in ("ok", "warning", "danger", "info", "neutral"):
            bg, fg = sample.theme.chip(kind)
            assert bg != fg
    assert sample.settings["theme"] == list(th.THEMES)[-1]


def test_themes_match_openschematix_tokens():
    """The family's colours: same names, same order, same accents."""
    assert list(th.THEMES) == ["modern_light", "modern_dark", "graphite", "neutral_gray", "blueprint", "high_contrast"]
    assert th.THEMES["modern_light"]["ui"]["accent"] == "#2563eb" and th.THEMES["graphite"]["ui"]["accent"] == "#e8a33d"


def test_about_says_what_the_family_says(sample, qapp):
    from PySide6.QtWidgets import QLabel, QPushButton
    d = dlg.AboutDialog(sample)
    text = " ".join(w.text() for w in d.findChildren(QLabel)) + " ".join(b.text() for b in d.findChildren(QPushButton))
    assert "Nate Robertson" in text and "GNU General Public License" in text and "no telemetry" in text and "Ko-fi" in text and "Licence text" in text


def test_pdf_export(sample, tmp_path, qapp):
    from openmeridian import documents
    c = sample.company
    inv = c.invoices()[0]
    html = documents.invoice_html(c, inv["id"])
    assert inv["number"] in html and "Northline" in html
    p = str(tmp_path / "i.pdf")
    sample.write_pdf(html, p)
    assert open(p, "rb").read(5) == b"%PDF-" and os.path.getsize(p) > 500


def test_html_is_escaped(sample):
    from openmeridian import documents
    c = sample.company
    cus = c.add_contact("customer", "<script>x</script>")
    so = c.create_sales_order(cus)
    assert "<script>" not in documents.sales_order_html(c, so)


def test_csv_blocks_formulas():
    from openmeridian.report_csv import to_csv
    text = to_csv(["A"], [["=cmd()"], ["-5"], ["@x"]])
    assert "'=cmd()" in text and "'@x" in text and "'-5" not in text


def test_bad_file_is_a_message(app, tmp_path):
    p = tmp_path / "x.meridian"
    p.write_bytes(b"nope")
    assert not app.open_path(str(p))
    assert app.errors and app.company is None


def test_real_company_file_round_trip_through_the_window(app, tmp_path, qapp):
    p = str(tmp_path / "c.meridian")
    Company.create(p, "My Works").close()
    assert app.open_path(p)
    pump(qapp)
    assert "My Works" in app.window.windowTitle() and app.sidebar.name.text() == "My Works"
    assert p in app.settings["recent"]
    app.close_company()
    assert app.root.currentWidget() is app.start and app.company is None
    assert QMessageBox is not None


@pytest.mark.parametrize("name", list(th.THEMES))
@pytest.mark.parametrize("kind", ["ok", "warning", "danger", "info", "neutral"])
def test_status_text_is_readable_on_every_theme(name, kind):
    """High contrast's white body text on its yellow warning block couldn't be read."""
    t = th.resolve(name)
    bg, fg = t.chip(kind)
    assert th.contrast(bg, fg) >= 4.5 and th.contrast(bg, t.chip_body(kind)) >= 4.5


def test_form_combos_show_an_arrow(sample, qapp):
    """The style sheet removes the native arrow: every form's combo must paint its own, or it reads as a text field."""
    from openmeridian.gui.widgets import Combo
    d = dlg.ItemDialog(sample)
    assert isinstance(d.kind, Combo)
    d.show()
    pump(qapp)
    img = d.kind.grab().toImage()
    bg = img.pixelColor(img.width() // 2, img.height() // 2)
    y = img.height() // 2
    assert any(img.pixelColor(x, y) != bg for x in range(img.width() - 20, img.width() - 8))
    d.close()


def _settle(app, qapp):
    import time
    end = time.time() + 30
    while app._jobs and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    pump(qapp)


def test_real_revisionworx_through_the_window(app, qapp, workspace, tmp_path, monkeypatch):
    w = workspace
    release(w, w.rev)
    p = str(tmp_path / "c.meridian")
    Company.create(p, "My Works").close()
    assert app.open_path(p)
    c = app.company
    c.set_setting("rw_workspace", w.path)
    page = app.pages["engineering"]
    app.go("engineering")
    page.fetch()
    _settle(app, qapp)
    assert page.proxy.rowCount() == 1 and app.sidebar.rw_status.text() == "RevisionWorx: connected"
    page.table.selectRow(0)
    pump(qapp)
    assert page.panel.primary_button.text().startswith("Import BOM")
    monkeypatch.setattr(dlg, "confirm", lambda *a, **k: True)
    page.import_bom_flow(None, w.doc)
    root = c.item_by_number("HPU-SKID")
    assert root and len(c.bom(root["id"])) == 2 and app.current_key == "items" and not app.errors
    # a release in RevisionWorx shows up in the sidebar and the panel
    c.update_item(root["id"], rw_document=w.doc, rw_number="BOM-1")
    w.run("doc", "checkout", w.doc)
    w.file.write_text(CSV.replace("HPU-SKID,2,MOTOR,,2,", "HPU-SKID,2,MOTOR,,3,"), encoding="utf-8")
    release(w, w.run("doc", "checkin", w.doc, "-m", "second")["id"])
    app.go("engineering")
    page.fetch()
    _settle(app, qapp)
    assert app.sidebar.rw_status.text() == "RevisionWorx: 1 out of step"
    # ... and on the Overview, and on the item
    app.go("dashboard")
    rows = [app.pages["dashboard"].attention.item(i).text() for i in range(app.pages["dashboard"].attention.count())]
    assert any("HPU-SKID" in t and "released" in t for t in rows)
    app.go("items", root["id"])
    tabs = app.pages["items"].panel.findChild(QTabWidget)
    from PySide6.QtWidgets import QLabel
    text = " ".join(x.text() for x in tabs.findChildren(QLabel))
    assert "Out of step" in text


def test_moving_through_items_never_runs_revisionworx(app, qapp, tmp_path, monkeypatch):
    """Selecting a linked item ran a program per row on the window's thread."""
    from openmeridian import revisionworx as rw
    (tmp_path / ".revisionworx").mkdir()
    p = str(tmp_path / "c.meridian")
    Company.create(p, "A").close()
    app.open_path(p)
    c = app.company
    c.set_setting("rw_workspace", str(tmp_path))
    i = c.add_item("I")
    c.update_item(i, rw_document="doc_x", rw_number="N")

    def boom(*a, **k):
        raise AssertionError("ran RevisionWorx on the window's thread")
    monkeypatch.setattr(rw.Client, "_run", boom)
    monkeypatch.setattr(rw.Client, "detail", boom)
    page = app.pages["items"]
    app.go("items", i)
    pump(qapp)
    assert page.current()["number"] == "I"


def test_answer_for_a_closed_company_is_ignored(app, qapp, tmp_path, monkeypatch):
    """RevisionWorx answering about company A must not paint its documents over company B."""
    from openmeridian import revisionworx as rw
    (tmp_path / ".revisionworx").mkdir()
    a, b = str(tmp_path / "a.meridian"), str(tmp_path / "b.meridian")
    Company.create(a, "A").close()
    Company.create(b, "B").close()
    app.open_path(a)
    app.company.set_setting("rw_workspace", str(tmp_path))
    doc = rw.Document("d", "N", "T", "f", "t", "A", "wip", "", "")
    monkeypatch.setattr(rw.Client, "documents", lambda self: [doc])
    monkeypatch.setattr(rw.Client, "changes", lambda self, open_only=True: [])
    monkeypatch.setattr(rw, "find_drift", lambda comp, client: [])
    page = app.pages["engineering"]
    page.fetch()
    app.open_path(b)
    _settle(app, qapp)
    assert page.docs == []
    assert QMessageBox is not None


def _panel_text(page):
    from PySide6.QtWidgets import QLabel, QPushButton, QTableWidget
    texts = [x.text() for x in page.panel.inner.findChildren(QLabel)]
    for t in page.panel.inner.findChildren(QTableWidget):
        texts += [t.item(r, c).text() for r in range(t.rowCount()) for c in range(t.columnCount()) if t.item(r, c)]
    buttons = [b.text() for b in page.panel.inner.findChildren(QPushButton)]
    return " | ".join(texts), buttons


def _serial_work_order(c, qty="2"):
    part = c.add_item("MOTOR", "Motor", "buy")
    c.adjust_stock(part, Q("5"), "opening")
    x = c.add_item("HPU-75", "Hydraulic power unit", "make", tracking="serial")
    c.set_bom_line(x, part, Q("1"))
    wo = c.create_work_order(x, Q(qty))
    c.release_work_order(wo)
    return wo


def test_completing_with_serials_then_registering_through_the_window(app, qapp, tmp_path, monkeypatch):
    p = str(tmp_path / "c.meridian")
    Company.create(p, "My Works").close()
    assert app.open_path(p)
    c = app.company
    wo = _serial_work_order(c)
    c.set_setting("rw_workspace", str(tmp_path / "eng"))
    fake = FakeRevisionWorx()
    fake.refuse = ("the workspace is busy: someone else is saving. Try again", "busy")
    monkeypatch.setattr(app, "rw_client", lambda: fake)
    page = app.pages["production"]
    app.go("production", wo)
    pump(qapp)
    assert page.panel.primary_button.text() == "Complete…"

    def made(serials):
        def run(self):
            assert self.serials is not None, "an item made with serial numbers asks for them"
            self.serials.setPlainText(serials)
            self.submit()
            return self.result()
        return run
    monkeypatch.setattr(dlg.CompleteDialog, "exec", made("NH-1"))
    page.panel.primary_button.click()
    pump(qapp)
    assert c.units_built(wo) == [] and c.work_order(wo)["done"] == 0, "one serial for two units: refused, nothing made"
    monkeypatch.setattr(dlg.CompleteDialog, "exec", made("NH-1\nNH-2"))
    page.panel.primary_button.click()
    pump(qapp)
    assert [u["serial"] for u in c.units_built(wo)] == ["NH-1", "NH-2"] and c.work_order(wo)["status"] == "complete"
    assert len(app.errors) == 1 and "NH-1, NH-2: the workspace is busy" in app.errors[0]
    text, buttons = _panel_text(page)
    assert "Not in RevisionWorx yet" in text and "The 2 units made aren't in its unit register. The workspace is busy" in text
    assert "UNITS BUILT (2)" in text and text.count("Not registered") == 2
    assert page.panel.primary_button.text() == "Register in RevisionWorx"

    fake.refuse = None
    page.panel.primary_button.click()
    pump(qapp)
    assert all(u["rw_unit"] for u in c.units_built(wo)) and len(fake.calls) == 2 and fake.calls[0] == fake.calls[1]
    text, buttons = _panel_text(page)
    assert "Not in RevisionWorx yet" not in text and text.count("Registered") == 2 and "Register in RevisionWorx" not in buttons
    assert len(app.errors) == 1


def test_without_revisionworx_units_built_are_listed_and_nothing_is_sent(app, qapp, tmp_path, monkeypatch):
    p = str(tmp_path / "c.meridian")
    Company.create(p, "My Works").close()
    assert app.open_path(p)
    c = app.company
    wo = _serial_work_order(c, "1")
    monkeypatch.setattr(app, "rw_client", lambda: pytest.fail("RevisionWorx isn't connected, so it isn't asked"))
    c.complete_work_order(wo, Q("1"), ["NH-7"])
    app.go("production", wo)
    pump(qapp)
    text, buttons = _panel_text(app.pages["production"])
    assert "UNITS BUILT (1)" in text and "NH-7" in text and "RevisionWorx" not in text
    assert "Register in RevisionWorx" not in buttons
    # the item says it's made with serial numbers, and its ledger says which unit came in
    app.go("items", c.item_by_number("HPU-75")["id"])
    pump(qapp)
    text, _ = _panel_text(app.pages["items"])
    assert "Each unit made has one" in text and f"{c.work_order(wo)['number']} · NH-7" in text


def test_item_dialog_offers_serial_numbers_only_for_items_made_and_lots_for_any(sample, qapp):
    def offered(dialog, tracking):
        return dialog.tracking.model().item(dialog.tracking.findData(tracking)).isEnabled()
    d = dlg.ItemDialog(sample)
    d.number.setText("SER-1")
    assert not offered(d, "serial") and d.tracking.currentData() == "none", "a bought item has no serial numbers here"
    assert offered(d, "lot"), "but it can be bought in lots"
    d.kind.setCurrentIndex(d.kind.findData("make"))
    assert offered(d, "serial") and offered(d, "lot")
    d.tracking.setCurrentIndex(d.tracking.findData("serial"))
    d.submit()
    item = sample.company.item_by_number("SER-1")
    assert item["tracking"] == "serial" and item["kind"] == "make"
    # made into a bought item, it stops having them (allowed while none is in stock)
    e = dlg.ItemDialog(sample, item)
    assert offered(e, "serial") and e.tracking.currentData() == "serial"
    e.kind.setCurrentIndex(e.kind.findData("buy"))
    assert e.tracking.currentData() == "none" and not offered(e, "serial")
    e.submit()
    assert sample.company.item_by_number("SER-1")["tracking"] == "none"
    # lots stay chosen whichever way the item goes
    g = dlg.ItemDialog(sample)
    g.number.setText("LOT-1")
    g.tracking.setCurrentIndex(g.tracking.findData("lot"))
    g.kind.setCurrentIndex(g.kind.findData("make"))
    g.kind.setCurrentIndex(g.kind.findData("buy"))
    assert g.tracking.currentData() == "lot"
    g.submit()
    assert sample.company.item_by_number("LOT-1")["tracking"] == "lot"
    # the rule is the company's, whatever the window shows
    f = dlg.ItemDialog(sample)
    f.number.setText("SER-2")
    f.tracking.setCurrentIndex(f.tracking.findData("serial"))
    f.submit()
    assert "items you make" in f.message.text() and sample.company.item_by_number("SER-2") is None


def test_units_made_are_registered_in_the_real_revisionworx_through_the_window(app, qapp, workspace, tmp_path, monkeypatch):
    w = workspace
    release(w, w.rev)
    p = str(tmp_path / "c.meridian")
    Company.create(p, "My Works").close()
    assert app.open_path(p)
    c = app.company
    c.set_setting("rw_workspace", w.path)
    part = c.add_item("MOTOR", "Motor", "buy")
    c.adjust_stock(part, Q("5"), "opening")
    x = c.add_item("HPU-75", "Hydraulic power unit", "make", tracking="serial")
    c.set_bom_line(x, part, Q("1"))
    c.update_item(x, rw_document=w.doc, rw_number="BOM-1")
    wo = c.create_work_order(x, Q("2"))
    page = app.pages["production"]
    app.go("production", wo)
    pump(qapp)
    page.panel.primary_button.click()                     # Release: records the released revision from RevisionWorx
    pump(qapp)
    assert c.work_order(wo)["build_rw_revision"] == w.rev

    def made(self):
        self.serials.setPlainText("NH-26-0001\nNH-26-0002")
        self.submit()
        return self.result()
    monkeypatch.setattr(dlg.CompleteDialog, "exec", made)
    page.panel.primary_button.click()                     # Complete…: then registered in RevisionWorx
    pump(qapp)
    assert not app.errors
    units = c.units_built(wo)
    assert [u["serial"] for u in units] == ["NH-26-0001", "NH-26-0002"] and all(u["rw_unit"] for u in units)
    client = app.rw_client()
    got = client._link("unit", "NH-26-0002")["unit"]
    assert got["id"] == units[1]["rw_unit"] and got["status"] == "built" and got["model"]["number"] == "HPU-75"
    assert [d["revision"]["id"] for d in got["documents"]] == [w.rev]
    text, buttons = _panel_text(page)
    assert text.count("Registered") == 2 and "Register in RevisionWorx" not in buttons


# ---------------------------------------------------------------- lots through the window
def _lot_company(app, tmp_path):
    p = str(tmp_path / "lots.meridian")
    Company.create(p, "Lot Works").close()
    assert app.open_path(p)
    c = app.company
    sup = c.add_contact("supplier", "Hose Co")
    cus = c.add_contact("customer", "Bayside")
    hose = c.add_item("HSE", "Hose", "buy", cost=M("5"), tracking="lot")
    kit = c.add_item("KIT", "Hose kit", "make", price=M("40"), tracking="lot")
    c.set_bom_line(kit, hose, Q("2"))
    po = c.create_purchase_order(sup)
    line = c.add_purchase_line(po, hose, Q("10"), M("5"))
    c.place_purchase_order(po)
    return c, sup, cus, hose, kit, po, line


def test_receiving_completing_and_shipping_say_which_lots_through_the_window(app, qapp, tmp_path, monkeypatch):
    c, _sup, cus, hose, kit, po, line = _lot_company(app, tmp_path)
    page = app.pages["purchasing"]
    app.go("purchasing", po)
    pump(qapp)
    assert page.panel.primary_button.text() == "Receive…"

    def receive(lot, qty):
        def run(self):
            assert self.table.horizontalHeaderItem(4).text() == "Lot"
            assert self.lot_edits[line].placeholderText() == "Supplier's lot"
            if lot == "H-1":
                self.submit()                       # no lot given: refused, nothing received
                assert "say which lot it came in as" in self.message.text() and c.lots(hose) == []
            self.table.item(self.line_row[line], 3).setText(qty)
            self.lot_edits[line].setText(lot)
            self.submit()
            return self.result()
        return run
    monkeypatch.setattr(dlg.QuantitiesDialog, "exec", receive("H-1", "6"))
    page.panel.primary_button.click()
    pump(qapp)
    monkeypatch.setattr(dlg.QuantitiesDialog, "exec", receive("H-2", "4"))
    page.panel.primary_button.click()
    pump(qapp)
    assert [(x["lot"], x["on_hand"]) for x in c.lots(hose)] == [("H-1", Q("6")), ("H-2", Q("4"))]
    assert c.purchase_order(po)["status"] == "received"

    wo = c.create_work_order(kit, Q("3"))
    c.release_work_order(wo)
    page = app.pages["production"]
    app.go("production", wo)
    pump(qapp)

    def complete(self):
        assert self.made_lot.text() == "WO-00001"
        used = {lot: self.lots.item(r, 3).text() for r, _cid, lot in self.lot_rows}
        assert used == {"H-1": "6", "H-2": "0"}, "filled in oldest first for 3 kits"
        self.qty.setText("2")
        used = {lot: self.lots.item(r, 3).text() for r, _cid, lot in self.lot_rows}
        assert used == {"H-1": "4", "H-2": "0"}, "and again for 2"
        for r, _cid, lot in self.lot_rows:          # what actually went in
            self.lots.item(r, 3).setText({"H-1": "1", "H-2": "3"}[lot])
        self.submit()
        return self.result()
    monkeypatch.setattr(dlg.CompleteDialog, "exec", complete)
    page.panel.primary_button.click()
    pump(qapp)
    assert {x["lot"]: x["on_hand"] for x in c.lots(hose)} == {"H-1": Q("5"), "H-2": Q("1")}
    assert [(x["lot"], x["on_hand"]) for x in c.lots(kit)] == [("WO-00001", Q("2"))]
    text, _buttons = _panel_text(page)
    assert "LOTS" in text and "H-2" in text and "WO-00001" in text

    so = c.create_sales_order(cus)
    sl = c.add_sales_line(so, kit, Q("2"))
    c.confirm_sales_order(so)
    page = app.pages["sales"]
    app.go("sales", so)
    pump(qapp)

    def ship(self):
        (r, lot), = self.lot_rows[sl]
        assert lot == "WO-00001" and self.table.item(r, 3).text() == "2"
        self.table.item(r, 3).setText("1")
        assert self.table.item(self.line_row[sl], 3).text() == "1", "the line ships what its lots add up to"
        self.submit()
        return self.result()
    monkeypatch.setattr(dlg.QuantitiesDialog, "exec", ship)
    page.panel.primary_button.click()
    pump(qapp)
    assert c.sales_lines(so)[0]["shipped"] == Q("1") and c.lot_on_hand(kit, "WO-00001") == Q("1")
    # the stock ledger shows each move's lot, and finds a lot's moves by it
    ledger = app.pages["stock"]
    app.go("stock")
    ledger.search.setText("h-2")
    pump(qapp)
    shown = [ledger.model.rows[i] for i in range(len(ledger.model.rows))]
    assert sorted((m["kind"], m["qty"]) for m in shown) == [("consume", -Q("3")), ("receipt", Q("4"))]
    assert "Lot or serial" in [col.title for col in ledger.model.columns]
    assert not app.errors


def test_a_lot_is_traced_from_the_item_page_and_saved_as_csv(app, qapp, tmp_path, monkeypatch):
    c, _sup, cus, hose, kit, po, line = _lot_company(app, tmp_path)
    c.receive_purchase_order(po, None, {line: "H-1"})
    wo = c.create_work_order(kit, Q("2"))
    c.release_work_order(wo)
    c.complete_work_order(wo, lots={hose: [("H-1", Q("4"))]})
    so = c.create_sales_order(cus)
    sl = c.add_sales_line(so, kit, Q("1"))
    c.confirm_sales_order(so)
    c.ship_sales_order(so, None, {sl: [("WO-00001", Q("1"))]})
    page = app.pages["items"]
    app.go("items", hose)
    pump(qapp)
    tabs = page.panel.inner.findChild(QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())][:2] == ["Details", "Lots"]
    text, buttons = _panel_text(page)
    assert "By lot. Each receipt, use and shipment says which" in text and "Trace…" in buttons and "lot H-1" in text
    seen = {}

    def show(self):
        seen["summary"] = " ".join(x.text() for x in self.findChildren(QLabel))
        top = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        seen["sections"] = [t.text(0) for t in top]
        went = top[1]
        seen["went"] = [went.child(i).text(0) for i in range(went.childCount())]
        seen["made"] = went.child(0).child(0).text(1), went.child(0).child(0).text(2)
        self.save_csv(str(tmp_path / "trace.csv"))
        return 0
    monkeypatch.setattr(dlg.TraceDialog, "exec", show)
    page.trace(hose, "h-1")
    assert seen["sections"] == ["Where it came from", "Where it went"]
    assert seen["went"] == ["Used", "In stock"] and seen["made"] == ("KIT", "WO-00001")
    assert "1 shipment carried it or what was made from it, to Bayside" in seen["summary"]
    csv_text = (tmp_path / "trace.csv").read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0] == "Section,Level,What,Item,Lot or serial,Qty,Reference,Customer or supplier,Date,Note"
    assert "Where it went,2,Shipped,KIT,WO-00001,1,SO-00001,Bayside" in csv_text
    page.trace(hose, "NO-SUCH")                     # a refusal is a message, never a crash
    assert app.errors and "HSE has no lot NO-SUCH" in app.errors[-1]


def test_adjusting_a_lot_and_finding_a_lot_from_search(app, qapp, tmp_path, monkeypatch):
    c, _sup, _cus, hose, _kit, po, line = _lot_company(app, tmp_path)
    c.receive_purchase_order(po, None, {line: "H-1"})
    d = dlg.AdjustDialog(app, c.item(hose))
    assert [d.lot.itemText(i) for i in range(d.lot.count())] == ["H-1"]
    assert d.lot.currentText() == "", "no lot is chosen for the person"
    d.delta.setText("-1")
    d.note.setText("count")
    d.submit()
    assert "say which lot is being adjusted" in d.message.text()
    d.lot.setCurrentText("H-9")
    d.delta.setText("-1")
    d.note.setText("count")
    d.submit()
    assert "H-9 has 0 on hand" in d.message.text()
    d.delta.setText("2")
    d.note.setText("found, labelled H-9")
    d.submit()
    assert c.lot_on_hand(hose, "H-9") == Q("2")
    rows = []

    class Pick:
        def __init__(self, _app, _title, found, _placeholder=""):
            rows.extend(found)
            self.chosen = None

        def exec(self):
            return 0
    monkeypatch.setattr(dlg, "PickDialog", Pick)
    app.global_search()
    assert ("Lot  H-9  HSE  Hose", ("items", hose)) in rows
