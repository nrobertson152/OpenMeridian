"""Shared pieces: table model, status chips, list page with a contextual panel, status block, forms."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPointF, QRectF, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


CHIP_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_ROLE = Qt.ItemDataRole.UserRole + 2
SORT_ROLE = Qt.ItemDataRole.UserRole + 3

STATUS_CHIPS = {"draft": "neutral", "confirmed": "info", "ordered": "info", "released": "info", "shipped": "ok", "received": "ok",
                "complete": "ok", "paid": "ok", "open": "warning", "overdue": "danger", "cancelled": "neutral", "void": "neutral",
                "buy": "neutral", "make": "info", "low": "warning", "out": "danger", "ok": "ok"}


@dataclass
class Column:
    title: str
    get: Callable
    width: int = 110
    stretch: bool = False
    right: bool = False
    chip: bool = False
    mono: bool = False
    sort: Callable | None = None
    warn: Callable | None = None        # row -> True: show this cell's value in the danger colour


class RowsModel(QAbstractTableModel):
    def __init__(self, columns, parent=None, get_theme=None):
        super().__init__(parent)
        self.columns = columns
        self.get_theme = get_theme
        self.rows: list = []

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        col = self.columns[index.column()]
        row = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return str(col.get(row))
        if role == CHIP_ROLE:
            return col.chip
        if role == ROW_ROLE:
            return row
        if role == SORT_ROLE:
            return col.sort(row) if col.sort else str(col.get(row)).casefold()
        if role == Qt.ItemDataRole.ForegroundRole and col.warn and self.get_theme and col.warn(row):
            return QColor(self.get_theme().ui["danger"])
        if role == Qt.ItemDataRole.TextAlignmentRole and col.right:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.columns[section].title
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int((Qt.AlignmentFlag.AlignRight if self.columns[section].right else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
        return None


def paint_chip(p: QPainter, rect, text: str, theme, kind: str | None = None) -> None:
    kind = kind or STATUS_CHIPS.get(text.lower(), "neutral")
    bg, fg = theme.chip(kind)
    label = text.capitalize()
    f = QFont(p.font())
    f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
    f.setWeight(QFont.Weight.DemiBold)
    p.save()
    p.setFont(f)
    w = p.fontMetrics().horizontalAdvance(label) + 16
    h = min(rect.height() - 6, 20)
    r = QRectF(rect.left() + 8, rect.top() + (rect.height() - h) / 2, min(w, rect.width() - 10), h)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(bg))
    p.drawRoundedRect(r, 5, 5)
    p.setPen(QColor(fg))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
    p.restore()


class ChipDelegate(QStyledItemDelegate):
    """Draws status columns as chips. Every other cell is the normal item."""

    def __init__(self, get_theme, parent=None):
        super().__init__(parent)
        self.get_theme = get_theme

    def paint(self, p, option, index):
        if not index.data(CHIP_ROLE):
            return super().paint(p, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        opt.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        if text:
            paint_chip(p, option.rect, text, self.get_theme())

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), max(s.height(), 32))


class EnterTable(QTableView):
    """Enter on a row does what a double-click does, as in RevisionWorx."""
    enter_pressed = Signal()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self.enter_pressed.emit()
            e.accept()
        else:
            super().keyPressEvent(e)


def label(text="", name="", wrap=False) -> QLabel:
    w = QLabel(str(text))
    if name:
        w.setObjectName(name)
    if wrap:
        w.setWordWrap(True)
        w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return w


def button(text, fn=None, primary=False, name="") -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    elif name:
        b.setObjectName(name)
    if fn:
        b.clicked.connect(lambda _=False: fn())
    return b


class Combo(QComboBox):
    """A combo box that looks like one. The style sheet removes the native arrow, and a style sheet can only
    draw an image from a file, so the chevron is painted here in the theme's own text colour."""

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self.palette().color(self.foregroundRole()), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x, y = self.width() - 14.0, self.height() / 2.0
        p.drawPolyline([QPointF(x - 3.5, y - 1.5), QPointF(x, y + 2), QPointF(x + 3.5, y - 1.5)])
        p.end()


