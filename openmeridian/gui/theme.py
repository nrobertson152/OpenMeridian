"""Themes. The colour tokens are OpenSchematix's own (openschematix/gui/theme.py, GPL-3.0-or-later), so the family
matches theme for theme, and OpenMeridian follows the theme you chose there the first time it starts."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication

THEMES = {
    "modern_light": {"label": "Modern Light", "dark": False,
        "ui": {"bg": "#f3f4f6", "surface": "#ffffff", "surface2": "#f7f8fa", "border": "#dcdfe4", "border_strong": "#c3c8cf",
               "text": "#1b1f24", "muted": "#626b75", "faint": "#8a929b", "accent": "#2563eb", "accent_text": "#ffffff",
               "accent_soft": "#e0eaff", "hover": "#eceef1", "pressed": "#dfe3e8", "input": "#ffffff", "select_bg": "#dbe6ff",
               "select_fg": "#10244d", "tooltip_bg": "#1f2329", "tooltip_fg": "#f5f6f8", "danger": "#d9364f", "warning": "#c27803",
               "success": "#1f8a46", "info": "#2563eb", "focus": "#2563eb"}},
    "modern_dark": {"label": "Modern Dark", "dark": True,
        "ui": {"bg": "#16181c", "surface": "#1e2126", "surface2": "#23272d", "border": "#2e333a", "border_strong": "#3b4149",
               "text": "#e6e8eb", "muted": "#9aa3ad", "faint": "#6c757f", "accent": "#4c8dff", "accent_text": "#ffffff",
               "accent_soft": "#1f3355", "hover": "#2a2f36", "pressed": "#343a42", "input": "#14161a", "select_bg": "#24406e",
               "select_fg": "#ffffff", "tooltip_bg": "#f1f3f5", "tooltip_fg": "#1b1f24", "danger": "#ff6b81", "warning": "#f5b649",
               "success": "#51cf66", "info": "#74a7ff", "focus": "#4c8dff"}},
    "graphite": {"label": "Graphite", "dark": True,
        "ui": {"bg": "#2b2d30", "surface": "#323538", "surface2": "#383b3f", "border": "#45494e", "border_strong": "#55595f",
               "text": "#e3e3e3", "muted": "#a7abb0", "faint": "#7d8186", "accent": "#e8a33d", "accent_text": "#1c1c1c",
               "accent_soft": "#4a3f2c", "hover": "#3d4044", "pressed": "#474a4f", "input": "#26282b", "select_bg": "#5a4a2e",
               "select_fg": "#ffffff", "tooltip_bg": "#f1f1f1", "tooltip_fg": "#1c1c1c", "danger": "#ff7b72", "warning": "#e8a33d",
               "success": "#7ee787", "info": "#79c0ff", "focus": "#e8a33d"}},
    "neutral_gray": {"label": "Neutral Gray", "dark": False,
        "ui": {"bg": "#d9dbde", "surface": "#e8e9eb", "surface2": "#e1e3e5", "border": "#c2c5ca", "border_strong": "#a9adb3",
               "text": "#1d2023", "muted": "#555b62", "faint": "#7b8188", "accent": "#3b6ea8", "accent_text": "#ffffff",
               "accent_soft": "#cfdcec", "hover": "#d4d7da", "pressed": "#c9ccd0", "input": "#f4f5f6", "select_bg": "#c3d5ea",
               "select_fg": "#10233a", "tooltip_bg": "#25282c", "tooltip_fg": "#f2f2f2", "danger": "#c0392b", "warning": "#a46a00",
               "success": "#25803d", "info": "#3b6ea8", "focus": "#3b6ea8"}},
    "blueprint": {"label": "Blueprint", "dark": True,
        "ui": {"bg": "#0b2140", "surface": "#0f2a52", "surface2": "#13325f", "border": "#1f4478", "border_strong": "#2a5591",
               "text": "#e6f0ff", "muted": "#9fb9dc", "faint": "#6f8fbb", "accent": "#5ab0ff", "accent_text": "#06203f",
               "accent_soft": "#173f72", "hover": "#16386a", "pressed": "#1d4580", "input": "#0a1d38", "select_bg": "#1f4e8f",
               "select_fg": "#ffffff", "tooltip_bg": "#e6f0ff", "tooltip_fg": "#06203f", "danger": "#ff8a8a", "warning": "#ffd166",
               "success": "#7ee2a8", "info": "#5ab0ff", "focus": "#5ab0ff"}},
    "high_contrast": {"label": "High Contrast", "dark": True,
        "ui": {"bg": "#000000", "surface": "#000000", "surface2": "#0d0d0d", "border": "#ffffff", "border_strong": "#ffffff",
               "text": "#ffffff", "muted": "#ffffff", "faint": "#d0d0d0", "accent": "#ffff00", "accent_text": "#000000",
               "accent_soft": "#333300", "hover": "#1f1f1f", "pressed": "#333333", "input": "#000000", "select_bg": "#ffff00",
               "select_fg": "#000000", "tooltip_bg": "#ffff00", "tooltip_fg": "#000000", "danger": "#ff4040", "warning": "#ffff00",
               "success": "#00ff00", "info": "#00ffff", "focus": "#ffff00"}},
}
DEFAULT_THEME = "modern_light"
UI_FONTS = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Cantarell", "Ubuntu", "Noto Sans", "Open Sans", "DejaVu Sans",
            "Liberation Sans", "Helvetica", "Arial")
MONO_FONTS = ("Cascadia Mono", "Consolas", "JetBrains Mono", "Ubuntu Mono", "Noto Sans Mono", "DejaVu Sans Mono", "Liberation Mono")


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two #rrggbb colours."""
    def lum(c):
        v = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b_ = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _readable(fg: str, bg: str, towards: str) -> str:
    """fg moved towards black or white only as far as it takes to read (4.5:1) on bg."""
    for step in range(11):
        c = _mix(fg, towards, step / 10)
        if contrast(c, bg) >= 4.5:
            return c
    return towards


