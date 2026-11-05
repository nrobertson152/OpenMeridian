"""Money and quantities. Never floats: amounts are whole cents, quantities whole thousandths of a unit."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

QTY_SCALE = 1000
CENTS = 100


class ValueProblem(ValueError):
    """Bad input. The message is written for the user."""


def _dec(text, what) -> Decimal:
    s = str(text).strip().replace(",", "")
    if s[:1] in "$€£":
        s = s[1:].strip()
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueProblem(f"Enter a number for {what}.") from None
    if not d.is_finite() or abs(d) > Decimal("1e12"):
        raise ValueProblem(f"Enter a sensible number for {what}.")
    return d


def parse_qty(text, what="the quantity") -> int:
    return int((_dec(text, what) * QTY_SCALE).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_money(text, what="the amount") -> int:
    return int((_dec(text, what) * CENTS).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fmt_qty(q: int) -> str:
    sign = "-" if q < 0 else ""
    whole, frac = divmod(abs(int(q)), QTY_SCALE)
    if frac:
        return f"{sign}{whole:,}.{frac:03d}".rstrip("0")
    return f"{sign}{whole:,}"


def fmt_money(c: int, symbol: str = "$") -> str:
    sign = "-" if c < 0 else ""
    whole, frac = divmod(abs(int(c)), CENTS)
    return f"{sign}{symbol}{whole:,}.{frac:02d}"


def line_total(qty: int, unit_cents: int) -> int:
    """Quantity × unit price, rounded half up to the cent."""
    n = qty * unit_cents
    return (2 * n + QTY_SCALE) // (2 * QTY_SCALE) if n >= 0 else -((-2 * n + QTY_SCALE) // (2 * QTY_SCALE))
