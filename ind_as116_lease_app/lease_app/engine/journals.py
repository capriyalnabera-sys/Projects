"""Monthly journal-entry generation from lease calculation results."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .dates import month_end, month_start, ym
from .decimal_utils import ZERO, r2
from .lease_engine import LeaseResult

DEFAULT_ACCOUNTS = {
    # key: (code, name)
    "ROU_GROSS": ("150100", "Right-of-use asset - gross block"),
    "ROU_ACCDEP": ("150190", "Accumulated depreciation - right-of-use asset"),
    "LEASE_LIAB": ("260100", "Lease liability"),
    "RENT_PAYABLE": ("210500", "Lease rent payable - landlords"),
    "INT_EXP": ("710100", "Interest expense on lease liability"),
    "DEP_EXP": ("720100", "Depreciation on right-of-use asset"),
    "SD_ASSET": ("160100", "Security deposit - lease (amortised cost)"),
    "SD_INT_INC": ("410100", "Interest income - unwinding of security deposit"),
    "BANK": ("120100", "Bank account"),
    "MOD_GAIN_LOSS": ("490100", "Gain / loss on lease modification"),
    "TERM_GAIN_LOSS": ("490200", "Gain / loss on lease termination"),
    "SD_REFUND_DIFF": ("490300", "Gain / loss on early refund of security deposit"),
    "PREPAID_RENT": ("170100", "Prepaid lease rentals"),
    "IDC_CLEARING": ("210900", "Initial direct costs - clearing"),
    "INCENTIVE_RECV": ("170200", "Lease incentive receivable"),
    "RESTORATION_PROV": ("270100", "Provision for restoration / dismantling"),
    "OTHER_ADJ_CLEARING": ("210950", "Lease initial adjustments - clearing"),
    "GST_INPUT": ("180100", "GST input tax credit"),
    "NONLEASE_EXP": ("730100", "Non-lease components (CAM / maintenance)"),
    "TERM_PAYABLE": ("210600", "Lease termination payable"),
}

JOURNAL_TYPES = {
    "INIT": ("INITIAL_RECOGNITION", "IR"),
    "DEPRECIATION": ("ROU_DEPRECIATION", "DP"),
    "INTEREST": ("LIABILITY_INTEREST", "IN"),
    "PAYMENT": ("LEASE_RENTAL_PAYMENT", "RP"),
    "SD_ADDITION": ("SD_ADDITION", "SA"),
    "SD_REFUND": ("SD_REFUND", "SR"),
    "SD_UNWINDING": ("SD_UNWINDING", "SU"),
    "MODIFICATION": ("LEASE_MODIFICATION", "MD"),
    "PARTIAL_TERMINATION": ("LEASE_TERMINATION", "PT"),
    "TERMINATION": ("LEASE_TERMINATION", "TR"),
}


@dataclass
class JournalLine:
    accounting_month: str
    accounting_date: date
    lease_id: str
    agreement_no: str
    entity: str
    location: str
    voucher_no: str
    account_key: str
    account_code: str
    account_name: str
    narration: str
    debit: Decimal
    credit: Decimal
    journal_type: str
    calc_ref: str
    status: str = "Draft"


class _Voucher:
    def __init__(self, res: LeaseResult, month: date, jkey: str, seq: int, acc_date: date,
                 narration: str, calc_ref: str, accounts: dict):
        self.res, self.lines, self.accounts = res, [], accounts
        jtype, code = JOURNAL_TYPES[jkey]
        self.jtype = jtype
        self.voucher = f"LA/{ym(month)}/{res.lease.lease_id}/{code}{seq:02d}"
        self.month, self.date, self.narr, self.ref = ym(month), acc_date, narration, calc_ref

    def add(self, key: str, amount: Decimal, debit: bool, narration: str = ""):
        amount = r2(amount)
        if amount == ZERO:
            return
        if amount < 0:
            amount, debit = -amount, not debit
        code, name = self.accounts.get(key, DEFAULT_ACCOUNTS[key])
        L = self.res.lease
        self.lines.append(JournalLine(
            self.month, self.date, L.lease_id, L.agreement_no, L.entity, L.location, self.voucher,
            key, code, name, narration or self.narr, amount if debit else ZERO,
            ZERO if debit else amount, self.jtype, self.ref))

    def dr(self, key, amount, narration=""):
        self.add(key, amount, True, narration)

    def cr(self, key, amount, narration=""):
        self.add(key, amount, False, narration)


def build_month_journals(res: LeaseResult, month: date, accounts: dict | None = None) -> list[JournalLine]:
    accounts = accounts or {}
    month = month_start(month)
    me = month_end(month)
    row = res.month(month)
    lines: list[JournalLine] = []
    seq = 0
    lid = res.lease.lease_id
    mlabel = month.strftime("%b-%Y")

    def voucher(jkey, d, narr, ref):
        nonlocal seq
        seq += 1
        return _Voucher(res, month, jkey, seq, d, narr, ref, accounts)

    # 1. event-driven entries (initial recognition, deposits, modifications, terminations)
    for ev in sorted(res.events_in(month), key=lambda e: e.event_date):
        a = ev.amounts
        if ev.kind == "INIT":
            v = voucher("INIT", ev.event_date, f"{lid}: initial recognition of ROU asset and lease liability", ev.ref)
            v.dr("ROU_GROSS", a["rou"])
            v.dr("INCENTIVE_RECV", a["incentives"], f"{lid}: lease incentives received reduce ROU")
            v.cr("LEASE_LIAB", a["liability"], f"{lid}: PV of lease payments")
            v.cr("PREPAID_RENT", a["prepaid"], f"{lid}: prepaid lease rentals transferred to ROU")
            v.cr("IDC_CLEARING", a["idc"], f"{lid}: initial direct costs capitalised")
            v.cr("RESTORATION_PROV", a["restoration"], f"{lid}: restoration / dismantling provision")
            v.cr("OTHER_ADJ_CLEARING", a["other_adj"], f"{lid}: other initial adjustments")
        elif ev.kind == "SD_ADDITION":
            v = voucher("SD_ADDITION", ev.event_date, f"{lid}: security deposit {ev.ref} paid", ev.ref)
            v.dr("SD_ASSET", a["fair_value"], f"{lid}: deposit {ev.ref} at fair value")
            v.dr("ROU_GROSS", a["rou"], f"{lid}: discount on deposit {ev.ref} = prepaid lease payment")
            v.dr("PREPAID_RENT", a["prepaid"], f"{lid}: discount on deposit {ev.ref} (pre-commencement)")
            v.dr("TERM_GAIN_LOSS", a["pnl"], f"{lid}: discount on deposit {ev.ref} (lease not active)")
            v.cr("BANK", a["cash"])
        elif ev.kind == "SD_REFUND":
            v = voucher("SD_REFUND", ev.event_date, f"{lid}: security deposit refund {ev.ref}", ev.ref)
            v.dr("BANK", a["cash"])
            v.cr("SD_ASSET", a["carrying"], f"{lid}: carrying amount of deposit refunded")
            v.cr("SD_REFUND_DIFF", a["difference"], f"{lid}: early refund - unamortised discount")
        elif ev.kind in ("MODIFICATION", "PARTIAL_TERMINATION"):
            if a.get("separate_lease"):
                continue
            jkey = "MODIFICATION" if ev.kind == "MODIFICATION" else "PARTIAL_TERMINATION"
            gl = "MOD_GAIN_LOSS" if ev.kind == "MODIFICATION" else "TERM_GAIN_LOSS"
            v = voucher(jkey, ev.event_date, f"{lid}: {ev.description} ({ev.ref})", ev.ref)
            v.dr("ROU_ACCDEP", a["rou_accdep_decrease"], f"{lid}: accumulated depreciation on decrease in scope")
            v.cr("ROU_GROSS", a["rou_gross_decrease"], f"{lid}: proportionate decrease in ROU (scope)")
            v.dr("ROU_GROSS", a["rou_remeasurement"], f"{lid}: remeasurement adjusted to ROU")
            v.cr("LEASE_LIAB", a["liability_change"], f"{lid}: remeasurement of lease liability")
            v.cr("TERM_PAYABLE", a["termination_payment"], f"{lid}: termination payment")
            v.cr(gl, a["gain_loss"], f"{lid}: gain / (loss) on {ev.description.lower()}")
        elif ev.kind == "TERMINATION":
            v = voucher("TERMINATION", ev.event_date, f"{lid}: full termination ({ev.ref})", ev.ref)
            v.dr("LEASE_LIAB", a["liability"], f"{lid}: derecognise lease liability")
            v.dr("ROU_ACCDEP", a["rou_accdep"], f"{lid}: derecognise accumulated depreciation")
            v.cr("ROU_GROSS", a["rou_gross"], f"{lid}: derecognise ROU gross block")
            v.cr("TERM_PAYABLE", a["termination_payment"], f"{lid}: termination payment")
            v.cr("TERM_GAIN_LOSS", a["gain_loss"], f"{lid}: gain / (loss) on termination")
        else:
            continue
        lines.extend(v.lines)

    if row is None:
        return lines
    val = row.values
    # 2. depreciation
    if val["rou_depreciation"]:
        v = voucher("DEPRECIATION", me, f"{lid}: ROU depreciation for {mlabel}", f"{lid}/ROU/{ym(month)}")
        v.dr("DEP_EXP", val["rou_depreciation"])
        v.cr("ROU_ACCDEP", val["rou_depreciation"])
        lines.extend(v.lines)
    # 3. interest
    if val["liab_interest"]:
        v = voucher("INTEREST", me, f"{lid}: interest on lease liability for {mlabel}", f"{lid}/LIAB/{ym(month)}")
        v.dr("INT_EXP", val["liab_interest"])
        v.cr("LEASE_LIAB", val["liab_interest"])
        lines.extend(v.lines)
    # 4. rental payments falling due in the month
    pays = res.payments_in(month)
    if pays:
        due = max(p.due_date for p in pays)
        v = voucher("PAYMENT", due, f"{lid}: lease rent due for {mlabel}", f"{lid}/PAY/{ym(month)}")
        v.dr("LEASE_LIAB", sum((p.eligible_payment for p in pays), ZERO), f"{lid}: lease payment against liability")
        v.dr("NONLEASE_EXP", sum((p.non_lease for p in pays), ZERO), f"{lid}: non-lease component")
        v.dr("GST_INPUT", sum((p.gst for p in pays), ZERO), f"{lid}: GST on rent")
        v.cr("RENT_PAYABLE", sum((p.total_payable for p in pays), ZERO), f"{lid}: rent payable to landlord")
        lines.extend(v.lines)
    # 5. deposit unwinding
    if val["sd_unwinding"]:
        v = voucher("SD_UNWINDING", me, f"{lid}: unwinding of security deposit discount for {mlabel}",
                    f"{lid}/SD/{ym(month)}")
        v.dr("SD_ASSET", val["sd_unwinding"])
        v.cr("SD_INT_INC", val["sd_unwinding"])
        lines.extend(v.lines)
    return lines


def check_balanced(lines) -> list[str]:
    """Return vouchers whose debits and credits do not agree."""
    totals = {}
    for ln in lines:
        d, c = totals.get(ln.voucher_no, (ZERO, ZERO))
        totals[ln.voucher_no] = (d + ln.debit, c + ln.credit)
    return [vn for vn, (d, c) in totals.items() if d != c]
