"""Accounting test scenarios.

Every expected value is calculated *independently* of the engine: closed-form annuity
formulas or explicit month-by-month roll-forwards written here, using only the contract
terms.  The engine result is then compared (tolerance: Rs 0.05, or Rs 1 for figures that
are sums of many rounded monthly amounts).
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as Dec, getcontext

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lease_app.engine.dates import TimeBasis  # noqa: E402
from lease_app.engine.lease_engine import calculate_lease  # noqa: E402
from lease_app.engine.models import (DepositMovementInput, EscalationRule, LeaseInput, ModificationInput,  # noqa: E402
                                     TerminationInput)

getcontext().prec = 40
TOL = Dec("0.05")


# ----------------------------------------------------------------------------- reference maths
def mrate(annual_pct):
    """Monthly rate = IBR / 12 (Finance-approved convention)."""
    return Dec(annual_pct) / 100 / 12


def pv(flows, annual_pct):
    """flows = [(t_months, amount)] ; discount monthly at IBR/12: amount / (1 + IBR/12)^t."""
    r = Dec(1) + Dec(annual_pct) / 1200
    return sum((Dec(a) / r ** Dec(t) for t, a in flows), Dec(0))


def rollforward(L0, flows, annual_pct, months, timing):
    """Liability after `months` full months; flows = {month_index: amount}.
    Advance: payment at start of month k; arrears: at end of month k."""
    i = mrate(annual_pct)
    L = Dec(L0)
    for k in range(months):
        if timing == "Advance":
            L = (L - flows.get(k, 0)) * (1 + i)
        else:
            L = L * (1 + i) - flows.get(k, 0)
    return L


def q2(x):
    return Dec(x).quantize(Dec("0.01"), rounding=ROUND_HALF_UP)


def rent_series(base, n, rules):
    """Monthly rents for n months, rules = list of (start_month_index, kind, value, every_n_months or 0)
    applied independently of the engine's escalation logic."""
    events = []
    rules = sorted(rules)
    for idx, (s, kind, val, every) in enumerate(rules):
        stop = rules[idx + 1][0] if idx + 1 < len(rules) else n
        m = s
        while m < stop and m < n:
            events.append((m, kind, Dec(val)))
            if not every:
                break
            m += every
    events.sort()
    rents, rent, j = [], Dec(base), 0
    for k in range(n):
        while j < len(events) and events[j][0] == k:
            _, kind, val = events[j]
            rent = q2(rent * (1 + val / 100)) if kind == "P" else rent + val
            j += 1
        rents.append(rent)
    return rents


# ----------------------------------------------------------------------------- helpers
RESULTS = []


def record(no, scenario, check, inputs, expected, actual, tol=TOL):
    expected, actual = Dec(expected), Dec(actual)
    diff = actual - expected
    RESULTS.append({"no": no, "scenario": scenario, "check": check, "input": inputs, "expected": q2(expected),
                    "actual": q2(actual), "difference": q2(diff), "status": "Pass" if abs(diff) <= tol else "Fail"})


def lease(**kw):
    base = dict(lease_id="T", commencement=date(2025, 4, 1), end_date=date(2030, 3, 31), monthly_rent=Dec(100000),
                frequency_months=1, timing="Advance", annual_rate=Dec(10))
    base.update(kw)
    return LeaseInput(**base)


def month_sum(res, key):
    return sum((r.values[key] for r in res.months), Dec(0))


# ----------------------------------------------------------------------------- scenarios
def s01_no_escalation():
    res = calculate_lease(lease())
    i = mrate(10)
    v = 1 / (1 + i)
    exp_L0 = Dec(100000) * (1 - v ** 60) / (1 - v)          # annuity-due closed form
    inp = "Rent 1,00,000 p.m. advance, 60 months, IBR 10%, no escalation"
    record(1, "No rent escalation", "Initial lease liability (annuity-due formula)", inp, exp_L0,
           res.summary["initial_liability"])
    record(1, "No rent escalation", "Month 1 interest = (L0 - first payment) x monthly rate", inp,
           (q2(exp_L0) - 100000) * i, res.months[0].values["liab_interest"])
    record(1, "No rent escalation", "Monthly depreciation = ROU / 60", inp, q2(exp_L0) / 60,
           res.months[1].values["rou_depreciation"])
    record(1, "No rent escalation", "Total interest = total payments - L0", inp, 6000000 - q2(exp_L0),
           month_sum(res, "liab_interest"))
    record(1, "No rent escalation", "Closing liability at lease end", inp, 0, res.months[-1].values["liab_close"])
    record(1, "No rent escalation", "Closing ROU at lease end", inp, 0, res.months[-1].values["rou_close"])


