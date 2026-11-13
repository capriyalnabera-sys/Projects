"""Ind AS 116 lease calculation engine.

Method (summary - see docs/ACCOUNTING_METHOD.md for detail)
------------------------------------------------------------
* Initial lease liability = PV at the IBR of all lease payments (incl. contractual
  escalations, after rent-free months) from the commencement date.  A payment due on the
  commencement date (advance) has discount factor 1 and is settled immediately.
* Initial ROU = liability + prepaid lease rentals + initial direct costs + restoration
  provision - lease incentives received + other adjustments (+ discount on interest-free
  security deposits, which is a prepaid lease payment).
* Liability: effective-interest method.  Interest accrues continuously on the outstanding
  balance and is split exactly at calendar-month ends and payment dates.
* ROU: straight-line depreciation over the remaining lease term; recomputed prospectively
  whenever the carrying amount changes (modification, additional deposit discount).
* Modification not accounted for as a separate lease (Ind AS 116.44-46): liability is
  remeasured with the revised payments at the revised discount rate.  For a decrease in
  scope (area reduction, term reduction, partial termination) the ROU and liability are
  first reduced proportionately with a gain/loss (46(a)); the remaining remeasurement
  adjusts the ROU (46(b)).
* Full termination: derecognise liability and ROU; difference less termination payment
  to P&L.
* Refundable interest-free deposits (Ind AS 109): initial fair value = PV of the refund at
  the deposit discount rate; the difference is a prepaid lease payment added to the ROU;
  the deposit is unwound to the refund amount by the effective-interest method.

Rounding: all calculations are carried at 40-digit precision.  Monthly balances are
rounded to paise; monthly interest/depreciation/unwinding are the balancing figures so
that every roll-forward ties exactly and the liability/ROU close at exactly zero.
"""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from .dates import TimeBasis, add_months, month_start, next_month_start
from .decimal_utils import D, ONE, ZERO, r2
from .models import DepositMovementInput, LeaseInput, ModificationInput, TerminationInput
from .rent import Payment, TermsVersion, generate_payments

# event priorities at the same instant
P_ARREARS, P_END, P_MONTH, P_INIT, P_MODTERM, P_DEPOSIT, P_ADVANCE = 0, 1, 2, 3, 4, 5, 6

MONTH_FIELDS = [
    "liab_open", "liab_initial", "liab_interest", "liab_payment", "liab_modification",
    "liab_termination", "liab_close",
    "rou_gross_open", "rou_accdep_open", "rou_open", "rou_addition", "rou_mod_gross",
    "rou_mod_accdep", "rou_term_gross", "rou_term_accdep", "rou_depreciation",
    "rou_gross_close", "rou_accdep_close", "rou_close",
    "sd_open", "sd_addition", "sd_unwinding", "sd_refund", "sd_close", "sd_nominal_close",
    "rent_eligible", "rent_non_lease", "rent_gst", "rent_total",
    "liab_current", "liab_non_current",
]


@dataclass
class MonthRow:
    month: date
    values: dict = field(default_factory=lambda: {k: ZERO for k in MONTH_FIELDS})

    def __getattr__(self, item):
        values = self.__dict__.get("values")
        if values is not None and item in values:
            return values[item]
        raise AttributeError(item)


@dataclass
class AccountingEvent:
    event_date: date
    kind: str            # INIT, MODIFICATION, TERMINATION, PARTIAL_TERMINATION, SD_ADDITION, SD_REFUND
    ref: str
    amounts: dict
    description: str = ""
    workings: list = field(default_factory=list)


@dataclass
class LeaseResult:
    lease: LeaseInput
    versions: list
    payments: list                    # all payments of all versions
    effective_payments: list          # payments actually accounted (not superseded)
    months: list                      # list[MonthRow]
    events: list                      # list[AccountingEvent]
    initial_workings: list            # PV table rows
    warnings: list
    summary: dict

    def month(self, m: date) -> Optional[MonthRow]:
        m = month_start(m)
        for row in self.months:
            if row.month == m:
                return row
        return None

    def events_in(self, m: date):
        m = month_start(m)
        return [e for e in self.events if month_start(e.event_date) == m]

    def payments_in(self, m: date):
        m = month_start(m)
        return [p for p in self.effective_payments if month_start(p.due_date) == m]


