"""The company file: one SQLite database with a versioned schema. Stock moves and the audit log can't be altered.

Foreign keys are enforced, and every change is one transaction, so a crash leaves the last complete state.
"""
from __future__ import annotations

import os
import sqlite3

APPLICATION_ID = 0x4F4D4552      # "OMER"
SCHEMA_VERSION = 1


class CompanyFileError(ValueError):
    """The file can't be used. The message is written for the user."""


SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE sequences (name TEXT PRIMARY KEY, last INTEGER NOT NULL) STRICT;

CREATE TABLE contacts (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('customer', 'supplier')),
    name TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '', terms_days INTEGER NOT NULL DEFAULT 30 CHECK (terms_days >= 0),
    notes TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1) STRICT;

CREATE TABLE items (
    id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE COLLATE NOCASE, description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL CHECK (kind IN ('buy', 'make')), unit TEXT NOT NULL DEFAULT 'EA',
    cost INTEGER NOT NULL DEFAULT 0 CHECK (cost >= 0), price INTEGER NOT NULL DEFAULT 0 CHECK (price >= 0),
    reorder_point INTEGER NOT NULL DEFAULT 0 CHECK (reorder_point >= 0),
    reorder_qty INTEGER NOT NULL DEFAULT 0 CHECK (reorder_qty >= 0),
    supplier_id INTEGER REFERENCES contacts(id), lead_days INTEGER NOT NULL DEFAULT 0 CHECK (lead_days >= 0),
    bin TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
    rw_document TEXT NOT NULL DEFAULT '', rw_number TEXT NOT NULL DEFAULT '',
    bom_rw_document TEXT NOT NULL DEFAULT '', bom_rw_revision TEXT NOT NULL DEFAULT '',
    bom_rw_label TEXT NOT NULL DEFAULT '', bom_rw_sha256 TEXT NOT NULL DEFAULT '') STRICT;

CREATE TABLE bom_lines (
    id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    child_id INTEGER NOT NULL REFERENCES items(id), qty INTEGER NOT NULL CHECK (qty > 0),
    find_number TEXT NOT NULL DEFAULT '', UNIQUE (parent_id, child_id), CHECK (parent_id <> child_id)) STRICT;

CREATE TABLE stock_moves (
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, item_id INTEGER NOT NULL REFERENCES items(id),
    qty INTEGER NOT NULL CHECK (qty <> 0), unit_cost INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL CHECK (kind IN ('receipt', 'shipment', 'consume', 'produce', 'adjust')),
    ref TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', user TEXT NOT NULL DEFAULT '') STRICT;
CREATE INDEX stock_moves_item ON stock_moves (item_id);
CREATE TRIGGER stock_moves_no_update BEFORE UPDATE ON stock_moves
    BEGIN SELECT RAISE(ABORT, 'stock moves cannot be changed; post a correction'); END;
CREATE TRIGGER stock_moves_no_delete BEFORE DELETE ON stock_moves
    BEGIN SELECT RAISE(ABORT, 'stock moves cannot be deleted; post a correction'); END;

CREATE TABLE sales_orders (
    id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, customer_id INTEGER NOT NULL REFERENCES contacts(id),
    status TEXT NOT NULL CHECK (status IN ('draft', 'confirmed', 'shipped', 'cancelled')),
    order_date TEXT NOT NULL, due_date TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '') STRICT;
CREATE TABLE sales_lines (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id), qty INTEGER NOT NULL CHECK (qty > 0),
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0), shipped INTEGER NOT NULL DEFAULT 0 CHECK (shipped >= 0),
    invoiced INTEGER NOT NULL DEFAULT 0 CHECK (invoiced >= 0)) STRICT;

CREATE TABLE purchase_orders (
    id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, supplier_id INTEGER NOT NULL REFERENCES contacts(id),
    status TEXT NOT NULL CHECK (status IN ('draft', 'ordered', 'received', 'cancelled')),
    order_date TEXT NOT NULL, due_date TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '') STRICT;
CREATE TABLE purchase_lines (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id), qty INTEGER NOT NULL CHECK (qty > 0),
    unit_cost INTEGER NOT NULL CHECK (unit_cost >= 0), received INTEGER NOT NULL DEFAULT 0 CHECK (received >= 0)) STRICT;