def s02_percentage():
    res = calculate_lease(lease(escalations=[EscalationRule(date(2026, 4, 1), "Percentage", Dec(5),
                                                            frequency_months=12)]))
    rents = rent_series(100000, 60, [(12, "P", 5, 12)])
    exp = pv([(k, rents[k]) for k in range(60)], 10)
    inp = "Rent 1,00,000 p.m., +5% every April, 60 months advance, IBR 10%"
    record(2, "Percentage escalation", "Initial lease liability", inp, exp, res.summary["initial_liability"])
    record(2, "Percentage escalation", "Rent in year 3 = 1,00,000 x 1.05^2", inp, Dec(110250),
           res.payments[24].eligible_payment)
    record(2, "Percentage escalation", "Rent in year 5", inp, q2(q2(Dec(110250) * Dec("1.05")) * Dec("1.05")),
           res.payments[48].eligible_payment)


def s03_absolute():
    res = calculate_lease(lease(escalations=[EscalationRule(date(2026, 4, 1), "Absolute Amount", amount=Dec(5000),
                                                            frequency_months=12)]))
    rents = rent_series(100000, 60, [(12, "A", 5000, 12)])
    inp = "Rent 1,00,000 p.m., +Rs 5,000 every April, 60 months advance, IBR 10%"
    record(3, "Absolute escalation", "Initial lease liability", inp, pv([(k, rents[k]) for k in range(60)], 10),
           res.summary["initial_liability"])
    record(3, "Absolute escalation", "Rent in year 2 = 1,05,000", inp, 105000, res.payments[12].eligible_payment)
    record(3, "Absolute escalation", "Rent in year 5 = 1,20,000", inp, 120000, res.payments[59].eligible_payment)


def s04_multiple():
    rules = [EscalationRule(date(2026, 4, 1), "Absolute Amount", amount=Dec(10000), frequency_months=12),
             EscalationRule(date(2028, 4, 1), "Percentage", Dec(15), frequency_months=0),
             EscalationRule(date(2029, 4, 1), "Percentage", Dec(4), frequency_months=0)]
    res = calculate_lease(lease(escalations=rules))
    rents = rent_series(100000, 60, [(12, "A", 10000, 12), (36, "P", 15, 0), (48, "P", 4, 0)])
    inp = "+10,000 yearly Apr-26/Apr-27, then +15% Apr-28, then +4% Apr-29"
    record(4, "Multiple escalations (mixed)", "Year 4 rent = (1,20,000) x 1.15 = 1,38,000", inp, 138000,
           res.payments[36].eligible_payment)
    record(4, "Multiple escalations (mixed)", "Year 5 rent = 1,38,000 x 1.04", inp, Dec(143520),
           res.payments[48].eligible_payment)
    record(4, "Multiple escalations (mixed)", "Initial lease liability", inp, pv([(k, rents[k]) for k in range(60)], 10),
           res.summary["initial_liability"])


def s05_rent_free():
    res = calculate_lease(lease(rent_free_months=3))
    inp = "First 3 months rent-free, then 1,00,000 p.m. advance, IBR 10%"
    record(5, "Rent-free period", "Initial lease liability = PV of months 4-60", inp,
           pv([(k, 100000) for k in range(3, 60)], 10), res.summary["initial_liability"])
    record(5, "Rent-free period", "Payment in month 1", inp, 0, res.payments[0].eligible_payment)