@dataclass
class Theme:
    name: str
    label: str
    dark: bool
    ui: dict
    family: str = ""
    mono: str = ""

    def chip(self, kind: str) -> tuple[str, str]:
        """(background, text) of a status chip: readable on every theme, and never colour alone, since it has words."""
        u = self.ui
        key = {"ok": "success", "warning": "warning", "danger": "danger", "info": "info"}.get(kind)
        if key is None:
            return _mix(u["surface"], u["muted"], 0.14), u["text"]
        base = u[key]
        if self.name == "high_contrast":
            return base, "#000000"
        if self.dark:
            bg = _mix(u["surface"], base, 0.22)
            return bg, _readable(base, bg, "#ffffff")
        bg = _mix(u["surface"], base, 0.13)
        return bg, _readable(_mix(base, "#000000", 0.28), bg, "#000000")

    def chip_body(self, kind: str) -> str:
        """Colour of ordinary text on a status block: high contrast's blocks are bright, so the theme's white would vanish."""
        return "#000000" if self.name == "high_contrast" and kind != "neutral" else self.ui["text"]


def resolve(name: str) -> Theme:
    t = THEMES.get(name) or THEMES[DEFAULT_THEME]
    key = name if name in THEMES else DEFAULT_THEME
    th = Theme(key, t["label"], t["dark"], dict(t["ui"]))
    fams = {f.lower(): f for f in QFontDatabase.families()}
    th.family = next((fams[f.lower()] for f in UI_FONTS if f.lower() in fams), QGuiApplication.font().family())
    th.mono = next((fams[f.lower()] for f in MONO_FONTS if f.lower() in fams), th.family)
    return th


