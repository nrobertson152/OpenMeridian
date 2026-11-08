"""Everything a company does. Every public method is one transaction: it all happens, or none of it does.
No GUI here: this module is what the window, the command line and the tests all use."""
from __future__ import annotations

import getpass
import hashlib
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import db
from .revisionworx import RevisionWorxError
from .values import QTY_SCALE, fmt_money, fmt_qty, line_total


class ERPError(ValueError):
    """Something the user can act on. The message is written for them."""


def today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _user() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        return ""


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _serial_key(serial) -> str:
    return unicodedata.normalize("NFC", str(serial)).casefold()


def _short(text, limit) -> str:
    text = _clean(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _date(text, what="date") -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise ERPError(f"Enter the {what} as YYYY-MM-DD.") from None


KINDS = ("buy", "make")
TRACKING = ("none", "serial", "lot")
REGISTER_DOMAIN = "openmeridian/register/v1"
SERIAL_LIMIT, NAME_LIMIT = 100, 200    # RevisionWorx's limits for a unit's serial and name (its docs/UNITS.md)
LOT_LIMIT = 100
TRACE_DEPTH = 24                       # deeper than any bill of materials here; a trace stops there and says so
UNFOLLOWED = {"none": "not tracked by lot or serial, so it can't be followed further",
              "serial": "which units isn't recorded when they're used, so they can't be followed further"}
MISSING_NOTE = ("RevisionWorx recorded this completion but didn't list this unit yet: it finishes recording it when its "
                "workspace is next opened for writing. Register again to pick it up.")
DEFAULT_SETTINGS = {"company_name": "", "currency": "$", "tax_percent": "0", "address": "", "rw_workspace": ""}
PREFIX = {"so": "SO", "po": "PO", "wo": "WO", "inv": "INV"}


class Company:
    def __init__(self, conn: sqlite3.Connection, path: str):
        self.conn, self.path = conn, path
        self._depth = 0
        self.user = _user()

    # ---- opening
    @classmethod
    def create(cls, path: str, name: str) -> "Company":
        name = _clean(name)
        if not name:
            raise ERPError("Enter a company name.")
        c = cls(db.create(path), path)
        with c.tx():
            for k, v in DEFAULT_SETTINGS.items():
                c.conn.execute("INSERT INTO settings VALUES (?, ?)", (k, name if k == "company_name" else v))
            c.conn.execute("INSERT INTO settings VALUES ('company_id', ?)", (secrets.token_hex(16),))
            c._log("company.create", name)
        return c

    @classmethod
    def open(cls, path: str) -> "Company":
        return cls(db.open_existing(path), path)

    def close(self) -> None:
        self.conn.close()

    def backup(self, dest: str) -> None:
        db.backup(self.conn, dest)

    @contextmanager
    def tx(self):
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            raise ERPError(f"The company file is busy in another window. Try again in a moment.\n\n{e}") from e
        self._depth = 1
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")
        finally:
            self._depth = 0

    def _log(self, action: str, detail: str = "") -> None:
        self.conn.execute("INSERT INTO audit (time, user, action, detail) VALUES (?, ?, ?, ?)",
                          (_now(), self.user, action, detail))

    def _next(self, seq: str) -> str:
        row = self.conn.execute("SELECT last FROM sequences WHERE name = ?", (seq,)).fetchone()
        n = (row[0] if row else 0) + 1
        self.conn.execute("INSERT INTO sequences VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET last = excluded.last", (seq, n))
        return f"{PREFIX[seq]}-{n:05d}"

    def _rows(self, sql, *args):
        return [dict(r) for r in self.conn.execute(sql, args)]

    def _row(self, sql, *args):
        r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    # ---- settings
    def setting(self, key: str) -> str:
        r = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return r[0] if r else DEFAULT_SETTINGS.get(key, "")

    def set_setting(self, key: str, value: str) -> None:
        if key not in DEFAULT_SETTINGS:
            raise ERPError(f"Unknown setting {key}.")
        value = str(value).strip()
        if key == "company_name" and not value:
            raise ERPError("Enter a company name.")
        if key == "tax_percent":
            try:
                d = Decimal(value or "0")
            except InvalidOperation:
                raise ERPError("Enter the tax rate as a percentage.") from None
            if not d.is_finite() or d < 0 or d > 100:
                raise ERPError("Enter a tax rate between 0 and 100.")
            value = str(d)
        with self.tx():
            self.conn.execute("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
            self._log("settings", f"{key} = {value}")

    def money(self, cents: int) -> str:
        return fmt_money(cents, self.setting("currency") or "$")

    # ---- contacts
    def add_contact(self, kind, name, contact="", email="", phone="", address="", terms_days=30, notes="") -> int:
        name = _clean(name)
        if not name:
            raise ERPError("Enter a name.")
        if kind not in ("customer", "supplier"):
            raise ERPError("A contact is a customer or a supplier.")
        with self.tx():
            cur = self.conn.execute("INSERT INTO contacts (kind, name, contact, email, phone, address, terms_days, notes) "
                                    "VALUES (?,?,?,?,?,?,?,?)", (kind, name, _clean(contact), _clean(email), _clean(phone),
                                                                 str(address or "").strip(), int(terms_days), str(notes or "").strip()))
            self._log("contact.add", name)
            return cur.lastrowid

    def update_contact(self, cid, **f) -> None:
        allowed = {"name", "contact", "email", "phone", "address", "terms_days", "notes", "active"}
        if set(f) - allowed:
            raise ERPError("Unknown contact field.")
        if "name" in f and not _clean(f["name"]):
            raise ERPError("Enter a name.")
        with self.tx():
            for k, v in f.items():
                self.conn.execute(f"UPDATE contacts SET {k} = ? WHERE id = ?", (v, cid))  # noqa: S608 - k is from `allowed`
            self._log("contact.update", str(cid))

    def contacts(self, kind, search="", include_inactive=False):
        q = f"%{search.strip()}%"
        return self._rows("SELECT * FROM contacts WHERE kind = ? AND (name LIKE ? OR contact LIKE ? OR email LIKE ?) "
                          "AND (active = 1 OR ?) ORDER BY name COLLATE NOCASE", kind, q, q, q, 1 if include_inactive else 0)

    def contact(self, cid):
        return self._row("SELECT * FROM contacts WHERE id = ?", cid)

    # ---- items
    def add_item(self, number, description="", kind="buy", unit="EA", cost=0, price=0, reorder_point=0, reorder_qty=0,
                 supplier_id=None, lead_days=0, bin="", notes="", rw_document="", rw_number="", tracking="none") -> int:  # noqa: A002
        number = _clean(number)
        if not number:
            raise ERPError("Enter an item number.")
        if kind not in KINDS:
            raise ERPError("An item is bought or made.")
        self._check_tracking(kind, tracking)
        if min(cost, price, reorder_point, reorder_qty, lead_days) < 0:
            raise ERPError("Costs, prices and reorder values can't be negative.")
        try:
            with self.tx():
                cur = self.conn.execute(
                    "INSERT INTO items (number, description, kind, unit, cost, price, reorder_point, reorder_qty, supplier_id, "
                    "lead_days, bin, notes, rw_document, rw_number, tracking) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (number, _clean(description), kind, _clean(unit) or "EA", cost, price, reorder_point, reorder_qty, supplier_id,
                     lead_days, _clean(bin), str(notes or "").strip(), rw_document, rw_number, tracking))
                self._log("item.add", number)
                return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ERPError(f"There is already an item {number}.") from None

    ITEM_FIELDS = {"number", "description", "kind", "unit", "cost", "price", "reorder_point", "reorder_qty", "supplier_id",
                   "lead_days", "bin", "notes", "active", "rw_document", "rw_number", "tracking"}

    @staticmethod
    def _check_tracking(kind, tracking) -> None:
        if tracking not in TRACKING:
            raise ERPError("An item is tracked by serial number, by lot, or not at all.")
        if tracking == "serial" and kind != "make":
            raise ERPError("Serial numbers are given to items you make (a unit a work order builds).")

    def update_item(self, item_id, **f) -> None:
        if set(f) - self.ITEM_FIELDS:
            raise ERPError("Unknown item field.")
        if "number" in f and not _clean(f["number"]):
            raise ERPError("Enter an item number.")
        try:
            with self.tx():
                now = self.item(item_id)
                if now is not None and ("tracking" in f or "kind" in f):
                    tracking, kind = f.get("tracking", now["tracking"]), f.get("kind", now["kind"])
                    self._check_tracking(kind, tracking)
                    if tracking != now["tracking"] and now["on_hand"] != 0:
                        raise ERPError(f"{now['number']} has {fmt_qty(now['on_hand'])} on hand. Its stock has to be zero "
                                       "before it starts or stops being tracked by serial number or lot.")
                for k, v in f.items():
                    self.conn.execute(f"UPDATE items SET {k} = ? WHERE id = ?", (v, item_id))  # noqa: S608 - k is from ITEM_FIELDS
                self._log("item.update", str(item_id))
        except sqlite3.IntegrityError as e:
            raise ERPError(f"That item number is already used, or a value isn't allowed.\n\n{e}") from None

    _ITEM_SELECT = """
        SELECT i.*, c.name AS supplier,
          COALESCE((SELECT SUM(m.qty) FROM stock_moves m WHERE m.item_id = i.id), 0) AS on_hand,
          COALESCE((SELECT SUM(l.qty - l.received) FROM purchase_lines l JOIN purchase_orders o ON o.id = l.order_id
                    WHERE l.item_id = i.id AND o.status = 'ordered' AND l.qty > l.received), 0)
          + COALESCE((SELECT SUM(w.qty - w.done) FROM work_orders w WHERE w.item_id = i.id AND w.status = 'released'), 0) AS on_order,
          COALESCE((SELECT SUM(l.qty - l.shipped) FROM sales_lines l JOIN sales_orders o ON o.id = l.order_id
                    WHERE l.item_id = i.id AND o.status = 'confirmed' AND l.qty > l.shipped), 0)
          + COALESCE((SELECT SUM((w.qty - w.done) * b.qty / 1000) FROM work_orders w JOIN bom_lines b ON b.parent_id = w.item_id
                      WHERE b.child_id = i.id AND w.status = 'released'), 0) AS allocated
        FROM items i LEFT JOIN contacts c ON c.id = i.supplier_id"""

    def items(self, search="", include_inactive=False):
        q = f"%{search.strip()}%"
        return self._rows(self._ITEM_SELECT + " WHERE (i.number LIKE ? OR i.description LIKE ?) AND (i.active = 1 OR ?) "
                          "ORDER BY i.number COLLATE NOCASE", q, q, 1 if include_inactive else 0)

    def item(self, item_id):
        return self._row(self._ITEM_SELECT + " WHERE i.id = ?", item_id)

    def item_by_number(self, number):
        return self._row(self._ITEM_SELECT + " WHERE i.number = ? COLLATE NOCASE", _clean(number))

    def on_hand(self, item_id) -> int:
        return self.conn.execute("SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE item_id = ?", (item_id,)).fetchone()[0]

    # ---- bill of materials
    def bom(self, item_id):
        return self._rows("SELECT b.*, i.number, i.description, i.unit, i.cost, i.kind FROM bom_lines b JOIN items i ON i.id = b.child_id "
                          "WHERE b.parent_id = ? ORDER BY CAST(b.find_number AS INTEGER), b.find_number, i.number", item_id)

    def where_used(self, item_id):
        return self._rows("SELECT b.qty, i.id, i.number, i.description FROM bom_lines b JOIN items i ON i.id = b.parent_id "
                          "WHERE b.child_id = ? ORDER BY i.number", item_id)

    def _would_cycle(self, parent_id, child_id) -> bool:
        seen, stack = set(), [child_id]
        while stack:
            cur = stack.pop()
            if cur == parent_id:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack += [r[0] for r in self.conn.execute("SELECT child_id FROM bom_lines WHERE parent_id = ?", (cur,))]
        return False

    def set_bom_line(self, parent_id, child_id, qty, find_number="") -> None:
        if qty <= 0:
            raise ERPError("A BOM quantity must be more than zero.")
        if self._would_cycle(parent_id, child_id):
            raise ERPError("That would make an item a part of itself.")
        with self.tx():
            self.conn.execute("INSERT INTO bom_lines (parent_id, child_id, qty, find_number) VALUES (?,?,?,?) "
                              "ON CONFLICT(parent_id, child_id) DO UPDATE SET qty = excluded.qty, find_number = excluded.find_number",
                              (parent_id, child_id, qty, str(find_number or "")))
            self.conn.execute("UPDATE items SET kind = 'make' WHERE id = ?", (parent_id,))
            self._log("bom.set", f"{parent_id} <- {child_id} x {fmt_qty(qty)}")

    def remove_bom_line(self, line_id) -> None:
        with self.tx():
            self.conn.execute("DELETE FROM bom_lines WHERE id = ?", (line_id,))
            self._log("bom.remove", str(line_id))

    def rollup_cost(self, item_id, _seen=None) -> int:
        """Cost to build one: components' costs, using each made component's own build-up where it has a BOM."""
        _seen = _seen or set()
        total = 0
        for line in self.bom(item_id):
            if line["child_id"] in _seen:
                continue
            sub = self.bom(line["child_id"])
            unit = self.rollup_cost(line["child_id"], _seen | {item_id}) if sub else line["cost"]
            total += line_total(line["qty"], unit)
        return total

    # ---- stock
    def _move(self, item_id, qty, kind, ref="", note="", unit_cost=0, serial="", lot="", batch=0) -> None:
        self.conn.execute("INSERT INTO stock_moves (time, item_id, qty, unit_cost, kind, ref, note, user, serial, lot, batch) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (_now(), item_id, qty, unit_cost, kind, ref, note, self.user, serial, lot, batch))

    def _add_at_cost(self, item, qty, unit_cost, kind, ref, note="", serial="", lot="", batch=0) -> None:
        """Bring stock in at a cost, keeping a moving average so the stock value stays true."""
        have = self.on_hand(item["id"])
        if have > 0 and item["cost"] > 0:
            avg = (have * item["cost"] + qty * unit_cost + (have + qty) // 2) // (have + qty)
        else:
            avg = unit_cost
        self.conn.execute("UPDATE items SET cost = ? WHERE id = ?", (avg, item["id"]))
        self._move(item["id"], qty, kind, ref, note, unit_cost, serial, lot, batch)

    def adjust_stock(self, item_id, delta, note, unit_cost=None, lot="") -> None:
        """Change the stock by ``delta`` for a reason that goes in the ledger. An item tracked by lot says which lot: one
        already there, or a new one when stock goes up."""
        if not _clean(note):
            raise ERPError("Say why the stock is being adjusted; the reason goes in the ledger.")
        if delta == 0:
            raise ERPError("Enter a quantity other than zero.")
        with self.tx():
            item = self.item(item_id)
            if item["on_hand"] + delta < 0:
                raise ERPError(f"{item['number']} has {fmt_qty(item['on_hand'])} on hand, so it can't go down by {fmt_qty(-delta)}.")
            if item["tracking"] == "lot":
                if not _clean(lot):
                    raise ERPError(f"{item['number']} is tracked by lot: say which lot is being adjusted.")
                lot = self._lot(item, lot)
                have = self.lot_on_hand(item_id, lot)
                if have + delta < 0:
                    raise ERPError(f"{item['number']} lot {lot} has {fmt_qty(have)} on hand, so it can't go down by {fmt_qty(-delta)}.")
            elif _clean(lot):
                raise ERPError(f"{item['number']} isn't tracked by lot.")
            if delta > 0:
                self._add_at_cost(item, delta, item["cost"] if unit_cost is None else unit_cost, "adjust", "", _clean(note), lot=lot)
            else:
                self._move(item_id, delta, "adjust", "", _clean(note), item["cost"], lot=lot)
            self._log("stock.adjust", f"{item['number']} {fmt_qty(delta)}" + (f" lot {lot}" if lot else "") + f": {note}")

    # ---- lots
    def _lot(self, item, lot) -> str:
        """``lot`` of ``item`` as the file keeps it: composed (NFC), single-spaced, without control characters, and spelt
        as that item's lot already is if it has one ignoring ASCII case, so one lot is never two."""
        text = unicodedata.normalize("NFC", _clean(lot))
        if not text:
            raise ERPError(f"{item['number']} is tracked by lot: say which lot.")
        if len(text) > LOT_LIMIT:
            raise ERPError(f"{text[:20]}… is longer than a lot can be ({LOT_LIMIT} characters).")
        if any(unicodedata.category(ch) == "Cc" for ch in text):
            raise ERPError(f"{text!r} has a control character in it, which a lot can't have.")
        had = self.conn.execute("SELECT lot FROM stock_moves WHERE item_id = ? AND lot = ? COLLATE NOCASE ORDER BY id LIMIT 1",
                                (item["id"], text)).fetchone()
        return had[0] if had else text

    def lots(self, item_id, in_stock=False) -> list[dict]:
        """An item's lots, oldest first: each with what is on hand in it and when it first came in. ``in_stock`` leaves
        out the lots that are used up."""
        rows = self._rows("SELECT lot, SUM(qty) AS on_hand, MIN(time) AS first, MIN(id) AS first_id FROM stock_moves "
                          "WHERE item_id = ? AND lot <> '' GROUP BY lot ORDER BY first_id", item_id)
        return [r for r in rows if r["on_hand"] > 0] if in_stock else rows

    def all_lots(self) -> list[dict]:
        """Every lot of every item: item_id, number, description, lot and on_hand, by item and then oldest first."""
        return self._rows("SELECT m.item_id, i.number, i.description, m.lot, SUM(m.qty) AS on_hand FROM stock_moves m "
                          "JOIN items i ON i.id = m.item_id WHERE m.lot <> '' GROUP BY m.item_id, m.lot "
                          "ORDER BY i.number COLLATE NOCASE, MIN(m.id)")

    def lot_on_hand(self, item_id, lot) -> int:
        return self.conn.execute("SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE item_id = ? AND lot = ?",
                                 (item_id, lot)).fetchone()[0]

    def suggest_lots(self, item_id, qty) -> list[tuple[str, int]]:
        """The lots ``qty`` would come from if the oldest goes first, as far as the lots in stock cover it. A suggestion
        for someone to check: what is recorded is only ever the lots they say."""
        out, left = [], qty
        for lot in self.lots(item_id, in_stock=True):
            if left <= 0:
                break
            take = min(left, lot["on_hand"])
            out.append((lot["lot"], take))
            left -= take
        return out

    def _picks(self, item, qty, picks, verb) -> list[tuple[str, int]]:
        """The lots ``qty`` of ``item`` is taken from: ``picks`` is [(lot, qty)], adding up to ``qty``, each lot having
        that much. Nothing for an item that isn't tracked by lot. ``verb`` says what the stock is doing, for messages."""
        if item["tracking"] != "lot":
            if any(q for _lot, q in (picks or [])):
                raise ERPError(f"{item['number']} isn't tracked by lot.")
            return []
        merged: dict[str, int] = {}
        for lot, q in picks or []:
            if q == 0:
                continue
            if q < 0:
                raise ERPError(f"{item['number']}: a quantity from a lot can't be negative.")
            key = self._lot(item, lot)
            merged[key] = merged.get(key, 0) + q
        total = sum(merged.values())
        if total != qty:
            raise ERPError(f"{item['number']} is tracked by lot: say which lots the {fmt_qty(qty)} {verb} came from "
                           f"({fmt_qty(total)} given).")
        for lot, q in merged.items():
            have = self.lot_on_hand(item["id"], lot)
            if q > have:
                raise ERPError(f"{item['number']} lot {lot} has {fmt_qty(have)} on hand, not {fmt_qty(q)}." if have
                               else f"{item['number']} has no lot {lot} in stock.")
        return list(merged.items())

    def _take(self, item, qty, picks, kind, ref, unit_cost, verb, batch=0) -> list[tuple[str, int]]:
        """Take ``qty`` of ``item`` out of stock: one move, or one per lot for an item tracked by lot."""
        chosen = self._picks(item, qty, picks, verb)
        for lot, q in chosen or [("", qty)]:
            self._move(item["id"], -q, kind, ref, unit_cost=unit_cost, lot=lot, batch=batch)
        return chosen

    def moves(self, item_id=None, limit=500):
        where, args = ("WHERE m.item_id = ?", [item_id]) if item_id else ("", [])
        return self._rows(f"SELECT m.*, i.number, i.description FROM stock_moves m JOIN items i ON i.id = m.item_id {where} "  # noqa: S608
                          "ORDER BY m.id DESC LIMIT ?", *args, limit)

    def stock_value(self) -> int:
        total = 0
        for r in self.conn.execute("SELECT i.cost, COALESCE(SUM(m.qty), 0) FROM items i LEFT JOIN stock_moves m ON m.item_id = i.id GROUP BY i.id"):
            total += line_total(r[1], r[0])
        return total

    # ---- sales orders
    def create_sales_order(self, customer_id, due_date="", reference="", notes="") -> int:
        if not self.contact(customer_id):
            raise ERPError("Choose a customer.")
        with self.tx():
            number = self._next("so")
            cur = self.conn.execute("INSERT INTO sales_orders (number, customer_id, status, order_date, due_date, reference, notes) "
                                    "VALUES (?,?,'draft',?,?,?,?)", (number, customer_id, today(), _date(due_date, "due date"), _clean(reference), str(notes or "")))
            self._log("so.create", number)
            return cur.lastrowid

    def sales_orders(self, status=None, search=""):
        q = f"%{search.strip()}%"
        cond = "AND o.status = ?" if status else ""
        args = [q, q, q] + ([status] if status else [])
        return self._rows(f"""SELECT o.*, c.name AS customer, COALESCE(SUM(l.qty * l.unit_price / {QTY_SCALE}), 0) AS total,
            COUNT(l.id) AS line_count, COALESCE(SUM(l.qty - l.shipped), 0) AS to_ship,
            COALESCE(SUM(l.shipped - l.invoiced), 0) AS to_invoice
            FROM sales_orders o JOIN contacts c ON c.id = o.customer_id LEFT JOIN sales_lines l ON l.order_id = o.id
            WHERE (o.number LIKE ? OR c.name LIKE ? OR o.reference LIKE ?) {cond} GROUP BY o.id ORDER BY o.id DESC""", *args)  # noqa: S608

    def sales_order(self, oid):
        return self._row("""SELECT o.*, c.name AS customer, c.terms_days FROM sales_orders o JOIN contacts c ON c.id = o.customer_id WHERE o.id = ?""", oid)

    def sales_lines(self, oid):
        return self._rows("SELECT l.*, i.number, i.description, i.unit FROM sales_lines l JOIN items i ON i.id = l.item_id WHERE l.order_id = ? ORDER BY l.id", oid)

    def _so(self, oid, *allowed):
        o = self.sales_order(oid)
        if o is None:
            raise ERPError("That order no longer exists.")
        if allowed and o["status"] not in allowed:
            raise ERPError(f"{o['number']} is {o['status']}, so that can't be done.")
        return o

    def add_sales_line(self, oid, item_id, qty, unit_price=None) -> int:
        if qty <= 0:
            raise ERPError("Enter a quantity above zero.")
        with self.tx():
            self._so(oid, "draft")
            item = self.item(item_id)
            if item is None:
                raise ERPError("Choose an item.")
            price = item["price"] if unit_price is None else unit_price
            if price < 0:
                raise ERPError("A price can't be negative.")
            cur = self.conn.execute("INSERT INTO sales_lines (order_id, item_id, qty, unit_price) VALUES (?,?,?,?)", (oid, item_id, qty, price))
            return cur.lastrowid

    def remove_sales_line(self, line_id) -> None:
        with self.tx():
            r = self._row("SELECT order_id FROM sales_lines WHERE id = ?", line_id)
            if r:
                self._so(r["order_id"], "draft")
                self.conn.execute("DELETE FROM sales_lines WHERE id = ?", (line_id,))

    def confirm_sales_order(self, oid) -> None:
        with self.tx():
            o = self._so(oid, "draft")
            if not self.sales_lines(oid):
                raise ERPError("Add at least one line first.")
            self.conn.execute("UPDATE sales_orders SET status = 'confirmed' WHERE id = ?", (oid,))
            self._log("so.confirm", o["number"])

    def ship_sales_order(self, oid, quantities: dict | None = None, lots: dict | None = None) -> None:
        """Ship {line id: qty}, or everything still to ship. Stock can't go negative: it would be a false record. A line
        of an item tracked by lot says which lots it ships from: ``lots`` is {line id: [(lot, qty)]}."""
        lots = lots or {}
        with self.tx():
            o = self._so(oid, "confirmed")
            lines = self.sales_lines(oid)
            todo = {l["id"]: l["qty"] - l["shipped"] for l in lines} if quantities is None else quantities
            any_shipped, shipped_lots = False, []
            by_id = {l["id"]: l for l in lines}
            if set(lots) - set(by_id):
                raise ERPError("That line isn't on this order.")
            for line_id, q in todo.items():
                if q == 0:
                    continue
                line = by_id.get(line_id)
                if line is None:
                    raise ERPError("That line isn't on this order.")
                if q < 0 or q > line["qty"] - line["shipped"]:
                    raise ERPError(f"{line['number']}: can't ship {fmt_qty(q)}; {fmt_qty(line['qty'] - line['shipped'])} is left to ship.")
                have = self.on_hand(line["item_id"])
                if q > have:
                    raise ERPError(f"{line['number']}: {fmt_qty(have)} on hand, not enough to ship {fmt_qty(q)}. Nothing was shipped.")
                item = self.item(line["item_id"])
                taken = self._take(item, q, lots.get(line_id), "shipment", o["number"], item["cost"], "shipped")
                shipped_lots += [f"{item['number']} lot {lot}" for lot, _q in taken]
                self.conn.execute("UPDATE sales_lines SET shipped = shipped + ? WHERE id = ?", (q, line_id))
                any_shipped = True
            if not any_shipped:
                raise ERPError("Nothing to ship.")
            left = self.conn.execute("SELECT COALESCE(SUM(qty - shipped), 0) FROM sales_lines WHERE order_id = ?", (oid,)).fetchone()[0]
            if left == 0:
                self.conn.execute("UPDATE sales_orders SET status = 'shipped' WHERE id = ?", (oid,))
            self._log("so.ship", o["number"] + (f": {', '.join(shipped_lots)}" if shipped_lots else ""))

    def cancel_sales_order(self, oid) -> None:
        with self.tx():
            o = self._so(oid, "draft", "confirmed")
            if any(l["shipped"] for l in self.sales_lines(oid)):
                raise ERPError(f"{o['number']} has shipped lines, so it can't be cancelled.")
            self.conn.execute("UPDATE sales_orders SET status = 'cancelled' WHERE id = ?", (oid,))
            self._log("so.cancel", o["number"])

    # ---- invoices
    def invoice_sales_order(self, oid) -> int:
        """Invoice whatever has shipped and hasn't been invoiced yet."""
        with self.tx():
            o = self._so(oid, "confirmed", "shipped")
            lines = [l for l in self.sales_lines(oid) if l["shipped"] > l["invoiced"]]
            if not lines:
                raise ERPError(f"{o['number']} has nothing shipped that isn't already invoiced.")
            number = self._next("inv")
            subtotal = sum(line_total(l["shipped"] - l["invoiced"], l["unit_price"]) for l in lines)
            pct = Decimal(self.setting("tax_percent") or "0")
            tax = int((Decimal(subtotal) * pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            issued = date.today()
            due = issued + timedelta(days=o["terms_days"])
            cur = self.conn.execute("INSERT INTO invoices (number, order_id, customer_id, status, issued, due, subtotal, tax, tax_percent) "
                                    "VALUES (?,?,?,'open',?,?,?,?,?)", (number, oid, o["customer_id"], issued.isoformat(), due.isoformat(), subtotal, tax, str(pct)))
            inv = cur.lastrowid
            for l in lines:
                q = l["shipped"] - l["invoiced"]
                self.conn.execute("INSERT INTO invoice_lines (invoice_id, sales_line_id, item_id, qty, unit_price) VALUES (?,?,?,?,?)", (inv, l["id"], l["item_id"], q, l["unit_price"]))
                self.conn.execute("UPDATE sales_lines SET invoiced = invoiced + ? WHERE id = ?", (q, l["id"]))
            self._log("invoice.create", f"{number} for {o['number']}")
            return inv

    def invoices(self, status=None, search=""):
        q = f"%{search.strip()}%"
        cond = "AND v.status = ?" if status else ""
        args = [q, q] + ([status] if status else [])
        return self._rows(f"""SELECT v.*, c.name AS customer, o.number AS order_number, v.subtotal + v.tax AS total FROM invoices v
            JOIN contacts c ON c.id = v.customer_id JOIN sales_orders o ON o.id = v.order_id
            WHERE (v.number LIKE ? OR c.name LIKE ?) {cond} ORDER BY v.id DESC""", *args)  # noqa: S608

    def invoice(self, inv):
        return self._row("""SELECT v.*, c.name AS customer, c.address AS customer_address, o.number AS order_number, o.reference, v.subtotal + v.tax AS total FROM invoices v
            JOIN contacts c ON c.id = v.customer_id JOIN sales_orders o ON o.id = v.order_id WHERE v.id = ?""", inv)

    def invoice_lines(self, inv):
        return self._rows("SELECT l.*, i.number, i.description, i.unit FROM invoice_lines l JOIN items i ON i.id = l.item_id WHERE l.invoice_id = ? ORDER BY l.id", inv)

    def mark_invoice_paid(self, inv, paid_on=None) -> None:
        with self.tx():
            v = self.invoice(inv)
            if v is None or v["status"] != "open":
                raise ERPError("Only an open invoice can be marked paid.")
            self.conn.execute("UPDATE invoices SET status = 'paid', paid_on = ? WHERE id = ?", (_date(paid_on, "payment date") or today(), inv))
            self._log("invoice.paid", v["number"])

    def void_invoice(self, inv) -> None:
        """Void it and put its quantities back to be invoiced again. The number stays used."""
        with self.tx():
            v = self.invoice(inv)
            if v is None or v["status"] != "open":
                raise ERPError("Only an open invoice can be voided.")
            for l in self.invoice_lines(inv):
                self.conn.execute("UPDATE sales_lines SET invoiced = invoiced - ? WHERE id = ?", (l["qty"], l["sales_line_id"]))
            self.conn.execute("UPDATE invoices SET status = 'void' WHERE id = ?", (inv,))
            self._log("invoice.void", v["number"])

    # ---- purchase orders
    def create_purchase_order(self, supplier_id, due_date="", reference="", notes="") -> int:
        if not self.contact(supplier_id):
            raise ERPError("Choose a supplier.")
        with self.tx():
            number = self._next("po")
            cur = self.conn.execute("INSERT INTO purchase_orders (number, supplier_id, status, order_date, due_date, reference, notes) "
                                    "VALUES (?,?,'draft',?,?,?,?)", (number, supplier_id, today(), _date(due_date, "due date"), _clean(reference), str(notes or "")))
            self._log("po.create", number)
            return cur.lastrowid

    def purchase_orders(self, status=None, search=""):
        q = f"%{search.strip()}%"
        cond = "AND o.status = ?" if status else ""
        args = [q, q, q] + ([status] if status else [])
        return self._rows(f"""SELECT o.*, c.name AS supplier, COALESCE(SUM(l.qty * l.unit_cost / {QTY_SCALE}), 0) AS total,
            COUNT(l.id) AS line_count, COALESCE(SUM(l.qty - l.received), 0) AS to_receive
            FROM purchase_orders o JOIN contacts c ON c.id = o.supplier_id LEFT JOIN purchase_lines l ON l.order_id = o.id
            WHERE (o.number LIKE ? OR c.name LIKE ? OR o.reference LIKE ?) {cond} GROUP BY o.id ORDER BY o.id DESC""", *args)  # noqa: S608

    def purchase_order(self, oid):
        return self._row("SELECT o.*, c.name AS supplier, c.address AS supplier_address FROM purchase_orders o JOIN contacts c ON c.id = o.supplier_id WHERE o.id = ?", oid)

    def purchase_lines(self, oid):
        return self._rows("SELECT l.*, i.number, i.description, i.unit FROM purchase_lines l JOIN items i ON i.id = l.item_id WHERE l.order_id = ? ORDER BY l.id", oid)

    def _po(self, oid, *allowed):
        o = self.purchase_order(oid)
        if o is None:
            raise ERPError("That order no longer exists.")
        if allowed and o["status"] not in allowed:
            raise ERPError(f"{o['number']} is {o['status']}, so that can't be done.")
        return o

    def add_purchase_line(self, oid, item_id, qty, unit_cost=None) -> int:
        if qty <= 0:
            raise ERPError("Enter a quantity above zero.")
        with self.tx():
            self._po(oid, "draft")
            item = self.item(item_id)
            if item is None:
                raise ERPError("Choose an item.")
            cost = item["cost"] if unit_cost is None else unit_cost
            if cost < 0:
                raise ERPError("A cost can't be negative.")
            cur = self.conn.execute("INSERT INTO purchase_lines (order_id, item_id, qty, unit_cost) VALUES (?,?,?,?)", (oid, item_id, qty, cost))
            return cur.lastrowid

    def remove_purchase_line(self, line_id) -> None:
        with self.tx():
            r = self._row("SELECT order_id FROM purchase_lines WHERE id = ?", line_id)
            if r:
                self._po(r["order_id"], "draft")
                self.conn.execute("DELETE FROM purchase_lines WHERE id = ?", (line_id,))

    def place_purchase_order(self, oid) -> None:
        with self.tx():
            o = self._po(oid, "draft")
            if not self.purchase_lines(oid):
                raise ERPError("Add at least one line first.")
            self.conn.execute("UPDATE purchase_orders SET status = 'ordered' WHERE id = ?", (oid,))
            self._log("po.place", o["number"])

    def receive_purchase_order(self, oid, quantities: dict | None = None, lots: dict | None = None) -> None:
        """Receive {line id: qty}, or everything outstanding. A line of an item tracked by lot says the lot it came in as
        (the supplier's lot or batch number): ``lots`` is {line id: lot}. A line that came in as two lots is received
        twice, once for each."""
        lots = lots or {}
        with self.tx():
            o = self._po(oid, "ordered")
            lines = self.purchase_lines(oid)
            by_id = {l["id"]: l for l in lines}
            if set(lots) - set(by_id):
                raise ERPError("That line isn't on this order.")
            todo = {l["id"]: l["qty"] - l["received"] for l in lines} if quantities is None else quantities
            any_received, received_lots = False, []
            for line_id, q in todo.items():
                if q == 0:
                    continue
                line = by_id.get(line_id)
                if line is None:
                    raise ERPError("That line isn't on this order.")
                if q < 0 or q > line["qty"] - line["received"]:
                    raise ERPError(f"{line['number']}: can't receive {fmt_qty(q)}; {fmt_qty(line['qty'] - line['received'])} is outstanding.")
                item = self.item(line["item_id"])
                lot = ""
                if item["tracking"] == "lot":
                    if not _clean(lots.get(line_id)):
                        raise ERPError(f"{item['number']} is tracked by lot: say which lot it came in as (the supplier's lot "
                                       "or batch number). Nothing was received.")
                    lot = self._lot(item, lots[line_id])
                    received_lots.append(f"{item['number']} lot {lot}")
                elif _clean(lots.get(line_id)):
                    raise ERPError(f"{item['number']} isn't tracked by lot.")
                self._add_at_cost(item, q, line["unit_cost"], "receipt", o["number"], lot=lot)
                self.conn.execute("UPDATE purchase_lines SET received = received + ? WHERE id = ?", (q, line_id))
                any_received = True
            if not any_received:
                raise ERPError("Nothing to receive.")
            left = self.conn.execute("SELECT COALESCE(SUM(qty - received), 0) FROM purchase_lines WHERE order_id = ?", (oid,)).fetchone()[0]
            if left == 0:
                self.conn.execute("UPDATE purchase_orders SET status = 'received' WHERE id = ?", (oid,))
            self._log("po.receive", o["number"] + (f": {', '.join(received_lots)}" if received_lots else ""))

    def cancel_purchase_order(self, oid) -> None:
        with self.tx():
            o = self._po(oid, "draft", "ordered")
            if any(l["received"] for l in self.purchase_lines(oid)):
                raise ERPError(f"{o['number']} has received lines, so it can't be cancelled.")
            self.conn.execute("UPDATE purchase_orders SET status = 'cancelled' WHERE id = ?", (oid,))
            self._log("po.cancel", o["number"])

    # ---- work orders
    def create_work_order(self, item_id, qty, due_date="", notes="") -> int:
        if qty <= 0:
            raise ERPError("Enter a quantity above zero.")
        item = self.item(item_id)
        if item is None:
            raise ERPError("Choose an item.")
        with self.tx():
            number = self._next("wo")
            cur = self.conn.execute("INSERT INTO work_orders (number, item_id, qty, status, created, due_date, notes) VALUES (?,?,?,'draft',?,?,?)",
                                    (number, item_id, qty, today(), _date(due_date, "due date"), str(notes or "")))
            self._log("wo.create", number)
            return cur.lastrowid

    _WO_SELECT = "SELECT w.*, i.number AS item_number, i.description, i.unit, i.rw_document, i.rw_number FROM work_orders w JOIN items i ON i.id = w.item_id"

    def work_orders(self, status=None, search=""):
        q = f"%{search.strip()}%"
        cond = "AND w.status = ?" if status else ""
        args = [q, q] + ([status] if status else [])
        return self._rows(f"{self._WO_SELECT} WHERE (w.number LIKE ? OR i.number LIKE ?) {cond} ORDER BY w.id DESC", *args)  # noqa: S608

    def work_order(self, wid):
        return self._row(f"{self._WO_SELECT} WHERE w.id = ?", wid)  # noqa: S608

    def work_order_components(self, wid):
        w = self.work_order(wid)
        out = []
        for b in self.bom(w["item_id"]):
            each = b["qty"]
            need = (w["qty"] - w["done"]) * each // QTY_SCALE
            out.append({**b, "needed": need, "on_hand": self.on_hand(b["child_id"])})
        return out

    def release_work_order(self, wid, rw_document="", rw_revision="", rw_label="", rw_note="") -> None:
        """Release to the shop floor, recording which controlled revision is being built, if there is one."""
        with self.tx():
            w = self.work_order(wid)
            if w is None or w["status"] != "draft":
                raise ERPError("Only a draft work order can be released.")
            if not self.bom(w["item_id"]):
                raise ERPError(f"{w['item_number']} has no bill of materials, so nothing would be consumed. Add one first.")
            self.conn.execute("UPDATE work_orders SET status = 'released', build_rw_document = ?, build_rw_revision = ?, build_rw_label = ?, build_rw_note = ? WHERE id = ?",
                              (rw_document, rw_revision, rw_label, rw_note, wid))
            self._log("wo.release", f"{w['number']}" + (f" to Rev {rw_label}" if rw_label else ""))

    def _next_batch(self, w) -> int:
        """The number the next completion of work order ``w`` gets, counting from 1 (``stock_moves.batch``,
        ``wo_units.batch``)."""
        return 1 + self.conn.execute(
            "SELECT MAX(COALESCE((SELECT MAX(batch) FROM wo_units WHERE work_order_id = ?), 0), "
            "COALESCE((SELECT MAX(batch) FROM stock_moves WHERE ref = ? AND kind IN ('consume', 'produce')), 0))",
            (w["id"], w["number"])).fetchone()[0]

    def default_made_lot(self, wid) -> str:
        """The lot an item tracked by lot comes into stock as when its work order is completed, unless someone names
        another: the work order's number, then the number and the completion for later ones (WO-00012-2)."""
        w = self.work_order(wid)
        batch = self._next_batch(w)
        return w["number"] if batch == 1 else f"{w['number']}-{batch}"

    def complete_work_order(self, wid, qty=None, serials=None, lots=None, made_lot=None) -> None:
        """Consume components from stock and bring finished goods in at their actual cost. An item made with serial numbers
        needs one serial per unit made (``serials``): each unit comes into stock under its serial and is listed on the work
        order (``units_built``), ready to be registered in RevisionWorx.

        A component tracked by lot says which lots were used: ``lots`` is {component item id: [(lot, qty)]}, as someone
        says it was (``suggest_lots`` fills in a guess for them to check, never this). An item made that is tracked by
        lot comes in as ``made_lot``, or ``default_made_lot``. Every move of the completion carries its number, so what
        went into which units and lots can be traced."""
        lots = dict(lots or {})
        with self.tx():
            w = self.work_order(wid)
            if w is None or w["status"] != "released":
                raise ERPError("Only a released work order can be completed.")
            left = w["qty"] - w["done"]
            q = left if qty is None else qty
            if q <= 0 or q > left:
                raise ERPError(f"{fmt_qty(left)} is left to make on {w['number']}.")
            item = self.item(w["item_id"])
            serials = self._check_serials(item, q, serials)
            bom = self.bom(w["item_id"])
            if set(lots) - {b["child_id"] for b in bom}:
                raise ERPError(f"Lots were given for an item that isn't one of {item['number']}'s components.")
            batch = self._next_batch(w)
            made = ""
            if item["tracking"] == "lot":
                made = self._lot(item, made_lot if _clean(made_lot) else self.default_made_lot(wid))
            elif _clean(made_lot):
                raise ERPError(f"{item['number']} isn't tracked by lot.")
            cost = 0
            for b in self.work_order_uses(wid, q):
                use = b["use"]
                have = self.on_hand(b["child_id"])
                if use > have:
                    raise ERPError(f"{b['number']}: {fmt_qty(have)} on hand, {fmt_qty(use)} needed. Nothing was consumed.")
                self._take(self.item(b["child_id"]), use, lots.get(b["child_id"]), "consume", w["number"], b["cost"], "used",
                           batch)
                cost += line_total(use, b["cost"])
            unit = (cost * QTY_SCALE + q // 2) // q
            if serials:
                for sn in serials:
                    self._add_at_cost(self.item(w["item_id"]), QTY_SCALE, unit, "produce", w["number"], serial=sn, batch=batch)
                    self.conn.execute("INSERT INTO wo_units (work_order_id, item_id, serial, batch, made, model, name) "
                                      "VALUES (?,?,?,?,?,?,?)", (wid, w["item_id"], sn, batch, today(), item["number"],
                                                                 _short(item["description"], NAME_LIMIT)))
            else:
                self._add_at_cost(self.item(w["item_id"]), q, unit, "produce", w["number"], lot=made, batch=batch)
            done = w["done"] + q
            status = "complete" if done >= w["qty"] else "released"
            self.conn.execute("UPDATE work_orders SET done = ?, status = ? WHERE id = ?", (done, status, wid))
            self._log("wo.complete", f"{w['number']}, {fmt_qty(q)} made" + (f": {', '.join(serials)}" if serials else "")
                      + (f" as lot {made}" if made else ""))

    def _check_serials(self, item, q, serials) -> list[str]:
        """The serials for ``q`` units of ``item``: one each, none repeated, none already made. None for an item without."""
        if item["tracking"] != "serial":
            if serials:
                raise ERPError(f"{item['number']} isn't made with serial numbers.")
            return []
        if q % QTY_SCALE:
            raise ERPError(f"{item['number']} is made with serial numbers, so complete whole units.")
        out = [unicodedata.normalize("NFC", _clean(sn)) for sn in (serials or []) if _clean(sn)]
        if len(out) != q // QTY_SCALE:
            raise ERPError(f"Give one serial number for each of the {fmt_qty(q)} {item['number']} made; {len(out)} given.")
        seen = set()
        for sn in out:
            if sn.casefold() in seen:
                raise ERPError(f"{sn} is given twice.")
            seen.add(sn.casefold())
            if len(sn) > SERIAL_LIMIT:
                raise ERPError(f"{sn[:20]}… is longer than a serial number can be ({SERIAL_LIMIT} characters).")
            if any(unicodedata.category(ch) == "Cc" for ch in sn):
                raise ERPError(f"{sn!r} has a control character in it, which a serial number can't have.")
            had = self._row("SELECT u.serial, u.model, w.number FROM wo_units u JOIN work_orders w ON w.id = u.work_order_id "
                            "WHERE u.serial = ? COLLATE NOCASE", sn)
            if had:
                raise ERPError(f"Serial number {had['serial']} was already given, to the {had['model']} made on "
                               f"{had['number']}. A serial number names one unit.")
        return out

    # ---- units built, and registering them in RevisionWorx (the one write to it; Director's decision, 2026-11-07)
    def units_built(self, wid) -> list[dict]:
        """The units a work order made, by serial, in the order made, with what RevisionWorx says of each."""
        return self._rows("SELECT * FROM wo_units WHERE work_order_id = ? ORDER BY batch, id", wid)

    def register_txid(self, wid, batch) -> str:
        """The txid a completion's units are registered with: the same for every attempt, so RevisionWorx records them once
        however often it is asked (its docs/INTEGRATION.md)."""
        w = self.work_order(wid)
        cid = self.setting("company_id")
        if len(cid) != 32 or any(ch not in "0123456789abcdef" for ch in cid):
            raise ERPError("This company file has no company id, so its units can't be registered in RevisionWorx: "
                           "two companies' work orders of the same number would look alike there.")
        key = f"{REGISTER_DOMAIN}\0{cid}\0{w['number']}\0{batch}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    def register_units(self, wid, client) -> dict:
        """Register in RevisionWorx the units this work order made that aren't registered yet, one completion at a time:
        RevisionWorx records all of a completion's units or none. ``client`` is a revisionworx.Client.

        Every attempt at a completion sends the same thing (its txid, all of its serials, and what they were built as,
        kept when they were made), so RevisionWorx records it once however often it is asked, and an earlier attempt
        whose answer was lost is simply answered again. Returns ``{"registered": [serials], "refused": [(serials,
        why)]}``; what RevisionWorx refused stays listed on the work order with why, and nothing about it changed there."""
        w = self.work_order(wid)
        if w is None:
            raise ERPError("No such work order.")
        batches: dict[int, list[dict]] = {}
        for u in self.units_built(wid):
            batches.setdefault(u["batch"], []).append(u)
        doc = f"{w['build_rw_document']}@{w['build_rw_revision']}" if w["build_rw_document"] and w["build_rw_revision"] else ""
        out = {"registered": [], "refused": []}
        for batch, units in sorted(batches.items()):
            if all(u["rw_unit"] for u in units):
                continue
            serials = [u["serial"] for u in units]
            try:
                got = client.register_units(self.register_txid(wid, batch), serials, model=units[0]["model"],
                                            name=units[0]["name"], built=units[0]["made"], document=doc,
                                            evidence=f"work-order:{w['number']}")
            except RevisionWorxError as e:
                note = str(e) or "RevisionWorx refused."
                if getattr(e, "kind", "") == "txid-used":
                    note = (f"RevisionWorx already has different units registered from this completion of {w['number']} "
                            "(from another copy of this company file, or an older backup of it, say). Nothing was changed "
                            "there; check the units in RevisionWorx.")
                pending = [u for u in units if not u["rw_unit"]]
                with self.tx():
                    for u in pending:
                        self.conn.execute("UPDATE wo_units SET rw_note = ? WHERE id = ?", (note, u["id"]))
                out["refused"].append(([u["serial"] for u in pending], note))
                continue
            ids = {_serial_key(sn): uid for sn, uid in got}
            done, missing = [], []
            with self.tx():
                for u in units:
                    if u["rw_unit"]:
                        continue
                    uid = ids.get(_serial_key(u["serial"]), "")
                    if uid:
                        self.conn.execute("UPDATE wo_units SET rw_unit = ?, rw_note = '' WHERE id = ?", (uid, u["id"]))
                        done.append(u["serial"])
                    else:
                        missing.append(u["serial"])
                        self.conn.execute("UPDATE wo_units SET rw_note = ? WHERE id = ?", (MISSING_NOTE, u["id"]))
                if done:
                    self._log("wo.register", f"{w['number']}: {', '.join(done)} in RevisionWorx")
            out["registered"] += done
            if missing:
                out["refused"].append((missing, MISSING_NOTE))
        return out

    def cancel_work_order(self, wid) -> None:
        with self.tx():
            w = self.work_order(wid)
            if w is None or w["status"] not in ("draft", "released"):
                raise ERPError("Only a draft or released work order can be cancelled.")
            if w["done"]:
                raise ERPError(f"{w['number']} has finished quantities, so it can't be cancelled.")
            self.conn.execute("UPDATE work_orders SET status = 'cancelled' WHERE id = ?", (wid,))
            self._log("wo.cancel", w["number"])

    def work_order_uses(self, wid, qty) -> list[dict]:
        """What completing ``qty`` of a work order takes from stock: each BOM line with ``use``, rounded up as
        ``complete_work_order`` rounds it."""
        w = self.work_order(wid)
        return [{**b, "use": (qty * b["qty"] + QTY_SCALE - 1) // QTY_SCALE} for b in self.bom(w["item_id"])]

    def work_order_lots(self, wid) -> list[dict]:
        """The lots a work order used and made, completion by completion: batch, kind ('consume' or 'produce'), item_id,
        number, lot and quantity (positive)."""
        w = self.work_order(wid)
        return self._rows("SELECT m.batch, m.kind, m.item_id, i.number, m.lot, SUM(ABS(m.qty)) AS qty FROM stock_moves m "
                          "JOIN items i ON i.id = m.item_id WHERE m.ref = ? AND m.kind IN ('consume', 'produce') AND m.lot <> '' "
                          "GROUP BY m.batch, m.kind, m.item_id, m.lot ORDER BY m.batch, m.kind, MIN(m.id)", w["number"])

    # ---- tracing a lot (docs/COMPANY_FILE.md, format 3)
    def trace_lot(self, item_id, lot) -> dict:
        """Where a lot came from and where it went, as far as the ledger follows it.

        ``came`` and ``went`` are trees of steps: {kind, what, item, code (lot or serial), qty, ref, who, date, note,
        children}. A lot used on a work order leads to what that completion made: lots made are followed in turn (the
        whole lot, so a lot others were added to is followed with them, which can only widen a recall), units made are
        listed by serial, and an item made that isn't tracked ends the trail, saying so. A lot that came from a work
        order shows what that completion used. ``units``, ``shipments``, ``in_stock``, ``untracked`` and ``lots`` (the lot
        traced, then every lot made from it) gather what the lot reached, for a recall."""
        item = self.item(item_id)
        if item is None:
            raise ERPError("No such item.")
        moves = self._lot_moves(item_id, lot)
        if not moves:
            raise ERPError(f"{item['number']} has no lot {lot}.")
        lot = moves[0]["lot"]
        out = {"item": item["number"], "description": item["description"], "unit": item["unit"], "lot": lot,
               "on_hand": sum(m["qty"] for m in moves), "units": [], "shipments": [], "in_stock": [], "untracked": [],
               "lots": [{"item": item["number"], "lot": lot}], "cut_short": False}
        out["came"] = self._came(item, moves, out, 0, {(item_id, lot)})
        out["went"] = self._went(item, lot, moves, out, 0, {(item_id, lot)})
        return out

    def _lot_moves(self, item_id, lot) -> list[dict]:
        return self._rows("SELECT * FROM stock_moves WHERE item_id = ? AND lot = ? COLLATE NOCASE AND lot <> '' ORDER BY id",
                          item_id, unicodedata.normalize("NFC", _clean(lot)))

    def _step(self, kind, what, item, code="", qty=0, ref="", who="", date="", note="", children=None) -> dict:
        return {"kind": kind, "what": what, "item": item, "code": code, "qty": qty, "ref": ref, "who": who, "date": date,
                "note": note, "children": children or []}

    def _party(self, kind, number) -> str:
        sql = {"receipt": "SELECT c.name FROM purchase_orders o JOIN contacts c ON c.id = o.supplier_id WHERE o.number = ?",
               "shipment": "SELECT c.name FROM sales_orders o JOIN contacts c ON c.id = o.customer_id WHERE o.number = ?"}[kind]
        r = self.conn.execute(sql, (number,)).fetchone()
        return r[0] if r else ""

    @staticmethod
    def _completion(m) -> str:
        return f"{m['ref']} (completion {m['batch']})" if m["batch"] else m["ref"]

    def _completion_moves(self, m, kind) -> list[dict]:
        """The moves of ``kind`` in the work order completion that move ``m`` was part of."""
        if not m["batch"]:
            return []
        return self._rows("SELECT m.*, i.number, i.description, i.tracking FROM stock_moves m JOIN items i ON i.id = m.item_id "
                          "WHERE m.ref = ? AND m.batch = ? AND m.kind = ? ORDER BY m.id", m["ref"], m["batch"], kind)

    def _came(self, item, moves, out, depth, seen) -> list[dict]:
        steps = []
        for m in moves:
            if m["qty"] <= 0:
                continue
            date = m["time"][:10]
            if m["kind"] == "receipt":
                steps.append(self._step("received", "Received", item["number"], m["lot"], m["qty"], m["ref"],
                                        self._party("receipt", m["ref"]), date))
            elif m["kind"] == "produce":
                used = []
                for u in self._completion_moves(m, "consume"):
                    if u["lot"] and depth + 1 < TRACE_DEPTH and (u["item_id"], u["lot"]) not in seen:
                        child = self.item(u["item_id"])
                        kids = self._came(child, self._lot_moves(u["item_id"], u["lot"]), out, depth + 1, seen | {(u["item_id"], u["lot"])})
                    else:
                        kids = []
                        out["cut_short"] |= bool(u["lot"]) and depth + 1 >= TRACE_DEPTH
                    note = "" if u["lot"] else UNFOLLOWED.get(u["tracking"], UNFOLLOWED["none"])
                    used.append(self._step("used", "Made from", u["number"], u["lot"], -u["qty"], self._completion(u), "",
                                           u["time"][:10], note, kids))
                steps.append(self._step("made", "Made", item["number"], m["lot"], m["qty"], self._completion(m), "", date,
                                        children=used))
            else:
                steps.append(self._step("adjusted", "Added by adjustment", item["number"], m["lot"], m["qty"], "", "", date,
                                        m["note"]))
        return steps

    def _went(self, item, lot, moves, out, depth, seen) -> list[dict]:
        steps = []
        for m in moves:
            if m["qty"] >= 0:
                continue
            date = m["time"][:10]
            if m["kind"] == "shipment":
                who = self._party("shipment", m["ref"])
                steps.append(self._step("shipped", "Shipped", item["number"], lot, -m["qty"], m["ref"], who, date))
                out["shipments"].append({"item": item["number"], "lot": lot, "qty": -m["qty"], "order": m["ref"],
                                         "customer": who, "date": date})
            elif m["kind"] == "consume":
                steps.append(self._step("used", "Used", item["number"], lot, -m["qty"], self._completion(m), "", date,
                                        children=self._made_from(m, out, depth, seen)))
            else:
                steps.append(self._step("adjusted", "Taken out by adjustment", item["number"], lot, -m["qty"], "", "", date,
                                        m["note"]))
        have = sum(m["qty"] for m in moves)
        if have:
            steps.append(self._step("stock", "In stock", item["number"], lot, have))
            out["in_stock"].append({"item": item["number"], "lot": lot, "qty": have})
        return steps

    def _made_from(self, m, out, depth, seen) -> list[dict]:
        """What the completion that used move ``m`` made, followed onward."""
        made = []
        produced = self._completion_moves(m, "produce")
        if not produced:
            return [self._step("untracked", "What this completion made can't be found in the ledger", "")]
        units = {u["serial"]: u for u in self._rows(
            "SELECT u.* FROM wo_units u JOIN work_orders w ON w.id = u.work_order_id WHERE w.number = ? AND u.batch = ?",
            m["ref"], m["batch"])}
        for p in produced:
            date = p["time"][:10]
            if p["serial"]:
                u = units.get(p["serial"], {})
                made.append(self._step("unit", "Unit made", p["number"], p["serial"], p["qty"], self._completion(p), "", date,
                                       "in RevisionWorx's unit register" if u.get("rw_unit") else ""))
                out["units"].append({"item": p["number"], "serial": p["serial"], "order": p["ref"], "made": date,
                                     "rw_unit": u.get("rw_unit", "")})
            elif p["lot"]:
                key = (p["item_id"], p["lot"])
                if key in seen or depth + 1 >= TRACE_DEPTH:
                    out["cut_short"] |= key not in seen
                    kids = []
                else:
                    kids = self._went(self.item(p["item_id"]), p["lot"], self._lot_moves(p["item_id"], p["lot"]), out,
                                      depth + 1, seen | {key})
                made.append(self._step("made", "Made", p["number"], p["lot"], p["qty"], self._completion(p), "", date,
                                       children=kids))
                if {"item": p["number"], "lot": p["lot"]} not in out["lots"]:
                    out["lots"].append({"item": p["number"], "lot": p["lot"]})
            else:
                made.append(self._step("untracked", "Made", p["number"], "", p["qty"], self._completion(p), "", date,
                                       UNFOLLOWED["none"]))
                out["untracked"].append({"item": p["number"], "qty": p["qty"], "order": self._completion(p), "made": date})
        return made

    # ---- from RevisionWorx
    def import_bom(self, root_number: str, parts: list, lines: list, source: dict) -> dict:
        """Replace item BOMs from a validated RevisionWorx structure, atomically.

        parts: [{"number", "description", "unit"}]; lines: [{"parent", "child", "qty" (int), "find"}]. Items that
        don't exist yet are created. Stock, costs and prices of existing items are left alone."""
        with self.tx():
            created, replaced = [], []
            parents = {l["parent"].casefold() for l in lines}
            ids = {}
            for p in parts:
                number = _clean(p["number"])
                if not number:
                    raise ERPError("The BOM has a part with no number.")
                found = self.item_by_number(number)
                if found is None:
                    item_id = self.add_item(number, p.get("description", ""), "make" if number.casefold() in parents else "buy", p.get("unit") or "EA")
                    created.append(number)
                else:
                    item_id = found["id"]
                ids[number.casefold()] = item_id
            for parent in sorted(parents):
                if parent not in ids:
                    raise ERPError(f"The BOM names a parent {parent} it doesn't list.")
                self.conn.execute("DELETE FROM bom_lines WHERE parent_id = ?", (ids[parent],))
                self.conn.execute("UPDATE items SET kind = 'make' WHERE id = ?", (ids[parent],))
                replaced.append(parent)
            for l in lines:
                parent, child = ids.get(l["parent"].casefold()), ids.get(l["child"].casefold())
                if parent is None or child is None:
                    raise ERPError(f"A BOM line refers to {l['child']}, which isn't in the BOM.")
                self.set_bom_line(parent, child, l["qty"], l.get("find", ""))
            root = ids.get(root_number.casefold())
            if root is None:
                raise ERPError(f"The BOM's top item {root_number} isn't in it.")
            self.conn.execute("UPDATE items SET bom_rw_document = ?, bom_rw_revision = ?, bom_rw_label = ?, bom_rw_sha256 = ? WHERE id = ?",
                              (source.get("document", ""), source.get("revision", ""), source.get("label", ""), source.get("sha256", ""), root))
            self._log("bom.import", f"{root_number} from {source.get('number', '')} Rev {source.get('label', '')}")
            return {"root": root, "created": created, "replaced": replaced, "lines": len(lines)}

    # ---- overview
    def attention(self):
        """What needs someone's attention, most urgent first: (severity, text, page, record id)."""
        out = []
        t = today()
        for v in self._rows("SELECT v.id, v.number, v.due, c.name, v.subtotal + v.tax AS total FROM invoices v JOIN contacts c ON c.id = v.customer_id WHERE v.status = 'open' AND v.due < ? ORDER BY v.due", t):
            out.append(("danger", f"{v['number']} from {v['name']} is overdue: {self.money(v['total'])}, due {v['due']}", "invoices", v["id"]))
        for o in self._rows("SELECT o.id, o.number, o.due_date, c.name FROM sales_orders o JOIN contacts c ON c.id = o.customer_id WHERE o.status = 'confirmed' AND o.due_date <> '' AND o.due_date < ? ORDER BY o.due_date", t):
            out.append(("danger", f"{o['number']} for {o['name']} was due {o['due_date']}", "sales", o["id"]))
        for o in self._rows("SELECT o.id, o.number, o.due_date, c.name FROM purchase_orders o JOIN contacts c ON c.id = o.supplier_id WHERE o.status = 'ordered' AND o.due_date <> '' AND o.due_date < ? ORDER BY o.due_date", t):
            out.append(("warning", f"{o['number']} from {o['name']} was due {o['due_date']}", "purchasing", o["id"]))
        for w in self._rows("SELECT w.id, w.number, w.due_date, i.number AS item FROM work_orders w JOIN items i ON i.id = w.item_id WHERE w.status = 'released' AND w.due_date <> '' AND w.due_date < ? ORDER BY w.due_date", t):
            out.append(("warning", f"{w['number']} ({w['item']}) was due {w['due_date']}", "production", w["id"]))
        for i in self.items():
            if i["reorder_point"] and i["on_hand"] - i["allocated"] + i["on_order"] < i["reorder_point"]:
                out.append(("warning", f"{i['number']} is below its reorder point: {fmt_qty(i['on_hand'])} on hand, {fmt_qty(i['allocated'])} allocated", "planning", i["id"]))
        return out

    def summary(self) -> dict:
        one = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]  # noqa: E731
        return {"stock_value": self.stock_value(),
                "open_sales": one("SELECT COUNT(*) FROM sales_orders WHERE status = 'confirmed'"),
                "open_sales_value": one(f"SELECT COALESCE(SUM((l.qty - l.shipped) * l.unit_price / {QTY_SCALE}), 0) FROM sales_lines l JOIN sales_orders o ON o.id = l.order_id WHERE o.status = 'confirmed'"),  # noqa: S608
                "receivable": one("SELECT COALESCE(SUM(subtotal + tax), 0) FROM invoices WHERE status = 'open'"),
                "open_invoices": one("SELECT COUNT(*) FROM invoices WHERE status = 'open'"),
                "open_purchases": one("SELECT COUNT(*) FROM purchase_orders WHERE status = 'ordered'"),
                "open_purchase_value": one(f"SELECT COALESCE(SUM((l.qty - l.received) * l.unit_cost / {QTY_SCALE}), 0) FROM purchase_lines l JOIN purchase_orders o ON o.id = l.order_id WHERE o.status = 'ordered'"),  # noqa: S608
                "open_work": one("SELECT COUNT(*) FROM work_orders WHERE status = 'released'")}

    def activity(self, limit=20):
        return self._rows("SELECT * FROM audit ORDER BY id DESC LIMIT ?", limit)
