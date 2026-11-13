"""Date helpers and the time basis used for discounting, interest and depreciation.

The engine measures time in *months* from an anchor date (commencement or modification
date).  Two conventions are supported (Settings > Accounting configuration):

* ``monthly``    - whole lease months from the anchor, plus the elapsed fraction of the
                   current lease month (days / days in that lease month).  A full calendar
                   month for a lease starting on the 1st is exactly 1.0 month, so interest
                   and depreciation are equal for every full month.
* ``actual_365`` - days / 365 x 12 (identical to Excel XNPV / XIRR conventions).

Monthly interest rate:

* ``effective`` - (1 + IBR) ^ (1/12) - 1  (IBR is an effective annual rate)
* ``nominal``   - IBR / 12
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .decimal_utils import D, ONE, ZERO


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month_start(d: date) -> date:
    return add_months(d.replace(day=1), 1)


def month_end(d: date) -> date:
    return next_month_start(d) - timedelta(days=1)


def ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label(d: date) -> str:
    return d.strftime("%b-%Y")


def financial_year(d: date, fy_start_month: int = 4) -> str:
    start = d.year if d.month >= fy_start_month else d.year - 1
    return f"FY {start}-{str(start + 1)[-2:]}"


def whole_months(anchor: date, d: date) -> int:
    """Largest k such that add_months(anchor, k) <= d."""
    k = (d.year - anchor.year) * 12 + (d.month - anchor.month)
    while add_months(anchor, k) > d:
        k -= 1
    while add_months(anchor, k + 1) <= d:
        k += 1
    return k


def month_range(first: date, last: date):
    """Yield the first day of every calendar month from first to last (inclusive)."""
    cur = month_start(first)
    while cur <= last:
        yield cur
        cur = next_month_start(cur)


@dataclass(frozen=True)
class TimeBasis:
    time_basis: str = "monthly"      # monthly | actual_365
    rate_basis: str = "effective"    # effective | nominal

    def monthly_rate(self, annual_rate_pct: Decimal) -> Decimal:
        r = D(annual_rate_pct) / 100
        if self.rate_basis == "nominal":
            return r / 12
        return (ONE + r) ** (ONE / 12) - ONE

    def t(self, anchor: date, d: date) -> Decimal:
        """Time in months from anchor to the start of day d."""
        if self.time_basis == "actual_365":
            return D((d - anchor).days) * 12 / D(365)
        if d >= anchor:
            k = whole_months(anchor, d)
            s, e = add_months(anchor, k), add_months(anchor, k + 1)
            return D(k) + D((d - s).days) / D((e - s).days)
        # before anchor (e.g. deposit paid before commencement)
        k = -whole_months(d, anchor)
        s = add_months(anchor, k)
        if s == d:
            return D(k)
        k -= 1
        s, e = add_months(anchor, k), add_months(anchor, k + 1)
        return D(k) + D((d - s).days) / D((e - s).days)

    def growth(self, annual_rate_pct: Decimal, anchor: date, d1: date, d2: date) -> Decimal:
        """Compounding factor (1+i)^(t(d2)-t(d1))."""
        dt = self.t(anchor, d2) - self.t(anchor, d1)
        if dt == ZERO:
            return ONE
        return (ONE + self.monthly_rate(annual_rate_pct)) ** dt

    def discount_factor(self, annual_rate_pct: Decimal, anchor: date, d: date) -> Decimal:
        return ONE / self.growth(annual_rate_pct, anchor, anchor, d)
