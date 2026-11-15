"""Single definition of every register (table).  The database schema, the desktop entry
forms, the Excel templates and the import validation are all generated from these
definitions, so a field is defined once and behaves the same everywhere."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from .engine.decimal_utils import D

YES_NO = ["Yes", "No"]
FREQUENCIES = ["Monthly", "Quarterly", "Half-yearly", "Annual"]
TIMINGS = ["Advance", "Arrears"]
APPROVAL = ["Draft", "Approved", "Rejected"]


@dataclass
class Field:
    key: str
    label: str
    ftype: str = "text"          # text | date | decimal | int | choice | lease | longtext
    required: bool = False
    choices: list = field(default_factory=list)
    default: object = None
    readonly: bool = False       # computed / auto-generated
    help: str = ""


@dataclass
class Register:
    name: str
    table: str
    title: str
    key: str
    fields: list
    key_prefix: str = ""         # for auto-generated IDs
    child_of_lease: bool = True
    list_columns: list = field(default_factory=list)

    def field(self, key) -> Field:
        return next(f for f in self.fields if f.key == key)

    @property
    def keys(self):
        return [f.key for f in self.fields]


LEASE_MASTER = Register("lease_master", "leases", "Lease Master", "lease_id", [
    Field("lease_id", "Lease ID", readonly=True, help="Auto-generated (L0001...) if left blank"),
    Field("agreement_no", "Agreement number", required=True),
    Field("landlord_name", "Landlord name", required=True),
    Field("entity", "Entity / Company", required=True),
    Field("location", "Store / Location", required=True),
    Field("address", "Address", "longtext"),
    Field("lease_category", "Lease category", "choice",
          choices=["Retail store", "Office", "Warehouse", "Land", "Residential", "Vehicle", "Equipment", "Other"],
          default="Retail store"),
    Field("agreement_start_date", "Agreement start date", "date"),
    Field("commencement_date", "Commencement date", "date", required=True),
    Field("lease_end_date", "Lease end date", "date", required=True),
    Field("lease_tenure_months", "Lease tenure (months)", "decimal", readonly=True, help="Calculated"),
    Field("renewal_option", "Renewal option", help="Describe; include in term only if reasonably certain"),
    Field("termination_option", "Termination option"),
    Field("rent_free_months", "Rent-free period (months)", "int", default=0),
    Field("payment_frequency", "Payment frequency", "choice", True, FREQUENCIES, "Monthly"),
    Field("payment_timing", "Payment terms", "choice", True, TIMINGS, "Advance"),
    Field("monthly_rent", "Monthly rent at commencement", "decimal", True),
    Field("security_deposit", "Security deposit", "decimal", default=0,
          help="Original deposit; detailed movements go to the Security Deposit register"),
    Field("discount_rate", "Discount rate / IBR (% p.a.)", "decimal", True),
    Field("lease_status", "Lease status", "choice",
          choices=["Active", "Expired", "Terminated", "Under Modification"], default="Active"),
    Field("prepaid_lease_rentals", "Prepaid lease rentals", "decimal", default=0),
    Field("initial_direct_costs", "Initial direct costs", "decimal", default=0),
    Field("lease_incentives", "Lease incentives received", "decimal", default=0),
    Field("restoration_provision", "Restoration / dismantling obligation (PV)", "decimal", default=0),
    Field("other_initial_adjustments", "Other eligible initial adjustments", "decimal", default=0),
    Field("gst_rate", "GST rate % (if tracked)", "decimal", default=0),
    Field("non_lease_monthly", "Non-lease component per month", "decimal", default=0),
    Field("remarks", "Remarks", "longtext"),
], key_prefix="L", child_of_lease=False,
    list_columns=["lease_id", "agreement_no", "landlord_name", "entity", "location", "commencement_date",
                  "lease_end_date", "payment_frequency", "payment_timing", "monthly_rent", "discount_rate",
                  "security_deposit", "lease_status"])

ESCALATIONS = Register("escalations", "escalations", "Rent Escalation Register", "escalation_ref", [
    Field("escalation_ref", "Escalation reference", readonly=True, help="Auto-generated if blank"),
    Field("lease_id", "Lease ID", "lease", True),
    Field("effective_date", "Effective date", "date", True),
    Field("escalation_type", "Escalation type", "choice", True, ["Percentage", "Absolute Amount"], "Percentage"),
    Field("escalation_pct", "Escalation %", "decimal", help="Required for Percentage"),
    Field("escalation_amount", "Absolute escalation amount (per month)", "decimal",
          help="Required for Absolute Amount"),
    Field("frequency_months", "Escalation frequency (months)", "int", True, default=12,
          help="0 = one-time; 12 = every year; 36 = every 3 years. Repeats until the next rule"),
    Field("remarks", "Remarks"),
    Field("agreement_ref", "Agreement reference / clause"),
], key_prefix="ESC",
    list_columns=["escalation_ref", "lease_id", "effective_date", "escalation_type", "escalation_pct",
                  "escalation_amount", "frequency_months", "remarks", "agreement_ref"])

MODIFICATIONS = Register("modifications", "modifications", "Lease Modification Register", "mod_ref", [
    Field("mod_ref", "Modification reference", required=True),
    Field("lease_id", "Lease ID", "lease", True),
    Field("effective_date", "Effective date", "date", True),
    Field("modification_type", "Modification type", "choice", True,
          ["Change in tenure", "Lease extension", "Lease reduction", "Rent change", "Payment frequency change",
           "Change in leased area", "Change in scope", "Other"], "Lease extension"),
    Field("reason", "Reason", "longtext"),
    Field("original_terms", "Original terms (summary)", "longtext"),
    Field("revised_terms", "Revised terms (summary)", "longtext"),
    Field("revised_monthly_rent", "Revised monthly rent", "decimal", help="Blank = continue current rent"),
    Field("revised_end_date", "Revised expiry date", "date", help="Blank = unchanged"),
    Field("revised_discount_rate", "Revised discount rate % p.a.", "decimal", help="Blank = unchanged"),
    Field("revised_payment_frequency", "Revised payment frequency", "choice", choices=[""] + FREQUENCIES),
    Field("revised_payment_timing", "Revised payment terms", "choice", choices=[""] + TIMINGS),
    Field("area_reduction_pct", "Reduction in leased area / scope %", "decimal", default=0,
          help="Decrease in scope -> proportionate derecognition with gain/loss"),
    Field("keep_existing_escalations", "Continue existing escalation clauses", "choice", True, YES_NO, "Yes"),
    Field("revised_escalation_type", "Revised escalation type", "choice",
          choices=["", "Percentage", "Absolute Amount"]),
    Field("revised_escalation_pct", "Revised escalation %", "decimal"),
    Field("revised_escalation_amount", "Revised escalation amount", "decimal"),
    Field("revised_escalation_frequency", "Revised escalation frequency (months)", "int"),
    Field("revised_first_escalation_date", "First revised escalation date", "date"),
    Field("separate_lease", "Separate lease (Ind AS 116.44)?", "choice", True, YES_NO, "No"),
    Field("accounting_assessment", "Accounting assessment", "longtext"),
    Field("approval_status", "Approval status", "choice", True, APPROVAL, "Draft"),
], list_columns=["mod_ref", "lease_id", "effective_date", "modification_type", "revised_monthly_rent",
                 "revised_end_date", "revised_discount_rate", "area_reduction_pct", "separate_lease",
                 "approval_status"])

TERMINATIONS = Register("terminations", "terminations", "Lease Termination Register", "term_ref", [
    Field("term_ref", "Termination reference", required=True),
    Field("lease_id", "Lease ID", "lease", True),
    Field("effective_date", "Effective date", "date", True,
          help="First day on which the lease no longer applies (payments due on/after are cancelled)"),
    Field("termination_type", "Termination type", "choice", True, ["Full", "Partial"], "Full"),
    Field("partial_pct", "Partial termination % (area / scope surrendered)", "decimal", default=0),
    Field("revised_monthly_rent", "Revised monthly rent (partial)", "decimal",
          help="Blank = current rent x (1 - partial %)"),
    Field("termination_reason", "Termination reason", "longtext"),
    Field("termination_payment", "Termination payment / penalty", "decimal", default=0),
    Field("settlement_amount", "Settlement amount (information)", "decimal", default=0),
    Field("approval_reference", "Approval reference"),
    Field("approval_status", "Approval status", "choice", True, APPROVAL, "Draft"),
], list_columns=["term_ref", "lease_id", "effective_date", "termination_type", "partial_pct",
                 "termination_payment", "approval_reference", "approval_status"])

DEPOSITS = Register("deposits", "deposit_movements", "Security Deposit Movement Register", "deposit_ref", [
    Field("deposit_ref", "Deposit reference", required=True),
    Field("lease_id", "Lease ID", "lease", True),
    Field("movement_type", "Movement type", "choice", True, ["Original", "Addition", "Refund"], "Original"),
    Field("movement_date", "Deposit / refund date", "date", True),
    Field("amount", "Amount", "decimal", True),
    Field("refundable", "Refundable / Non-refundable", "choice", True, ["Refundable", "Non-refundable"],
          "Refundable"),
    Field("interest_type", "Interest-free / Interest-bearing", "choice", True,
          ["Interest-free", "Interest-bearing"], "Interest-free"),
    Field("discount_rate", "Discount rate % p.a. (market rate)", "decimal",
          help="Blank = Settings default deposit rate, else lease IBR"),
    Field("expected_refund_date", "Expected refund date", "date", help="Blank = lease end date"),
    Field("accounting_treatment", "Accounting treatment", "longtext",
          default="Amortised cost (Ind AS 109); discount treated as prepaid lease payment in ROU"),
    Field("supporting_document", "Supporting document"),
    Field("approval_status", "Approval status", "choice", True, APPROVAL, "Approved"),
    Field("remarks", "Remarks"),
], list_columns=["deposit_ref", "lease_id", "movement_type", "movement_date", "amount", "refundable",
                 "interest_type", "discount_rate", "expected_refund_date", "approval_status"])

PAYMENT_ACTUALS = Register("payment_actuals", "payment_actuals", "Lease Payment Actuals", "payment_ref", [
    Field("payment_ref", "Payment reference", required=True),
    Field("lease_id", "Lease ID", "lease", True),
    Field("due_date", "Payment due date", "date", True),
    Field("actual_payment_date", "Actual payment date", "date"),
    Field("actual_amount", "Actual payment amount", "decimal"),
    Field("remarks", "Remarks"),
])

GL_BALANCES = Register("gl_balances", "gl_balances", "GL Balance Upload", "gl_ref", [
    Field("gl_ref", "Reference", readonly=True),
    Field("month", "Month (YYYY-MM)", required=True),
    Field("entity", "Entity"),
    Field("account_code", "Account code", required=True),
    Field("account_name", "Account name"),
    Field("gl_balance", "GL closing balance (Dr + / Cr -)", "decimal", True),
], child_of_lease=False)

REGISTERS = {r.name: r for r in [LEASE_MASTER, ESCALATIONS, MODIFICATIONS, TERMINATIONS, DEPOSITS,
                                 PAYMENT_ACTUALS, GL_BALANCES]}


# --------------------------------------------------------------------------- parsing
def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "nat", "none"):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d %H:%M:%S",
                "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}' (use DD-MM-YYYY)")


def normalise(reg: Register, raw: dict) -> tuple[dict, list[str]]:
    """Convert raw values (from a form or Excel) to storable strings; return (values, errors)."""
    out, errors = {}, []
    for f in reg.fields:
        v = raw.get(f.key)
        if v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and v.strip() == ""):
            v = None
        try:
            if v is None:
                if f.required and not f.readonly:
                    errors.append(f"{f.label}: mandatory field is missing")
                out[f.key] = None if f.default is None else str(f.default)
                continue
            if f.ftype == "date":
                out[f.key] = parse_date(v).isoformat()
            elif f.ftype == "decimal":
                out[f.key] = str(D(v))
            elif f.ftype == "int":
                dv = D(v)
                if dv != dv.to_integral_value():
                    raise ValueError(f"must be a whole number, got {v}")
                out[f.key] = str(int(dv))
            elif f.ftype == "choice":
                s = str(v).strip()
                match = next((c for c in f.choices if c.lower() == s.lower()), None)
                if match is None:
                    raise ValueError(f"'{s}' is not one of {', '.join(c for c in f.choices if c)}")
                out[f.key] = match
            else:
                out[f.key] = str(v).strip()
        except (ValueError, ArithmeticError) as exc:
            errors.append(f"{f.label}: {exc}")
    return out, errors
