"""Rent escalation expansion and payment-schedule generation.

Escalation rules
----------------
Each rule in the Rent Escalation Register has an effective date, a type (Percentage /
Absolute Amount) and a frequency in months (0 = one-time).  A recurring rule repeats
from its effective date every *frequency* months until the next rule's effective date
(or lease end).  Rules are applied in date order on the rent then in force, so
percentage and absolute escalations can be freely mixed.

An escalation applies from the first lease month that starts on or after its effective
date (escalation dates should normally coincide with a lease-month start).

Payment periods
---------------
Lease months are anchored on the commencement (or modification) date.  Payments are
grouped into periods of 1 / 3 / 6 / 12 months.  The periodic payment is the sum of the
monthly rents in that period (so an escalation inside a quarter is handled correctly).
Rent-free months carry zero rent.  A final broken month is pro-rated on days.

Due dates: Advance = first day of the period; Arrears = last day of the period.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from .dates import add_months
from .decimal_utils import D, ZERO, r2


@dataclass
class RentStep:
    step_date: date
    esc_type: str
    pct: Decimal
    amount: Decimal
    existing_rent: Decimal
    revised_rent: Decimal
    next_date: Optional[date]
    frequency_months: int
    remarks: str = ""
    agreement_ref: str = ""


def expand_steps(rules, base_rent: Decimal, after: date, end: date) -> list[RentStep]:
    """Turn escalation rules into dated rent steps strictly after `after` and on/before `end`."""
    rules = sorted(rules, key=lambda r: r.effective_date)
    dated = []
    for i, rule in enumerate(rules):
        stop = rules[i + 1].effective_date if i + 1 < len(rules) else None
        k = 0
        while True:
            d = add_months(rule.effective_date, k * rule.frequency_months) if k else rule.effective_date
            if d > end or (stop is not None and d >= stop):
                break
            dated.append((d, rule))
            if rule.frequency_months <= 0:
                break
            k += 1
    steps: list[RentStep] = []
    rent = D(base_rent)
    for d, rule in dated:
        if d <= after:
            continue
        if rule.esc_type.lower().startswith("p"):
            revised = r2(rent * (1 + D(rule.pct) / 100))
        else:
            revised = r2(rent + D(rule.amount))
        steps.append(RentStep(d, rule.esc_type, D(rule.pct), D(rule.amount), rent, revised, None,
                              rule.frequency_months, rule.remarks, rule.agreement_ref))
        rent = revised
    for i in range(len(steps) - 1):
        steps[i].next_date = steps[i + 1].step_date
    return steps


@dataclass
class TermsVersion:
    """One set of contractual terms: the original lease or a modified version."""
    version_no: int
    anchor: date                     # commencement or modification effective date
    end_date: date                   # lease end (inclusive)
    base_rent: Decimal               # monthly rent in force at anchor
    rules: list                      # escalation rules
    frequency_months: int
    timing: str
    annual_rate: Decimal
    rent_free_end: Optional[date] = None
    gst_rate: Decimal = ZERO
    non_lease_monthly: Decimal = ZERO
    label: str = "Original"
    steps: list = field(default_factory=list)

    def __post_init__(self):
        self.steps = expand_steps(self.rules, self.base_rent, self.anchor, self.end_date)

    def rent_at(self, d: date) -> Decimal:
        """Contractual monthly rent (ignoring rent-free) for a lease month starting on d."""
        rent = D(self.base_rent)
        for s in self.steps:
            if s.step_date <= d:
                rent = s.revised_rent
            else:
                break
        return rent


@dataclass
class Payment:
    version_no: int
    period_no: int
    period_start: date
    period_end: date
    due_date: date
    timing: str
    opening_rent: Decimal            # monthly rent before this period
    revised_rent: Decimal            # monthly rent in the first month of this period
    escalation_amount: Decimal
    months: int
    rent_free_months: int
    eligible_payment: Decimal        # lease payment included in the liability
    non_lease: Decimal
    gst: Decimal
    version_label: str = ""

    @property
    def total_payable(self) -> Decimal:
        return self.eligible_payment + self.non_lease + self.gst

    @property
    def instant(self) -> date:
        """Point in time at which the payment reduces the liability (start of day)."""
        return self.due_date if self.timing == "Advance" else self.due_date + timedelta(days=1)


def generate_payments(v: TermsVersion) -> list[Payment]:
    months = []  # (month_start, rent, rent_free_flag, fraction_flag)
    j = 0
    while True:
        ms = add_months(v.anchor, j)
        if ms > v.end_date:
            break
        nxt = add_months(v.anchor, j + 1)
        contractual = v.rent_at(ms)
        free = v.rent_free_end is not None and ms < v.rent_free_end
        if nxt - timedelta(days=1) <= v.end_date:
            frac = D(1)
        else:
            frac = D((v.end_date - ms).days + 1) / D((nxt - ms).days)
        rent = ZERO if free else r2(contractual * frac)
        nl = r2(D(v.non_lease_monthly) * frac)
        months.append((ms, contractual, rent, free, nl))
        j += 1

    payments = []
    f = max(1, int(v.frequency_months))
    prev_rent = D(v.base_rent)
    for p, k in enumerate(range(0, len(months), f)):
        chunk = months[k:k + f]
        start = chunk[0][0]
        end = min(add_months(v.anchor, k + f) - timedelta(days=1), v.end_date)
        eligible = sum((c[2] for c in chunk), ZERO)
        nl = sum((c[4] for c in chunk), ZERO)
        gst = r2((eligible + nl) * D(v.gst_rate) / 100)
        revised = chunk[0][1]
        due = start if v.timing == "Advance" else end
        payments.append(Payment(v.version_no, p + 1, start, end, due, v.timing, prev_rent, revised,
                                revised - prev_rent, len(chunk), sum(1 for c in chunk if c[3]),
                                eligible, nl, gst, v.label))
        prev_rent = chunk[-1][1]
    return payments