class StatusBlock(QFrame):
    """One sentence saying what is true and what to do next (RevisionWorx's design principle)."""

    def __init__(self, theme, kind, title, text=""):
        super().__init__()
        bg, fg = theme.chip(kind)
        self.setStyleSheet(f"StatusBlock {{ background: {bg}; border-radius: 8px; }} QLabel {{ background: transparent; color: {theme.chip_body(kind)}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(2)
        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet(f"font-weight: 700; color: {fg};")
        lay.addWidget(t)
        if text:
            b = QLabel(text)
            b.setWordWrap(True)
            lay.addWidget(b)


class KeyValues(QWidget):
    def __init__(self, rows):
        super().__init__()
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(5)
        g.setColumnStretch(1, 1)
        for i, (k, v) in enumerate(rows):
            g.addWidget(label(k, "muted"), i, 0, Qt.AlignmentFlag.AlignTop)
            val = label(v)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            g.addWidget(val, i, 1)


class MiniTable(QTableWidget):
    """Small read-only table for a contextual panel."""
    def __init__(self, headers, rows, right=(), on_activate=None, max_rows=10):
        super().__init__(len(rows), len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                it = QTableWidgetItem(str(v))
                it.setToolTip(str(v))
                if c in right:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(r, c, it)
        for c in right:
            hi = self.horizontalHeaderItem(c)
            if hi:
                hi.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        if len(headers) > 1:
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setDefaultSectionSize(28)
        self.setFixedHeight(32 + 28 * max(1, min(len(rows), max_rows)))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if len(rows) > max_rows else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if on_activate:
            self.cellDoubleClicked.connect(lambda r, _c: on_activate(r))

    def selected_row(self) -> int:
        return self.currentRow()


class DetailPanel(QScrollArea):
    """The panel beside a list: title, status, the one next step, then details."""

    def __init__(self):
        super().__init__()
        self.setObjectName("detailScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.inner.setObjectName("detailPanel")
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(9)
        self.setWidget(self.inner)
        self.setMinimumWidth(340)

    def clear(self):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def title(self, text, sub=""):
        t = label(text, "detailTitle")
        t.setWordWrap(True)
        t.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lay.addWidget(t)
        if sub:
            s = label(sub, "muted")
            s.setWordWrap(True)
            self.lay.addWidget(s)

    def add(self, w):
        self.lay.addWidget(w)
        return w

    def section(self, text):
        self.lay.addWidget(label(text.upper(), "sectionTitle"))

    def actions(self, primary=None, secondary=(), more=(), more_icon=None):
        """One filled button: the obvious next step. Everything else stays out of the way."""
        row = QHBoxLayout()
        row.setSpacing(6)
        if primary:
            b = button(primary[0], primary[1], primary=True)
            row.addWidget(b, 1)
            self.primary_button = b
        for text, fn in secondary:
            row.addWidget(button(text, fn))
        if more:
            m = QPushButton("···")
            m.setToolTip("More actions")
            m.setFixedWidth(36)
            menu = QMenu(m)
            for text, fn in more:
                if text == "-":
                    menu.addSeparator()
                else:
                    menu.addAction(text, fn)
            m.setMenu(menu)
            row.addWidget(m)
        if not primary:
            row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 2, 0, 2)
        self.lay.addWidget(holder)

    def finish(self):
        self.lay.addStretch(1)

    def empty(self, text):
        self.clear()
        self.lay.addStretch(1)
        lab = label(text, "muted")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setWordWrap(True)
        self.lay.addWidget(lab)
        self.lay.addStretch(2)


class ListPage(QWidget):
    """Header, filters and search, a table, and a contextual panel: the layout of every list in the program."""
    title = ""
    subtitle = ""
    primary_label = ""
    empty_text = "Nothing here yet."
    no_match_text = "Nothing matches this filter."
    select_text = "Select a row to see its details."
    show_panel = True

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.filter_key = None
        self._keep = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(20, 16, 20, 8)
        head.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label(self.title, "pageTitle"))
        self.sub = label(self.subtitle, "pageSub")
        titles.addWidget(self.sub)
        head.addLayout(titles, 1)
        self.head = head
        self.primary_btn = None
        self.add_header_buttons(head)
        if self.primary_label:
            self.primary_btn = button(self.primary_label, self.on_primary, primary=True)
            head.addWidget(self.primary_btn)
        outer.addLayout(head)
        bar = QHBoxLayout()
        bar.setContentsMargins(20, 0, 20, 8)
        bar.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.filter_buttons = {}
        for text, key in self.filters():
            b = QPushButton(text)
            b.setObjectName("filter")
            b.setCheckable(True)
            self.group.addButton(b)
            self.filter_buttons[key] = (b, text)
            bar.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
        if self.filter_buttons:
            first = next(iter(self.filter_buttons))
            self.filter_buttons[first][0].setChecked(True)
            self.filter_key = first
        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter this list")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(230)
        self.search.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search)
        outer.addLayout(bar)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {self.app.theme.ui['border']};")
        self.rule = line
        outer.addWidget(line)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(1)
        self.split.setChildrenCollapsible(False)
        self.stack = QStackedWidget()
        self.table = EnterTable()
        self.model = RowsModel(self.columns(), get_theme=lambda: self.app.theme)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setTabKeyNavigation(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setItemDelegate(ChipDelegate(lambda: self.app.theme, self.table))
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(False)
        for i, c in enumerate(self.model.columns):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if c.stretch else QHeaderView.ResizeMode.Interactive)
            if not c.stretch:
                self.table.setColumnWidth(i, c.width)
        self.empty_label = label("", "muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty_label)
        self.split.addWidget(self.stack)
        self.panel = DetailPanel()
        if self.show_panel:
            self.split.addWidget(self.panel)
            self.split.setStretchFactor(0, 3)
            self.split.setStretchFactor(1, 2)
            self.split.setSizes([640, 400])
        outer.addWidget(self.split, 1)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._selected())
        self.table.doubleClicked.connect(lambda _i: self.on_activate())
        self.table.enter_pressed.connect(self.on_activate)
        self.panel.empty(self.select_text)

    # ---- for subclasses
    def columns(self):
        raise NotImplementedError

    def filters(self):
        return []

    def load(self):
        raise NotImplementedError

    def key_of(self, row):
        return row["id"]

    def fill(self, row):
        pass

    def on_primary(self):
        pass

    def on_activate(self):
        pass

    def add_header_buttons(self, head):
        pass

    def filter_counts(self):
        return {}

    # ---- behaviour
    def set_filter(self, key):
        self.filter_key = key
        self.filter_buttons[key][0].setChecked(True)
        self.refresh()

    def text(self):
        return self.search.text().strip()

    def current(self):
        idx = self.table.currentIndex()
        return idx.data(ROW_ROLE) if idx.isValid() else None

    def select_key(self, key):
        for r in range(self.proxy.rowCount()):
            row = self.proxy.index(r, 0).data(ROW_ROLE)
            if self.key_of(row) == key:
                self.table.selectRow(r)
                self.table.scrollTo(self.proxy.index(r, 0))
                return True
        return False

    def refresh(self, keep=None):
        if self.app.company is None:
            return
        cur = self.current()
        key = keep if keep is not None else (self.key_of(cur) if cur else None)
        self._loading = True
        rows = self.load()
        self.model.set_rows(rows)
        counts = self.filter_counts()
        for k, (b, text) in self.filter_buttons.items():
            b.setText(f"{text}  {counts[k]}" if k in counts else text)
        if rows:
            self.stack.setCurrentWidget(self.table)
        else:
            has_filter = bool(self.text()) or (self.filter_buttons and self.filter_key != next(iter(self.filter_buttons)))
            self.empty_label.setText(self.no_match_text if has_filter else self.empty_text)
            self.stack.setCurrentWidget(self.empty_label)
        self._loading = False
        if key is None or not self.select_key(key):
            if self.proxy.rowCount():
                self.table.selectRow(0)
            else:
                self._selected()
        else:
            self._selected()

    def _selected(self):
        if getattr(self, "_loading", False):
            return
        row = self.current()
        if not self.show_panel:
            return
        self.panel.clear()
        if row is None:
            self.panel.empty(self.select_text)
            return
        self.fill(row)
        self.panel.finish()