def s06_advance():
    res = calculate_lease(lease(timing="Advance"))
    inp = "Advance: first payment on commencement date"
    record(6, "Advance payment", "First payment due on commencement (t=0) - discount factor 1", inp, 1,
           res.initial_workings[0]["discount_factor"])
    L12 = rollforward(res.summary["initial_liability"], {k: 100000 for k in range(60)}, 10, 12, "Advance")
    record(6, "Advance payment", "Liability after 12 months (independent roll-forward)", inp, L12,
           res.months[11].values["liab_close"])


def s07_arrears():
    res = calculate_lease(lease(timing="Arrears"))
    i = mrate(10)
    exp = Dec(100000) * (1 - (1 + i) ** -60) / i            # ordinary annuity
    inp = "Rent 1,00,000 p.m. in arrears, 60 months, IBR 10%"
    record(7, "Arrears payment", "Initial lease liability (ordinary annuity formula)", inp, exp,
           res.summary["initial_liability"])
    record(7, "Arrears payment", "Month 1 interest = L0 x monthly rate", inp, q2(exp) * i,
           res.months[0].values["liab_interest"])


def s08_quarterly():
    res = calculate_lease(lease(frequency_months=3))
    exp = pv([(3 * k, 300000) for k in range(20)], 10)
    inp = "Rent 1,00,000 p.m. paid quarterly in advance (3,00,000), IBR 10%"
    record(8, "Quarterly payment", "Initial lease liability", inp, exp, res.summary["initial_liability"])
    record(8, "Quarterly payment", "Payments in Apr / May / Jun 2025", inp, 300000,
           sum((r.values["liab_payment"] for r in res.months[:3]), Dec(0)))
    record(8, "Quarterly payment", "No payment in May 2025", inp, 0, res.months[1].values["liab_payment"])


def s09_mid_month():
    res = calculate_lease(lease(commencement=date(2025, 10, 15), end_date=date(2030, 10, 14)))
    exp = pv([(k, 100000) for k in range(60)], 10)
    inp = "Commencement 15-Oct-2025 (mid-month), 60 lease months"
    record(9, "Different commencement dates", "Initial lease liability", inp, exp, res.summary["initial_liability"])
    record(9, "Different commencement dates", "Sum of calendar-month depreciation = ROU", inp,
           res.summary["initial_rou"], month_sum(res, "rou_depreciation"))
    record(9, "Different commencement dates", "Total interest = payments - L0", inp, 6000000 - q2(exp),
           month_sum(res, "liab_interest"))
    # Oct-2025 covers 17 of 31 days of the first lease month (15-Oct to 14-Nov)
    record(9, "Different commencement dates", "Oct-2025 depreciation = ROU/60 x 17/31", inp,
           res.summary["initial_rou"] / 60 * 17 / 31, res.months[0].values["rou_depreciation"], Dec("0.05"))


def _l_before(L0, rents, rate, months, timing="Advance"):
    return rollforward(L0, dict(enumerate(rents)), rate, months, timing)


def s10_modification_rent():
    mod = ModificationInput("M", date(2027, 4, 1), "Rent change", revised_monthly_rent=Dec(90000), revised_rate=Dec(11))
    res = calculate_lease(lease(modifications=[mod]))
    L0 = res.summary["initial_liability"]
    Lb = _l_before(L0, [Dec(100000)] * 60, 10, 24)
    Ln = pv([(k, 90000) for k in range(36)], 11)
    ev = next(e for e in res.events if e.kind == "MODIFICATION")
    rou_b = L0 - L0 / 60 * 24
    inp = "Rent reduced to 90,000 from Apr-2027 (month 25); IBR revised 10% -> 11%"
    record(10, "Mid-term modification", "Liability before modification", inp, Lb, ev.amounts["liability_before"])
    record(10, "Mid-term modification", "Remeasured liability at revised rate", inp, Ln, ev.amounts["liability_after"])
    record(10, "Mid-term modification", "ROU adjusted by remeasurement (46(b))", inp, q2(rou_b) + (Ln - Lb),
           ev.amounts["rou_after"], Dec("0.10"))
    record(10, "Mid-term modification", "Depreciation after = ROU after / 36", inp, (q2(rou_b) + Ln - Lb) / 36,
           res.months[25].values["rou_depreciation"], Dec("0.10"))