CREATE TABLE work_orders (
    id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, item_id INTEGER NOT NULL REFERENCES items(id),
    qty INTEGER NOT NULL CHECK (qty > 0), done INTEGER NOT NULL DEFAULT 0 CHECK (done >= 0),
    status TEXT NOT NULL CHECK (status IN ('draft', 'released', 'complete', 'cancelled')),
    created TEXT NOT NULL, due_date TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    build_rw_document TEXT NOT NULL DEFAULT '', build_rw_revision TEXT NOT NULL DEFAULT '',
    build_rw_label TEXT NOT NULL DEFAULT '', build_rw_note TEXT NOT NULL DEFAULT '') STRICT;

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, order_id INTEGER NOT NULL REFERENCES sales_orders(id),
    customer_id INTEGER NOT NULL REFERENCES contacts(id), status TEXT NOT NULL CHECK (status IN ('open', 'paid', 'void')),
    issued TEXT NOT NULL, due TEXT NOT NULL, paid_on TEXT NOT NULL DEFAULT '',
    subtotal INTEGER NOT NULL, tax INTEGER NOT NULL, tax_percent TEXT NOT NULL DEFAULT '0') STRICT;
CREATE TABLE invoice_lines (
    id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    sales_line_id INTEGER NOT NULL REFERENCES sales_lines(id), item_id INTEGER NOT NULL REFERENCES items(id),
    qty INTEGER NOT NULL, unit_price INTEGER NOT NULL) STRICT;

CREATE TABLE audit (
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, user TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '') STRICT;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'the log cannot be changed'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'the log cannot be changed'); END;
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=8.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def _check_sqlite() -> None:
    """Company files use STRICT tables, new in SQLite 3.37. Early Python 3.10 builds for Windows ship an older one."""
    if sqlite3.sqlite_version_info < (3, 37):
        raise CompanyFileError(f"OpenMeridian needs SQLite 3.37 or newer, and this Python has {sqlite3.sqlite_version}. Update Python.")


def create(path: str) -> sqlite3.Connection:
    _check_sqlite()
    if os.path.exists(path):
        raise CompanyFileError(f"{path} already exists. Choose another name, or open it.")
    conn = _connect(path)
    try:
        conn.executescript("BEGIN;\n" + SCHEMA + f"\nPRAGMA application_id = {APPLICATION_ID};\n"
                           f"PRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    except sqlite3.Error:
        conn.close()
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return conn


def open_existing(path: str) -> sqlite3.Connection:
    _check_sqlite()
    if not os.path.isfile(path):
        raise CompanyFileError(f"{path} can't be found.")
    conn = None
    try:
        conn = _connect(path)
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if app_id != APPLICATION_ID:
            raise CompanyFileError("This is not an OpenMeridian company file.")
        if version > SCHEMA_VERSION:
            raise CompanyFileError(f"This company file was saved by a newer OpenMeridian (format {version}). Please update.")
        if version < 1:
            raise CompanyFileError("This company file is damaged: its format can't be read.")
        problems = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
        if problems != "ok":
            raise CompanyFileError(f"This company file is damaged and was not opened, so nothing changes.\n\n{problems}")
    except sqlite3.DatabaseError as e:
        if conn is not None:
            conn.close()
        raise CompanyFileError(f"This is not an OpenMeridian company file, or it is damaged.\n\n{e}") from e
    except CompanyFileError:
        conn.close()
        raise
    return conn


def backup(conn: sqlite3.Connection, dest: str) -> None:
    """A complete, consistent copy, safe to take while the file is open. Refuses to overwrite."""
    if os.path.exists(dest):
        raise CompanyFileError(f"{dest} already exists. Choose another name.")
    tmp = dest + ".tmp"
    out = sqlite3.connect(tmp)
    try:
        conn.backup(out)
        problems = out.execute("PRAGMA integrity_check(1)").fetchone()[0]
    finally:
        out.close()
    if problems != "ok":
        os.unlink(tmp)
        raise CompanyFileError("The backup failed its integrity check, so it was not kept.")
    os.replace(tmp, dest)
