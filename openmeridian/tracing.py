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


# ---- several lots at once, for a recall a supplier announces (Company.trace_lots)
def recall_summary(r) -> str:
    """What the lots reached together, said as :func:`summary` says it of one."""
    traced = {(t["item"], t["lot"]) for t in r["traces"]}
    own = [s for s in r["in_stock"] if (s["item"], s["lot"]) in traced]
    made = [s for s in r["in_stock"] if s not in own]
    n = len(r["traces"])
    parts = [f"{n} lot{'s' if n != 1 else ''} traced"]
    if r["units"]:
        k = len(r["units"])
        parts.append(f"{k} unit{'s were' if k != 1 else ' was'} made from them ({_names(u['serial'] for u in r['units'])})")
    if r["shipments"]:
        k = len(r["shipments"])
        who = _names(dict.fromkeys(s["customer"] or "a customer no longer on file" for s in r["shipments"]))
        parts.append(f"{k} shipment{'s' if k != 1 else ''} carried them or what was made from them, to {who}")
    if made:
        parts.append(_names(f"{fmt_qty(s['qty'])} of {s['item']} lot {s['lot']}" for s in made) + " made from them "
                     + ("is" if len(made) == 1 else "are") + " in stock")
    if own:
        parts.append(_names(f"{fmt_qty(s['qty'])} of {s['item']} lot {s['lot']}" for s in own) + " "
                     + ("is" if len(own) == 1 else "are") + " still in stock")
    if len(parts) == 1:
        parts.append("none of them is in stock, and they went into nothing that is tracked")
    text = "; ".join(parts) + "."
    if r["untracked"]:
        text += (" Some went into " + _names(dict.fromkeys(u["item"] for u in r["untracked"]))
                 + ", which isn't tracked by lot or serial, so where that went can't be followed.")
    if r["cut_short"]:
        text += " A trace stopped after many levels of assemblies; trace the last lots shown to go further."
    return text


def recall_rows(r) -> list[list[str]]:
    """Each lot's trace as :func:`rows` gives it, its section naming the lot."""
    out = []
    for t in r["traces"]:
        for row in rows(t):
            out.append([f"{t['item']} lot {t['lot']}: {row[0]}", *row[1:]])
    return out


# ---- what RevisionWorx's unit register says of what a lot reached (read-only; docs/COMPANY_FILE.md, Tracing a lot)
def in_revisionworx(t, client) -> dict:
    """What RevisionWorx's unit register says of what lot trace ``t`` reached, asked through ``client`` (a
    revisionworx.Client), writing nothing there:

    - ``units``: each unit the lot went into, with ``found``, the register's summary of it (status, customer, site,
      location), or None when the register doesn't have it. It is matched by the id RevisionWorx gave it when it was
      registered, or by its serial.
    - ``fitted``: units the register records one of the lots reached fitted in (the lot traced, or a lot made from it),
      now or before, that the trace didn't reach: a spare fitted in the field, say, which the stock ledger can't know.
      Each has ``item``, ``lot`` and the register's row (``unit``, ``position``, ``current``, ``fitted_on``,
      ``removed_on``, and ``built_from`` for a unit registered as built from the lot). The units this company file
      registered with their lots are among ``units`` already, so they aren't listed again.
    - ``note``: why ``fitted`` couldn't be asked, if it couldn't."""
    summaries = client.units()
    by_id = {u["id"]: u for u in summaries}
    by_serial = {}
    for u in summaries:
        for ident in u.get("identifiers") or []:
            if isinstance(ident, dict) and ident.get("scheme") == "serial" and not ident.get("issuer"):
                by_serial.setdefault(str(ident.get("value", "")).casefold(), u)
    out = {"units": [], "fitted": [], "note": ""}
    reached = set()
    for unit in t["units"]:
        found = by_id.get(unit["rw_unit"]) if unit["rw_unit"] else None
        found = found or by_serial.get(unit["serial"].casefold())
        out["units"].append({**unit, "found": found})
        if found:
            reached.add(found["id"])
    if not client.has("unit-where-used"):
        out["note"] = ("This RevisionWorx can't say which other units have these lots fitted. Update it (1.0.0 or "
                       "later) to see them.")
        return out
    seen = set()
    for lot in t["lots"]:
        for row in client.where_used(lot["item"], lot["lot"], history=True):
            key = (row["unit"].get("id"), row.get("position"), row.get("fitted"))
            if row["unit"].get("id") in reached or key in seen:
                continue
            seen.add(key)
            out["fitted"].append({"item": lot["item"], "lot": lot["lot"], **row})
    return out


def _where(u) -> str:
    """Where a unit is, as the register says: its customer, site and location, as far as they're known."""
    return ", ".join(x for x in (u.get("customer", ""), u.get("site", ""), u.get("location", "")) if x) or "not recorded"


def rw_summary(r, it="it") -> str:
    """The register's answer in a sentence or two. ``it`` is what was traced: "it" for a lot, "them" for several."""
    n = len(r["units"])
    found = [u for u in r["units"] if u["found"]]
    parts = []
    lot = "a lot" if it == "it" else "lots"
    if n:
        parts.append(f"RevisionWorx has {len(found)} of the {n} unit{'s' if n != 1 else ''} made from {it}"
                     + ("" if len(found) == n else
                        f"; not {_names(u['serial'] for u in r['units'] if not u['found'])}") + ".")
    who = "It also" if parts else "RevisionWorx"
    if r["fitted"]:
        units = _names(dict.fromkeys(f["unit"].get("label", "?") for f in r["fitted"]))
        parts.append(f"{who} records {it}, or {lot} made from {it}, fitted in {units}, which the stock ledger can't know.")
    elif not r["note"]:
        parts.append(f"{who} records {it} fitted in no other unit." if parts else
                     f"RevisionWorx records {it} fitted in no unit.")
    if r["note"]:
        parts.append(r["note"])
    return " ".join(parts) or "RevisionWorx has nothing more on it."


def rw_rows(r) -> list[list[str]]:
    """The register's answer as rows under HEADERS, in a section of its own."""
    section = "In RevisionWorx"
    out = []
    for u in r["units"]:
        f = u["found"]
        out.append([section, "0", "Unit", u["item"], u["serial"], "1", f["label"] if f else "", _where(f) if f else "",
                    "", (f"{f.get('status', '')}" if f else "not in RevisionWorx's unit register")])
    for row in r["fitted"]:
        unit = row["unit"]
        when = row.get("fitted_on", "") or ""
        if row.get("built_from"):                    # registered as built from the lot, by whoever made that unit
            n = row["built_from"].get("units", 1)
            what, state = "Built from it", (f"one of {n} units built with it" if n > 1 else "built with it")
        else:
            what = f"Fitted at {row.get('position', '')}"
            state = "fitted now" if row.get("current") else (f"removed {row.get('removed_on', '')}".strip()
                                                             + (f", {row['disposition']}" if row.get("disposition") else ""))
        out.append([section, "0", what, row["item"], row["lot"], "", unit.get("label", ""), _where(unit), when,
                    f"{state}; {unit.get('status', '')}".strip("; ")])
    return out