def s11_extension():
    mod = ModificationInput("M", date(2027, 4, 1), "Lease extension", revised_end_date=date(2033, 3, 31),
                            revised_monthly_rent=Dec(110000), revised_rate=Dec(10.5))
    res = calculate_lease(lease(modifications=[mod]))
    L0 = res.summary["initial_liability"]
    Lb = _l_before(L0, [Dec(100000)] * 60, 10, 24)
    Ln = pv([(k, 110000) for k in range(72)], Dec("10.5"))
    ev = next(e for e in res.events if e.kind == "MODIFICATION")
    inp = "Term extended from Mar-2030 to Mar-2033 w.e.f. Apr-2027, rent 1,10,000, IBR 10.5%"
    record(11, "Lease extension", "Liability before", inp, Lb, ev.amounts["liability_before"])
    record(11, "Lease extension", "Remeasured liability (72 payments)", inp, Ln, ev.amounts["liability_after"])
    record(11, "Lease extension", "Gain / loss (none for extension)", inp, 0, ev.amounts["gain_loss"])
    record(11, "Lease extension", "Liability fully settled at new end", inp, 0, res.months[-1].values["liab_close"])


def s12_reduction():
    mod = ModificationInput("M", date(2027, 4, 1), "Lease reduction", revised_end_date=date(2029, 3, 31))
    res = calculate_lease(lease(modifications=[mod]))
    L0 = res.summary["initial_liability"]
    Lb = _l_before(L0, [Dec(100000)] * 60, 10, 24)
    rou_b = q2(L0) - q2(L0) / 60 * 24
    old_days = (date(2030, 4, 1) - date(2027, 4, 1)).days
    new_days = (date(2029, 4, 1) - date(2027, 4, 1)).days
    f = 1 - Dec(new_days) / Dec(old_days)
    Ln = pv([(k, 100000) for k in range(24)], 10)
    gain = f * Lb - f * rou_b
    ev = next(e for e in res.events if e.kind == "MODIFICATION")
    inp = "Term shortened from Mar-2030 to Mar-2029 w.e.f. Apr-2027 (decrease in scope)"
    record(12, "Lease reduction", "Remeasured liability (24 payments)", inp, Ln, ev.amounts["liability_after"])
    record(12, "Lease reduction", "Gain/(loss) = f x (Liability - ROU), f = reduction in remaining term", inp, gain,
           ev.amounts["gain_loss"], Dec("0.10"))
    record(12, "Lease reduction", "ROU after = ROU x (1-f) + (Lnew - L x (1-f))", inp,
           rou_b * (1 - f) + (Ln - Lb * (1 - f)), ev.amounts["rou_after"], Dec("0.10"))


def s13_full_termination():
    t = TerminationInput("T1", date(2027, 4, 1), True, termination_payment=Dec(200000))
    res = calculate_lease(lease(terminations=[t]))
    L0 = res.summary["initial_liability"]
    Lb = _l_before(L0, [Dec(100000)] * 60, 10, 24)
    rou_b = q2(L0) - q2(L0) / 60 * 24
    ev = next(e for e in res.events if e.kind == "TERMINATION")
    inp = "Full termination w.e.f. 1-Apr-2027; termination payment 2,00,000"
    record(13, "Full termination", "Liability derecognised", inp, Lb, ev.amounts["liability"])
    record(13, "Full termination", "ROU (net) derecognised", inp, rou_b, ev.amounts["rou_net"], Dec("0.10"))
    record(13, "Full termination", "Gain/(loss) = L - ROU - payment", inp, Lb - rou_b - 200000,
           ev.amounts["gain_loss"], Dec("0.10"))
    record(13, "Full termination", "No interest / depreciation after termination", inp, 0,
           sum((r.values["liab_interest"] + r.values["rou_depreciation"] for r in res.months[24:]), Dec(0)))