class _Tranche:
    def __init__(self, ref, d, nominal, rate, refund_date, carry_discounted):
        self.ref, self.date, self.nominal, self.rate = ref, d, D(nominal), D(rate)
        self.refund_date, self.discounted = refund_date, carry_discounted
        self.outstanding = D(nominal)

    def carrying(self, basis: TimeBasis, at: date) -> Decimal:
        if not self.discounted or at >= self.refund_date:
            return self.outstanding
        return self.outstanding / basis.growth(self.rate, self.date, at, self.refund_date)


def build_version0(lease: LeaseInput) -> TermsVersion:
    rf_end = add_months(lease.commencement, lease.rent_free_months) if lease.rent_free_months else None
    return TermsVersion(0, lease.commencement, lease.end_date, D(lease.monthly_rent),
                        list(lease.escalations), lease.frequency_months, lease.timing,
                        D(lease.annual_rate), rf_end, D(lease.gst_rate), D(lease.non_lease_monthly),
                        "Original")


def calculate_lease(lease: LeaseInput, basis: TimeBasis = TimeBasis()) -> LeaseResult:
    warnings: list[str] = []
    v0 = build_version0(lease)
    versions = [v0]
    all_payments: list[Payment] = list(generate_payments(v0))
    effective: list[Payment] = []
    events: list[AccountingEvent] = []

    # ---- change events (modifications and terminations), approved only, in date order
    changes = []
    for m in lease.modifications:
        changes.append(("MOD", m.effective_date, m))
    for t in lease.terminations:
        if t.full:
            changes.append(("TERM", t.effective_date, t))
        else:
            pct = D(t.partial_pct)
            mod = ModificationInput(
                ref=t.ref, effective_date=t.effective_date, mod_type="Partial termination",
                revised_monthly_rent=t.revised_monthly_rent, revised_rate=t.revised_rate,
                area_reduction_pct=pct, keep_existing_escalations=True,
                termination_payment=D(t.termination_payment), is_partial_termination=True)
            changes.append(("MOD", t.effective_date, mod))
    changes.sort(key=lambda c: c[1])
    for kind, d, obj in changes:
        if d <= lease.commencement:
            warnings.append(f"{obj.ref}: effective date must be after commencement - ignored")
    changes = [c for c in changes if c[1] > lease.commencement]

    deposits = sorted(lease.deposits, key=lambda x: (x.movement_date, 0 if x.kind != "Refund" else 1))

    # ---- month range
    last = lease.end_date
    for kind, d, obj in changes:
        if kind == "MOD" and obj.revised_end_date:
            last = max(last, obj.revised_end_date)
    for dm in deposits:
        last = max(last, dm.movement_date)
        if dm.kind != "Refund":
            last = max(last, dm.expected_refund_date or lease.end_date)
    first = min([lease.commencement] + [dm.movement_date for dm in deposits])
    first_month = month_start(first)
    last_month = month_start(last)

    heap = []
    seq = itertools.count()

    def push(instant, prio, kind, payload=None):
        heapq.heappush(heap, (instant, prio, next(seq), kind, payload))

    m = next_month_start(first_month)
    while m <= next_month_start(last_month):
        push(m, P_MONTH, "MONTH", m)
        m = next_month_start(m)
    push(lease.commencement, P_INIT, "INIT")

    def push_payments(v: TermsVersion, from_date: Optional[date] = None):
        for p in generate_payments(v):
            if from_date and p.due_date < from_date:
                continue
            push(p.instant, P_ADVANCE if p.timing == "Advance" else P_ARREARS, "PAY", p)

    push_payments(v0)
    push(v0.end_date + timedelta(days=1), P_END, "END", 0)
    for kind, d, obj in changes:
        push(d, P_MODTERM, kind, obj)
    for dm in deposits:
        push(dm.movement_date, P_DEPOSIT, "DEP", dm)

    # ---- state
    st = {
        "L": ZERO, "NET": ZERO, "G_r": ZERO, "active": False, "ended": False,
        "version": v0, "net_reset": ZERO, "t_reset": ZERO, "t_end": ZERO,
        "pending_prepaid": ZERO, "pay_list": generate_payments(v0),
    }
    tranches: list[_Tranche] = []
    exact = {}       # month -> dict of exact accumulators
    rnd = {}         # month -> dict of rounded event amounts
    snap = {}        # month -> closing exact snapshot

    def bucket(store, month):
        if month not in store:
            store[month] = {k: ZERO for k in MONTH_FIELDS}
        return store[month]

    def reset_dep(now: date):
        v = st["version"]
        st["net_reset"] = st["NET"]
        st["t_reset"] = basis.t(v.anchor, now)
        st["t_end"] = basis.t(v.anchor, v.end_date + timedelta(days=1))

    cur = first
    initial_workings = []

    def accrue(to: date):
        nonlocal cur
        if to <= cur:
            return
        mb = month_start(cur)
        e = bucket(exact, mb)
        v = st["version"]
        if st["active"]:
            g = basis.growth(v.annual_rate, v.anchor, cur, to)
            interest = st["L"] * (g - ONE)
            st["L"] += interest
            e["liab_interest"] += interest
            span = st["t_end"] - st["t_reset"]
            if span > 0:
                dt = basis.t(v.anchor, to) - basis.t(v.anchor, cur)
                dep = st["net_reset"] * dt / span
                dep = min(dep, st["NET"])
                st["NET"] -= dep
                e["rou_depreciation"] += dep
        for tr in tranches:
            if tr.outstanding > 0:
                e["sd_unwinding"] += tr.carrying(basis, to) - tr.carrying(basis, cur)
        cur = to

    def liability_in_12_months(now: date) -> Decimal:
        """Liability 12 months after `now` under the terms in force at `now`
        (used for the current / non-current split; ignores later modifications)."""
        if not st["active"]:
            return ZERO
        v = st["version"]
        horizon = add_months(now, 12)
        bal = st["L"] * basis.growth(v.annual_rate, v.anchor, now, horizon)
        for p in st["pay_list"]:
            if p.instant < now or p.instant > horizon:
                continue
            if p.instant == now and p.timing == "Arrears":
                continue          # already settled before the month-end snapshot
            if p.instant == horizon and p.timing == "Advance":
                continue          # falls due after the 12-month window
            bal -= p.eligible_payment * basis.growth(v.annual_rate, v.anchor, p.instant, horizon)
        return max(ZERO, bal)

    def sd_carrying(at):
        return sum((tr.carrying(basis, at) for tr in tranches), ZERO)

    def sd_nominal():
        return sum((tr.outstanding for tr in tranches), ZERO)

    while heap:
        instant, prio, _, kind, payload = heapq.heappop(heap)
        accrue(instant)

        if kind == "MONTH":
            prev = add_months(payload, -1)
            snap[prev] = {"L": st["L"], "NET": st["NET"], "G_r": st["G_r"],
                          "SD": sd_carrying(instant), "SDN": sd_nominal(),
                          "L12": liability_in_12_months(instant)}
            continue

        if kind == "INIT":
            v = st["version"]
            pv = ZERO
            for p in generate_payments(v):
                t = basis.t(v.anchor, p.instant)
                dfac = basis.discount_factor(v.annual_rate, v.anchor, p.instant)
                pv_p = p.eligible_payment * dfac
                pv += pv_p
                initial_workings.append({
                    "period_no": p.period_no, "period_start": p.period_start, "period_end": p.period_end,
                    "due_date": p.due_date, "monthly_rent": p.revised_rent, "payment": p.eligible_payment,
                    "t_months": t, "discount_factor": dfac, "present_value": pv_p})
            L0 = pv
            others = (D(lease.prepaid) + D(lease.idc) + D(lease.restoration) - D(lease.incentives)
                      + D(lease.other_adj) + st["pending_prepaid"])
            st["L"] = L0
            st["NET"] = L0 + others
            st["active"] = True
            reset_dep(instant)
            L0_r = r2(L0)
            rou_r = L0_r + others
            st["G_r"] = rou_r
            mb = month_start(instant)
            bucket(exact, mb)["liab_initial"] += L0
            rb = bucket(rnd, mb)
            rb["liab_initial"] += L0_r
            rb["rou_addition"] += rou_r
            events.append(AccountingEvent(instant, "INIT", lease.lease_id, {
                "rou": rou_r, "liability": L0_r, "prepaid": D(lease.prepaid) + st["pending_prepaid"],
                "idc": D(lease.idc), "incentives": D(lease.incentives),
                "restoration": D(lease.restoration), "other_adj": D(lease.other_adj),
                "pv_exact": L0}, "Initial recognition of ROU asset and lease liability",
                initial_workings))
            st["pending_prepaid"] = ZERO
            continue

        if kind == "END":
            if payload != st["version"].version_no or not st["active"]:
                continue
            mb = month_start(instant - timedelta(days=1))
            e = bucket(exact, mb)
            e["liab_interest"] -= st["L"]       # remove sub-paisa residual
            st["L"] = ZERO
            e["rou_depreciation"] += st["NET"]
            st["NET"] = ZERO
            st["active"] = False
            st["ended"] = True
            continue

        if kind == "PAY":
            p: Payment = payload
            if not st["active"] or p.version_no != st["version"].version_no:
                continue
            st["L"] -= p.eligible_payment
            effective.append(p)
            mb = month_start(p.due_date)
            rb = bucket(rnd, mb)
            rb["liab_payment"] += p.eligible_payment
            rb["rent_eligible"] += p.eligible_payment
            rb["rent_non_lease"] += p.non_lease
            rb["rent_gst"] += p.gst
            rb["rent_total"] += p.total_payable
            continue

        if kind == "DEP":
            dm: DepositMovementInput = payload
            mb = month_start(instant)
            rb = bucket(rnd, mb)
            if dm.kind == "Refund":
                remaining = D(dm.amount)
                carry_r_total = ZERO
                if remaining > sd_nominal() + D("0.005"):
                    warnings.append(f"{dm.ref}: refund {remaining} exceeds deposit balance {sd_nominal()}")
                for tr in tranches:
                    if remaining <= 0:
                        break
                    if tr.outstanding <= 0:
                        continue
                    take = min(remaining, tr.outstanding)
                    share = tr.carrying(basis, instant) * take / tr.outstanding
                    tr.outstanding -= take
                    remaining -= take
                    carry_r_total += share
                carry_r = r2(carry_r_total)
                refunded = D(dm.amount) - remaining
                rb["sd_refund"] += carry_r
                events.append(AccountingEvent(instant, "SD_REFUND", dm.ref, {
                    "cash": refunded, "carrying": carry_r, "difference": refunded - carry_r},
                    "Security deposit refund"))
                continue
            nominal = D(dm.amount)
            if not dm.refundable:
                # non-refundable deposit = lease payment -> ROU
                if st["active"]:
                    st["NET"] += nominal
                    st["G_r"] += nominal
                    rb["rou_addition"] += nominal
                    reset_dep(instant)
                else:
                    st["pending_prepaid"] += nominal
                events.append(AccountingEvent(instant, "SD_ADDITION", dm.ref, {
                    "cash": nominal, "fair_value": ZERO, "rou": nominal if st["active"] else ZERO,
                    "prepaid": ZERO if st["active"] else nominal, "pnl": ZERO},
                    "Non-refundable deposit treated as lease payment"))
                continue
            rate = D(dm.annual_rate if dm.annual_rate not in (None, "") else lease.annual_rate)
            refund_date = dm.expected_refund_date or st["version"].end_date
            discounted = bool(dm.interest_free) and refund_date > instant and rate > 0
            tr = _Tranche(dm.ref, instant, nominal, rate, refund_date, discounted)
            fv = tr.carrying(basis, instant)
            fv_r = r2(fv)
            diff = nominal - fv_r
            tranches.append(tr)
            rb["sd_addition"] += fv_r
            # sub-paisa rounding of fair value goes to unwinding of this month
            bucket(exact, mb)["sd_unwinding"] -= (fv - fv_r)
            amounts = {"cash": nominal, "fair_value": fv_r, "rou": ZERO, "prepaid": ZERO, "pnl": ZERO,
                       "rate": rate, "refund_date": refund_date}
            if diff:
                if st["active"]:
                    st["NET"] += diff
                    st["G_r"] += diff
                    rb["rou_addition"] += diff
                    reset_dep(instant)
                    amounts["rou"] = diff
                elif not st["ended"] and instant < lease.commencement:
                    st["pending_prepaid"] += diff
                    amounts["prepaid"] = diff
                else:
                    amounts["pnl"] = diff
            events.append(AccountingEvent(instant, "SD_ADDITION", dm.ref, amounts,
                                          f"Security deposit ({dm.kind.lower()})"))
            continue

        if kind == "TERM":
            t: TerminationInput = payload
            if not st["active"]:
                warnings.append(f"{t.ref}: lease not active on termination date - ignored")
                continue
            L_b, NET_b, G_r = st["L"], st["NET"], st["G_r"]
            L_r = r2(L_b)
            A_r = G_r - r2(NET_b)
            X = D(t.termination_payment)
            gain_r = L_r - (G_r - A_r) - X
            mb = month_start(instant)
            e = bucket(exact, mb)
            e["liab_termination"] -= L_b
            rb = bucket(rnd, mb)
            rb["liab_termination"] -= L_r
            rb["rou_term_gross"] -= G_r
            rb["rou_term_accdep"] -= A_r
            events.append(AccountingEvent(instant, "TERMINATION", t.ref, {
                "liability": L_r, "rou_gross": G_r, "rou_accdep": A_r, "rou_net": G_r - A_r,
                "termination_payment": X, "gain_loss": gain_r},
                "Full termination - derecognition of ROU asset and lease liability"))
            st.update(L=ZERO, NET=ZERO, G_r=ZERO, active=False, ended=True)
            st["version"] = TermsVersion(-1, instant, instant, ZERO, [], 1, "Advance", ZERO, label="Terminated")
            continue

        if kind == "MOD":
            mod: ModificationInput = payload
            if not st["active"]:
                warnings.append(f"{mod.ref}: lease not active on modification date - ignored")
                continue
            old = st["version"]
            if mod.separate_lease:
                events.append(AccountingEvent(instant, "MODIFICATION", mod.ref, {
                    "liability_before": r2(st["L"]), "liability_after": r2(st["L"]),
                    "liability_change": ZERO, "rou_gross_change": ZERO, "rou_accdep_change": ZERO,
                    "gain_loss": ZERO, "separate_lease": True},
                    "Accounted for as a separate lease - record the additional scope as a new lease"))
                continue
            D_ = instant
            base = D(mod.revised_monthly_rent) if mod.revised_monthly_rent not in (None, "") else None
            if base is None:
                base = old.rent_at(D_)
                if mod.is_partial_termination:
                    base = r2(base * (1 - D(mod.area_reduction_pct) / 100))
            if mod.keep_existing_escalations:
                rules = list(old.rules) + list(mod.revised_escalations)
            else:
                rules = list(mod.revised_escalations)
            new_end = mod.revised_end_date or old.end_date
            nv = TermsVersion(
                old.version_no + 1, D_, new_end, base, rules,
                mod.revised_frequency_months or old.frequency_months,
                mod.revised_timing or old.timing,
                D(mod.revised_rate) if mod.revised_rate not in (None, "") else old.annual_rate,
                old.rent_free_end if (old.rent_free_end and old.rent_free_end > D_) else None,
                old.gst_rate, old.non_lease_monthly, f"Modified ({mod.ref})")
            new_pay = generate_payments(nv)
            L_new = ZERO
            workings = []
            for p in new_pay:
                dfac = basis.discount_factor(nv.annual_rate, nv.anchor, p.instant)
                L_new += p.eligible_payment * dfac
                workings.append({"period_no": p.period_no, "period_start": p.period_start,
                                 "period_end": p.period_end, "due_date": p.due_date,
                                 "monthly_rent": p.revised_rent, "payment": p.eligible_payment,
                                 "t_months": basis.t(nv.anchor, p.instant), "discount_factor": dfac,
                                 "present_value": p.eligible_payment * dfac})
            # proportion of decrease in scope
            f_area = D(mod.area_reduction_pct) / 100
            f_term = ZERO
            if new_end < old.end_date:
                old_rem = D((old.end_date + timedelta(days=1) - D_).days)
                new_rem = D((new_end + timedelta(days=1) - D_).days)
                f_term = ONE - new_rem / old_rem
            f = ONE - (ONE - f_area) * (ONE - f_term)
            L_b, NET_b, G_r = st["L"], st["NET"], st["G_r"]
            A_r = G_r - r2(NET_b)
            rou_dec = f * NET_b
            L_dec = f * L_b
            adj = L_new - (L_b - L_dec)
            NET_after = NET_b - rou_dec + adj
            if NET_after < 0:
                adj -= NET_after
                NET_after = ZERO
            gross_dec_r = r2(f * G_r)
            accdep_dec_r = r2(f * A_r)
            adj_r = r2(adj)
            dL_r = r2(L_new - L_b)
            d_net_r = -(gross_dec_r - accdep_dec_r) + adj_r
            X = D(mod.termination_payment)
            gain_r = d_net_r - dL_r - X
            mb = month_start(instant)
            e = bucket(exact, mb)
            e["liab_modification"] += L_new - L_b
            rb = bucket(rnd, mb)
            rb["liab_modification"] += dL_r
            rb["rou_mod_gross"] += -gross_dec_r + adj_r
            rb["rou_mod_accdep"] += -accdep_dec_r
            kind_label = "PARTIAL_TERMINATION" if mod.is_partial_termination else "MODIFICATION"
            events.append(AccountingEvent(instant, kind_label, mod.ref, {
                "liability_before": r2(L_b), "liability_after": r2(L_new), "liability_change": dL_r,
                "rou_before": r2(NET_b), "rou_after": r2(NET_b) + d_net_r,
                "scope_decrease_pct": r2(f * 100),
                "rou_gross_decrease": gross_dec_r, "rou_accdep_decrease": accdep_dec_r,
                "rou_remeasurement": adj_r, "rou_gross_change": -gross_dec_r + adj_r,
                "rou_accdep_change": -accdep_dec_r, "termination_payment": X, "gain_loss": gain_r,
                "revised_rate": nv.annual_rate, "revised_end_date": new_end, "revised_rent": base},
                ("Partial termination (decrease in scope)" if mod.is_partial_termination
                 else f"Lease modification - {mod.mod_type}"), workings))
            st["L"] = L_new
            st["NET"] = NET_after
            st["G_r"] = G_r - gross_dec_r + adj_r
            st["version"] = nv
            st["pay_list"] = new_pay
            versions.append(nv)
            all_payments.extend(new_pay)
            reset_dep(D_)
            push_payments(nv)
            push(new_end + timedelta(days=1), P_END, "END", nv.version_no)
            # deposits whose refund was expected at old end keep their original estimate
            continue

    # ---- build rounded monthly rows
    months: list[MonthRow] = []
    prev = None
    month_list = []
    m = first_month
    while m <= last_month:
        month_list.append(m)
        m = next_month_start(m)
    for m in month_list:
        row = MonthRow(m)
        v = row.values
        s = snap.get(m)
        rb = rnd.get(m, {k: ZERO for k in MONTH_FIELDS})
        if prev is None:
            for k in ("liab_open", "rou_gross_open", "rou_accdep_open", "sd_open"):
                v[k] = ZERO
        else:
            v["liab_open"] = prev.values["liab_close"]
            v["rou_gross_open"] = prev.values["rou_gross_close"]
            v["rou_accdep_open"] = prev.values["rou_accdep_close"]
            v["sd_open"] = prev.values["sd_close"]
        v["rou_open"] = v["rou_gross_open"] - v["rou_accdep_open"]
        for k in ("liab_initial", "liab_payment", "liab_modification", "liab_termination",
                  "rou_addition", "rou_mod_gross", "rou_mod_accdep", "rou_term_gross", "rou_term_accdep",
                  "sd_addition", "sd_refund", "rent_eligible", "rent_non_lease", "rent_gst", "rent_total"):
            v[k] = rb[k]
        v["liab_close"] = r2(s["L"])
        v["liab_interest"] = (v["liab_close"] - v["liab_open"] - v["liab_initial"] + v["liab_payment"]
                              - v["liab_modification"] - v["liab_termination"])
        v["rou_gross_close"] = s["G_r"]
        v["rou_close"] = r2(s["NET"])
        v["rou_accdep_close"] = v["rou_gross_close"] - v["rou_close"]
        v["rou_depreciation"] = (v["rou_accdep_close"] - v["rou_accdep_open"]
                                 - v["rou_mod_accdep"] - v["rou_term_accdep"])
        v["sd_close"] = r2(s["SD"])
        v["sd_nominal_close"] = r2(s["SDN"])
        v["sd_unwinding"] = v["sd_close"] - v["sd_open"] - v["sd_addition"] + v["sd_refund"]
        months.append(row)
        prev = row

    # current / non-current split: principal falling due within 12 months
    for row in months:
        later = r2(snap[row.month]["L12"])
        cur_part = max(ZERO, row.values["liab_close"] - later)
        row.values["liab_current"] = min(cur_part, row.values["liab_close"])
        row.values["liab_non_current"] = row.values["liab_close"] - row.values["liab_current"]

    init = next((e for e in events if e.kind == "INIT"), None)
    total_rent = sum((p.eligible_payment for p in effective), ZERO)
    summary = {
        "initial_liability": init.amounts["liability"] if init else ZERO,
        "initial_rou": init.amounts["rou"] if init else ZERO,
        "total_lease_payments": total_rent,
        "total_interest": sum((r.values["liab_interest"] for r in months), ZERO),
        "total_depreciation": sum((r.values["rou_depreciation"] for r in months), ZERO),
        "lease_term_months": basis.t(v0.anchor, v0.end_date + timedelta(days=1)),
        "monthly_rate": basis.monthly_rate(lease.annual_rate),
    }
    return LeaseResult(lease, versions, all_payments, effective, months, events, initial_workings,
                       warnings, summary)
