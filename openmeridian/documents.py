"""Printable business documents as HTML, shared by PDF export and anything else that needs them. No GUI here."""
from __future__ import annotations

from html import escape as e

from .values import fmt_qty, line_total

STYLE = """body{font-family:Arial,Helvetica,sans-serif;font-size:10pt;color:#1b1f24}h1{font-size:18pt;margin:0}
.muted{color:#626b75}table{border-collapse:collapse;width:100%}th{text-align:left;color:#626b75;font-size:9pt;
border-bottom:1px solid #8a929b;padding:5px 8px 5px 0}td{padding:5px 8px 5px 0;border-bottom:1px solid #dcdfe4;vertical-align:top}
.num{text-align:right}.total td{border:none;font-weight:bold}"""


def _lines_br(text) -> str:
    return "<br>".join(e(x) for x in str(text or "").splitlines())


def _head(company, title, number, facts, party_label, party, address) -> str:
    rows = "".join(f'<tr><td class="muted" style="border:none">{e(k)}</td><td style="border:none">{e(str(v))}</td></tr>' for k, v in facts if v)
    return (f'<table style="margin-bottom:18px"><tr><td style="border:none"><b style="font-size:13pt">{e(company.setting("company_name"))}</b><br>'
            f'<span class="muted">{_lines_br(company.setting("address"))}</span></td>'
            f'<td style="border:none;text-align:right"><h1>{e(title)}</h1><b>{e(number)}</b></td></tr></table>'
            f'<table style="margin-bottom:16px"><tr><td style="border:none;width:55%"><span class="muted">{e(party_label)}</span><br><b>{e(party)}</b><br>{_lines_br(address)}</td>'
            f'<td style="border:none"><table>{rows}</table></td></tr></table>')


def _table(rows, money_label) -> str:
    body = "".join(f'<tr><td>{e(n)}</td><td>{e(d)}</td><td class="num">{e(q)}</td><td class="num">{e(p)}</td><td class="num">{e(t)}</td></tr>' for n, d, q, p, t in rows)
    return (f'<table><tr><th>Item</th><th>Description</th><th class="num">Qty</th><th class="num">{e(money_label)}</th><th class="num">Amount</th></tr>{body}</table>')


def _page(inner) -> str:
    return f"<html><head><style>{STYLE}</style></head><body>{inner}</body></html>"


def invoice_html(c, inv_id) -> str:
    v = c.invoice(inv_id)
    rows = [(l["number"], l["description"], f'{fmt_qty(l["qty"])} {l["unit"]}', c.money(l["unit_price"]), c.money(line_total(l["qty"], l["unit_price"]))) for l in c.invoice_lines(inv_id)]
    facts = [("Issued", v["issued"]), ("Due", v["due"]), ("Order", v["order_number"]), ("Your reference", v["reference"])]
    totals = (f'<table style="margin-top:10px"><tr class="total"><td style="width:70%"></td><td>Subtotal</td><td class="num">{c.money(v["subtotal"])}</td></tr>'
              f'<tr class="total"><td></td><td>Tax ({e(v["tax_percent"])}%)</td><td class="num">{c.money(v["tax"])}</td></tr>'
              f'<tr class="total"><td></td><td>Total</td><td class="num">{c.money(v["total"])}</td></tr></table>')
    void = '<p style="color:#c0392b"><b>VOID</b></p>' if v["status"] == "void" else ""
    return _page(_head(c, "Invoice", v["number"], facts, "Bill to", v["customer"], v["customer_address"]) + void + _table(rows, "Price") + totals)


def sales_order_html(c, oid) -> str:
    o = c.sales_order(oid)
    lines = c.sales_lines(oid)
    rows = [(l["number"], l["description"], f'{fmt_qty(l["qty"])} {l["unit"]}', c.money(l["unit_price"]), c.money(line_total(l["qty"], l["unit_price"]))) for l in lines]
    total = sum(line_total(l["qty"], l["unit_price"]) for l in lines)
    addr = c.contact(o["customer_id"])["address"]
    facts = [("Date", o["order_date"]), ("Due", o["due_date"]), ("Your reference", o["reference"])]
    return _page(_head(c, "Sales order", o["number"], facts, "Customer", o["customer"], addr) + _table(rows, "Price")
                 + f'<table style="margin-top:10px"><tr class="total"><td style="width:70%"></td><td>Total</td><td class="num">{c.money(total)}</td></tr></table>')


def purchase_order_html(c, oid) -> str:
    o = c.purchase_order(oid)
    lines = c.purchase_lines(oid)
    rows = [(l["number"], l["description"], f'{fmt_qty(l["qty"])} {l["unit"]}', c.money(l["unit_cost"]), c.money(line_total(l["qty"], l["unit_cost"]))) for l in lines]
    total = sum(line_total(l["qty"], l["unit_cost"]) for l in lines)
    facts = [("Date", o["order_date"]), ("Needed by", o["due_date"]), ("Reference", o["reference"])]
    return _page(_head(c, "Purchase order", o["number"], facts, "Supplier", o["supplier"], o["supplier_address"]) + _table(rows, "Cost")
                 + f'<table style="margin-top:10px"><tr class="total"><td style="width:70%"></td><td>Total</td><td class="num">{c.money(total)}</td></tr></table>')
