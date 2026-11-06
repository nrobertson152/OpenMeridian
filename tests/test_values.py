import pytest

from openmeridian.values import ValueProblem, fmt_money, fmt_qty, line_total, parse_money, parse_qty


def test_no_floats_lost():
    assert parse_money("0.10") + parse_money("0.20") == parse_money("0.30")
    assert parse_qty("1.5") == 1500 and fmt_qty(1500) == "1.5" and fmt_qty(2000) == "2" and fmt_qty(-1250) == "-1.25"
    assert parse_money("$1,234.50") == 123450 and fmt_money(123450) == "$1,234.50" and fmt_money(-5, "€") == "-€0.05"


@pytest.mark.parametrize("q,u,t", [(1000, 100, 100), (1500, 333, 500), (333, 100, 33), (1, 1, 0), (500, 1, 1), (-1500, 333, -500)])
def test_line_total_rounds_half_up(q, u, t):
    assert line_total(q, u) == t


@pytest.mark.parametrize("bad", ["", "abc", "1e999", "NaN", "Infinity", "__import__('os')"])
def test_bad_numbers_are_refused(bad):
    with pytest.raises(ValueProblem):
        parse_qty(bad)