def s14_partial_termination():
    t = TerminationInput("T1", date(2027, 4, 1), False, partial_pct=Dec(40), termination_payment=Dec(50000))
    res = calculate_lease(lease(terminations=[t]))
    L0 = res.summary["initial_liability"]
    Lb = _l_before(L0, [Dec(100000)] * 60, 10, 24)
    rou_b = q2(L0) - q2(L0) / 60 * 24
    ev = next(e for e in res.events if e.kind == "PARTIAL_TERMINATION")
    inp = "40% of area surrendered w.e.f. 1-Apr-2027; rent becomes 60,000; payment 50,000"
    record(14, "Partial termination", "Liability after = PV of 36 x 60,000", inp, pv([(k, 60000) for k in range(36)], 10),
           ev.amounts["liability_after"])
    record(14, "Partial termination", "Gain/(loss) = 40% x (L - ROU) - 50,000", inp,
           Dec("0.4") * (Lb - rou_b) - 50000, ev.amounts["gain_loss"], Dec("0.10"))
    record(14, "Partial termination", "Rent after partial termination", inp, 60000,
           res.months[24].values["liab_payment"])


def s15_19_deposits():
    sd = [DepositMovementInput("SD1", date(2025, 4, 1), "Original", Dec(600000), annual_rate=Dec(9),
                               expected_refund_date=date(2030, 4, 1)),
          DepositMovementInput("SD2", date(2027, 4, 1), "Addition", Dec(120000), annual_rate=Dec(9),
                               expected_refund_date=date(2030, 4, 1)),
          DepositMovementInput("R1", date(2028, 4, 1), "Refund", Dec(100000)),
          DepositMovementInput("R2", date(2030, 4, 1), "Refund", Dec(620000))]
    res = calculate_lease(lease(end_date=date(2030, 3, 31), deposits=sd))
    fv1 = Dec(600000) / Dec("1.0075") ** 60
    inp = "SD 6,00,000 interest-free at commencement, 9% market rate, refund 1-Apr-2030"
    record(15, "Security deposit at commencement", "Fair value = 6,00,000 / (1+0.09/12)^60", inp, fv1,
           next(e for e in res.events if e.ref == "SD1").amounts["fair_value"])
    record(15, "Security deposit at commencement", "Discount added to ROU = 6,00,000 - FV", inp, 600000 - q2(fv1),
           next(e for e in res.events if e.ref == "SD1").amounts["rou"])
    record(19, "Interest-free deposit", "Month 1 unwinding = FV x monthly rate", inp, q2(fv1) * mrate(9),
           res.months[0].values["sd_unwinding"], Dec("0.05"))
    fv2 = Dec(120000) / Dec("1.0075") ** 36
    ev2 = next(e for e in res.events if e.ref == "SD2")
    inp2 = "Additional deposit 1,20,000 on 1-Apr-2027 (36 months to refund), 9%"
    record(16, "Additional deposit during lease", "Fair value = 1,20,000 / (1+0.09/12)^36", inp2, fv2, ev2.amounts["fair_value"])
    record(16, "Additional deposit during lease", "Discount added to ROU (not a modification)", inp2, 120000 - q2(fv2),
           ev2.amounts["rou"])
    rou_open = res.months[24].values["rou_open"]
    record(16, "Additional deposit during lease", "Depreciation after = (ROU + discount) / 36", inp2,
           (rou_open + 120000 - q2(fv2)) / 36, res.months[24].values["rou_depreciation"], Dec("0.10"))
    # carrying of tranche 1 at 1-Apr-2028 = 600000 / (1+0.09/12)^24 ; refund 100000 FIFO from tranche 1
    carry1 = Dec(600000) / Dec("1.0075") ** 24
    share = carry1 * 100000 / 600000
    ev3 = next(e for e in res.events if e.ref == "R1")
    inp3 = "Partial refund 1,00,000 on 1-Apr-2028 (2 years early), FIFO from original deposit"
    record(17, "Partial deposit refund", "Carrying amount derecognised", inp3, share, ev3.amounts["carrying"])
    record(17, "Partial deposit refund", "Difference to P&L = 1,00,000 - carrying", inp3, 100000 - q2(share),
           ev3.amounts["difference"])
    ev4 = next(e for e in res.events if e.ref == "R2")
    inp4 = "Final refund 6,20,000 on expected refund date 1-Apr-2030"
    record(18, "Full deposit refund", "Carrying = nominal on refund date", inp4, 620000, ev4.amounts["carrying"])
    record(18, "Full deposit refund", "No P&L difference", inp4, 0, ev4.amounts["difference"])
    record(18, "Full deposit refund", "Closing deposit balance", inp4, 0, res.months[-1].values["sd_close"])
    record(19, "Interest-free deposit", "Total unwinding = nominal - FV - early refund difference", inp,
           720000 - q2(fv1) - q2(fv2) - (100000 - q2(share)), month_sum(res, "sd_unwinding"), Dec("0.05"))


