"""Vector icons in OpenSchematix's stroke language (24 x 24 grid; its `gui/icons.py`, GPL-3.0-or-later), painted with Qt.
Ops: ("l", x1, y1, ...) polyline, ("p", ...) polygon, ("pf", ...) filled, ("r", x1, y1, x2, y2) rectangle,
("o", cx, cy, r) circle, ("of", ...) filled circle, ("a", cx, cy, r, start, extent) arc. A "!" uses the accent colour."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

ICONS = {
    "dashboard": [("r", 4, 4, 11, 11), ("r!", 13, 4, 20, 8), ("r", 13, 10, 20, 20), ("r!", 4, 13, 11, 20)],
    "items": [("p", 12, 3, 20, 7.5, 20, 16.5, 12, 21, 4, 16.5, 4, 7.5), ("l", 4, 7.5, 12, 12, 20, 7.5), ("l!", 12, 12, 12, 21)],
    "customers": [("o", 9, 8, 3.5), ("a", 9, 20, 7, 0, 180), ("o!", 17, 9, 2.5), ("a!", 17, 19, 5, 0, 110)],
    "suppliers": [("r", 3, 7, 14, 17), ("p!", 14, 10, 18.5, 10, 21, 13, 21, 17, 14, 17), ("o", 7.5, 18, 2), ("o", 17, 18, 2)],
    "sales": [("p", 6, 3, 18, 3, 18, 21, 6, 21), ("l", 9, 8, 15, 8), ("l", 9, 12, 15, 12), ("l!", 9, 16, 13, 16)],
    "invoices": [("p", 6, 3, 18, 3, 18, 21, 15, 19, 12, 21, 9, 19, 6, 21), ("l", 9, 8, 15, 8), ("l!", 9, 12, 15, 12)],
    "purchasing": [("l", 3, 4, 6, 4, 8.5, 15, 18, 15, 20, 7, 7, 7), ("of!", 10, 19, 1.6), ("of!", 17, 19, 1.6)],
    "production": [("p", 3, 20, 3, 10, 9, 14, 9, 10, 15, 14, 15, 5, 21, 5, 21, 20), ("r!", 7, 16, 10, 20), ("r!", 14, 16, 17, 20)],
    "planning": [("r", 4, 5, 20, 20), ("l", 4, 9.5, 20, 9.5), ("l", 8, 3, 8, 7), ("l", 16, 3, 16, 7), ("l!", 8, 15, 11, 17.5, 16, 12.5)],
    "stock": [("r", 3, 13, 11, 21), ("r", 13, 13, 21, 21), ("r!", 8, 3, 16, 11)],
    "engineering": [("a", 12, 12, 8, 160, -300), ("l", 4.5, 5.5, 4.4, 9.5, 8.4, 9.2), ("l!", 12, 8, 12, 12, 15, 14)],
    "settings": [("o", 12, 12, 3)] + [("l", 12 + 5.5 * math.cos(a), 12 + 5.5 * math.sin(a), 12 + 8.5 * math.cos(a), 12 + 8.5 * math.sin(a))
                                       for a in [i * math.pi / 4 for i in range(8)]] + [("o", 12, 12, 5.5)],
    "search": [("o", 10, 10, 6.5), ("l", 14.8, 14.8, 20.5, 20.5)],
    "plus": [("l", 12, 5, 12, 19), ("l", 5, 12, 19, 12)],
    "more": [("of", 6, 12, 1.5), ("of", 12, 12, 1.5), ("of", 18, 12, 1.5)],
    "check": [("o", 12, 12, 8.5), ("l!", 8, 12.3, 11, 15.3, 16.5, 9)],
    "warning": [("p!", 12, 3.5, 21, 20, 3, 20), ("l", 12, 9, 12, 14.5), ("of", 12, 17.2, 1)],
    "error": [("o!", 12, 12, 8.5), ("l", 8.5, 8.5, 15.5, 15.5), ("l", 15.5, 8.5, 8.5, 15.5)],
    "info": [("o!", 12, 12, 8.5), ("l", 12, 11, 12, 17), ("of", 12, 7.6, 1.1)],
    "export": [("l", 4, 14, 4, 20, 20, 20, 20, 14), ("l!", 12, 4, 12, 15), ("l!", 8, 8, 12, 4, 16, 8)],
    "theme": [("o", 12, 12, 8.5), ("pf", 12, 3.5, 12, 20.5, 7, 19, 4, 15, 3.5, 12, 4, 9, 7, 5)],
    "refresh": [("a", 12, 12, 7, 30, 300), ("l!", 18.5, 4.5, 18.5, 9.5, 13.5, 9.5)],
    "help": [("o", 12, 12, 8.5), ("a", 12, 9.5, 3, -50, 230), ("l", 12, 12.5, 12, 14.5), ("of", 12, 17.3, 1)],
}


def paint(p: QPainter, name: str, x: float, y: float, size: float, color: str, accent: str, width: float = 1.6) -> None:
    k = size / 24.0
    pen_w = max(1.0, width * k)
    for op in ICONS.get(name, [("r", 4, 4, 20, 20)]):
        kind = op[0].rstrip("!")
        col = QColor(accent if op[0].endswith("!") else color)
        args = op[1:]
        p.setPen(QPen(col, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        pts = [QPointF(x + args[i] * k, y + args[i + 1] * k) for i in range(0, len(args) - 1, 2)] if kind in ("l", "p", "pf") else []
        if kind == "l":
            p.drawPolyline(QPolygonF(pts))
        elif kind in ("p", "pf"):
            if kind == "pf":
                p.setBrush(col)
            p.drawPolygon(QPolygonF(pts))
        elif kind == "r":
            p.drawRoundedRect(QRectF(x + args[0] * k, y + args[1] * k, (args[2] - args[0]) * k, (args[3] - args[1]) * k), 1.2 * k, 1.2 * k)
        elif kind in ("o", "of"):
            if kind == "of":
                p.setBrush(col)
                p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x + args[0] * k, y + args[1] * k), args[2] * k, args[2] * k)
        elif kind == "a":
            cx, cy, r, st, ex = args
            path = QPainterPath()
            rect = QRectF(x + (cx - r) * k, y + (cy - r) * k, 2 * r * k, 2 * r * k)
            path.arcMoveTo(rect, st)
            path.arcTo(rect, st, ex)
            p.drawPath(path)


def icon(name: str, color: str, accent: str, size: int = 18) -> QIcon:
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(scale)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint(p, name, 0, 0, size, color, accent)
        p.end()
        ic.addPixmap(pm)
    return ic
