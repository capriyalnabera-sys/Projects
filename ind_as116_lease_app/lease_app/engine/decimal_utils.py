"""Decimal helpers.  All financial arithmetic in the engine uses Decimal (never float)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, getcontext

getcontext().prec = 40

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")


def D(value) -> Decimal:
    """Convert anything sensible to Decimal (None / blank -> 0)."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    s = str(value).strip().replace(",", "").replace("₹", "")
    if s == "" or s.lower() in ("nan", "none"):
        return ZERO
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"Not a valid number: {value!r}") from exc


def r2(value) -> Decimal:
    """Round to 2 decimals, half-up (accounting rounding)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_inr(value, decimals: int = 2) -> str:
    """Indian digit grouping: 12,34,56,789.00"""
    v = D(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    neg = v < 0
    s = f"{abs(v):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = whole + ("." + frac if decimals else "")
    return f"-{out}" if neg else out