def stylesheet(t: Theme) -> str:
    u = t.ui
    return f"""
* {{ font-family: "{t.family}"; font-size: 10pt; }}
QWidget {{ color: {u['text']}; }}
QMainWindow, QDialog {{ background: {u['surface']}; }}
QToolTip {{ background: {u['tooltip_bg']}; color: {u['tooltip_fg']}; border: none; padding: 4px 6px; }}
QMenuBar {{ background: {u['surface']}; border-bottom: 1px solid {u['border']}; }}
QMenuBar::item {{ padding: 4px 9px; background: transparent; }}
QMenuBar::item:selected {{ background: {u['hover']}; }}
QMenu {{ background: {u['surface']}; border: 1px solid {u['border_strong']}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {u['select_bg']}; color: {u['select_fg']}; }}
QMenu::item:disabled {{ color: {u['faint']}; }}
QMenu::separator {{ height: 1px; background: {u['border']}; margin: 4px 6px; }}
QStatusBar {{ background: {u['surface2']}; border-top: 1px solid {u['border']}; color: {u['muted']}; }}
QStatusBar {{ padding-left: 8px; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {u['muted']}; font-size: 9pt; }}
#sidebar {{ background: {u['bg']}; border-right: 1px solid {u['border']}; }}
#sidebar QLabel#navGroup {{ color: {u['faint']}; font-size: 8pt; font-weight: 700; letter-spacing: 0.5px; padding: 12px 10px 3px 10px; }}
#companyName {{ font-weight: 700; font-size: 10.5pt; }}
#companyFile {{ color: {u['muted']}; font-size: 8.5pt; }}
QPushButton#navButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px 10px; text-align: left; font-weight: 500; color: {u['text']}; }}
QPushButton#navButton:hover {{ background: {u['hover']}; }}
QPushButton#navButton:checked {{ background: {u['accent_soft']}; color: {u['accent'] if t.dark else _mix(u['accent'], '#000000', 0.2)}; font-weight: 600; }}
QPushButton#navButton:focus {{ outline: none; border: 1px solid {u['focus']}; }}
#page {{ background: {u['surface']}; }}
#pageTitle {{ font-size: 15pt; font-weight: 700; }}
#pageSub, #muted {{ color: {u['muted']}; }}
#small {{ color: {u['muted']}; font-size: 9pt; }}
#sectionTitle {{ color: {u['muted']}; font-size: 8.5pt; font-weight: 700; letter-spacing: 0.4px; padding-top: 6px; }}
#detailTitle {{ font-size: 13pt; font-weight: 700; }}
#detailPanel {{ background: {u['surface']}; }}
QScrollArea#detailScroll {{ border: none; border-left: 1px solid {u['border']}; background: {u['surface']}; }}
QScrollArea {{ border: none; background: transparent; }}
QPushButton {{ background: {u['surface2']}; border: 1px solid {u['border_strong']}; border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ background: {u['hover']}; }}
QPushButton:pressed {{ background: {u['pressed']}; }}
QPushButton:focus {{ border-color: {u['focus']}; }}
QPushButton:disabled {{ color: {u['faint']}; background: {u['surface2']}; border-color: {u['border']}; }}
QPushButton#primary {{ background: {u['accent']}; color: {u['accent_text']}; border: 1px solid {u['accent']}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {_mix(u['accent'], u['surface'] if t.dark else '#000000', 0.12)}; }}
QPushButton#primary:disabled {{ background: {u['surface2']}; color: {u['faint']}; border-color: {u['border']}; }}
QPushButton#link {{ background: transparent; border: none; color: {u['accent']}; padding: 2px 0; text-align: left; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#filter {{ background: transparent; border: none; border-radius: 6px; padding: 4px 10px; color: {u['muted']}; }}
QPushButton#filter:hover {{ background: {u['hover']}; }}
QPushButton#filter:checked {{ background: {u['accent_soft']}; color: {u['accent'] if t.dark else _mix(u['accent'], '#000000', 0.2)}; font-weight: 600; }}
QPushButton::menu-indicator {{ width: 0; }}
QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox {{ background: {u['input']}; border: 1px solid {u['border_strong']}; border-radius: 6px; padding: 4px 7px; selection-background-color: {u['select_bg']}; selection-color: {u['select_fg']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {u['focus']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {u['surface']}; border: 1px solid {u['border_strong']}; selection-background-color: {u['select_bg']}; selection-color: {u['select_fg']}; outline: 0; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {u['border_strong']}; border-radius: 3px; background: {u['input']}; }}
QCheckBox::indicator:checked {{ background: {u['accent']}; border-color: {u['accent']}; }}
QTableView, QTableWidget, QListWidget, QTreeView {{ background: {u['surface']}; border: none; gridline-color: {u['border']}; outline: 0; selection-background-color: {u['select_bg']}; selection-color: {u['select_fg']}; }}
QTableView::item {{ padding: 0 8px; border-bottom: 1px solid {u['border']}; }}
QTableView::item:selected {{ background: {u['select_bg']}; color: {u['select_fg']}; }}
QTreeView {{ color: {u['text']}; }}
QTreeView::item {{ padding: 2px 4px; }}
QTreeView::item:selected {{ background: {u['select_bg']}; color: {u['select_fg']}; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}
QListWidget::item:hover {{ background: {u['hover']}; }}
QListWidget::item:selected {{ background: {u['select_bg']}; color: {u['select_fg']}; }}
QHeaderView {{ background: {u['surface']}; }}
QHeaderView::section {{ background: {u['surface']}; color: {u['muted']}; border: none; border-bottom: 1px solid {u['border_strong']}; padding: 5px 8px; font-size: 9pt; font-weight: 600; }}
QHeaderView::section:hover {{ background: {u['hover']}; }}
QSplitter::handle {{ background: {u['border']}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {u['border']}; }}
QTabBar::tab {{ background: transparent; color: {u['muted']}; padding: 6px 12px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {u['text']}; border-bottom: 2px solid {u['accent']}; font-weight: 600; }}
QTabBar::tab:hover {{ background: {u['hover']}; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle {{ background: {u['border_strong']}; border-radius: 4px; min-height: 24px; min-width: 24px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {u['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
#statCard {{ background: {u['surface']}; border: 1px solid {u['border']}; border-radius: 8px; }}
#statValue {{ font-size: 17pt; font-weight: 700; }}
#statLabel {{ color: {u['muted']}; font-size: 9pt; }}
#card {{ background: {u['surface']}; border: 1px solid {u['border']}; border-radius: 8px; }}
QMessageBox {{ messagebox-text-interaction-flags: 3; }}
"""