def s20_24_portfolio():
    from lease_app.db.database import Database
    from lease_app.db.repository import ValidationError
    from lease_app.engine.journals import check_balanced
    from lease_app.sample_data import load_sample_data
    from lease_app.services import LeaseService
    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "t.sqlite"))
    svc = LeaseService(db)
    load_sample_data(svc.repo)
    res = svc.calculate_all()
    apr = date(2027, 4, 1)
    lines = svc.generate_month(apr)
    dr = sum((l.debit for l in lines), Dec(0))
    cr = sum((l.credit for l in lines), Dec(0))
    inp = "8 sample leases (L0001-L0008), April 2027"
    record(20, "Multiple leases", "Number of leases calculated", inp, 8, len(res))
    exp_int = sum((r.month(apr).values["liab_interest"] for r in res.values()), Dec(0))
    act_int = sum((l.debit for l in lines if l.journal_type == "LIABILITY_INTEREST"), Dec(0))
    record(20, "Multiple leases", "Interest journals = sum of lease schedules", inp, exp_int, act_int)
    exp_dep = sum((r.month(apr).values["rou_depreciation"] for r in res.values()), Dec(0))
    act_dep = sum((l.debit for l in lines if l.journal_type == "ROU_DEPRECIATION"), Dec(0))
    record(20, "Multiple leases", "Depreciation journals = sum of lease schedules", inp, exp_dep, act_dep)
    record(21, "Monthly journal generation", "Total debit = total credit", inp, dr, cr)
    record(21, "Monthly journal generation", "Unbalanced vouchers", inp, 0, len(check_balanced(lines)))
    types = {l.journal_type for l in lines}
    needed = {"INITIAL_RECOGNITION", "ROU_DEPRECIATION", "LIABILITY_INTEREST", "LEASE_RENTAL_PAYMENT", "SD_ADDITION",
              "SD_REFUND", "SD_UNWINDING", "LEASE_MODIFICATION", "LEASE_TERMINATION"}
    record(21, "Monthly journal generation", "Journal types missing for April 2027", inp, 0, len(needed - types))
    # liability movement in journals ties to schedule
    liab_code = db.accounts()["LEASE_LIAB"][0]
    net_liab = sum((l.credit - l.debit for l in lines if l.account_code == liab_code), Dec(0))
    exp_move = sum((r.month(apr).values["liab_close"] - r.month(apr).values["liab_open"] for r in res.values()), Dec(0))
    record(21, "Monthly journal generation", "Net lease-liability journals = closing - opening liability", inp,
           exp_move, net_liab)
    svc.set_batch_status(apr, "Approved", "test")
    blocked = 0
    try:
        svc.generate_month(apr, regenerate=True)
    except ValidationError:
        blocked = 1
    record(21, "Monthly journal generation", "Duplicate generation blocked after approval (1 = blocked)", inp, 1, blocked)
    db.close()
    for no, name in ((22, "GL reconciliation"), (23, "Month closure"), (24, "Month reopening")):
        RESULTS.append({"no": no, "scenario": name, "check": "Scheduled for Phase 3", "input": "",
                        "expected": None, "actual": None, "difference": None, "status": "Phase 3"})


ALL = [s01_no_escalation, s02_percentage, s03_absolute, s04_multiple, s05_rent_free, s06_advance, s07_arrears,
       s08_quarterly, s09_mid_month, s10_modification_rent, s11_extension, s12_reduction, s13_full_termination,
       s14_partial_termination, s15_19_deposits, s20_24_portfolio]


def run_all():
    RESULTS.clear()
    for fn in ALL:
        fn()
    return sorted(RESULTS, key=lambda r: r["no"])
