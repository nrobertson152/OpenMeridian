"""A lot's trace (Company.trace_lot) said in a sentence and laid out as rows, for the window and for CSV. No GUI here."""
from __future__ import annotations

from .values import fmt_qty

HEADERS = ["Section", "Level", "What", "Item", "Lot or serial", "Qty", "Reference", "Customer or supplier", "Date", "Note"]
SECTIONS = (("came", "Where it came from"), ("went", "Where it went"))


def _names(names, limit=6) -> str:
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"


def summary(t) -> str:
    """What the lot reached, for someone deciding on a recall: units, shipments, stock, and where the trail stops."""
    own = [s for s in t["in_stock"] if (s["item"], s["lot"]) == (t["item"], t["lot"])]
    made = [s for s in t["in_stock"] if s not in own]
    parts = []
    if t["units"]:
        n = len(t["units"])
        parts.append(f"{n} unit{'s were' if n != 1 else ' was'} made from it ({_names(u['serial'] for u in t['units'])})")
    if t["shipments"]:
        n = len(t["shipments"])
        who = _names(dict.fromkeys(s["customer"] or "a customer no longer on file" for s in t["shipments"]))
        parts.append(f"{n} shipment{'s' if n != 1 else ''} carried it or what was made from it, to {who}")
    if made:
        parts.append(_names(f"{fmt_qty(s['qty'])} of {s['item']} lot {s['lot']}" for s in made) + " made from it "
                     + ("is" if len(made) == 1 else "are") + " in stock")
    if own:
        parts.append(f"{fmt_qty(own[0]['qty'])} of it is still in stock")
    text = ("; ".join(parts) if parts else "None of it is in stock, and it went into nothing that is tracked") + "."
    text = text[0].upper() + text[1:]
    if t["untracked"]:
        text += (" Some went into " + _names(dict.fromkeys(u["item"] for u in t["untracked"]))
                 + ", which isn't tracked by lot or serial, so where that went can't be followed.")
    if t["cut_short"]:
        text += " The trace stopped after many levels of assemblies; trace the last lots shown to go further."
    return text


def rows(t) -> list[list[str]]:
    """The trace as rows under HEADERS: a step's level is how many steps it is from the lot traced."""
    out = []

    def walk(section, steps, level):
        for s in steps:
            out.append([section, str(level), s["what"], s["item"], s["code"], fmt_qty(s["qty"]) if s["qty"] else "",
                        s["ref"], s["who"], s["date"], s["note"]])
            walk(section, s["children"], level + 1)
    for key, title in SECTIONS:
        walk(title, t[key], 0)
    return out
