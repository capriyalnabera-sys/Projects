"""Excel templates, import with validation / error report, and exports."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..db.repository import Repository, ValidationError
from ..engine.dates import month_label, ym
from ..engine.decimal_utils import D, ZERO
from ..engine.lease_engine import MONTH_FIELDS, LeaseResult
from ..registers import REGISTERS, Register, parse_date

HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
HEAD_FONT = Font(bold=True, color="FFFFFF")
REQ_FILL = PatternFill("solid", fgColor="C00000")
SUB_FILL = PatternFill("solid", fgColor="DDEBF7")
BOLD = Font(bold=True)
THIN = Side(style="thin", color="BFBFBF")
NUM = '#,##,##0.00;[Red]-#,##,##0.00'
DATE_FMT = "DD-MMM-YYYY"


def _header(ws, row, headers, fills=None):
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = HEAD_FONT
        c.fill = (fills[i - 1] if fills else None) or HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _autosize(ws, min_w=10, max_w=45):
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                l = len(str(c.value)) if not isinstance(c.value, (int, float, Decimal)) else 14
                widths[c.column_letter] = max(widths.get(c.column_letter, 0), l)
    for col, w in widths.items():
        ws.column_dimensions[col].width = max(min_w, min(max_w, w + 2))


def _cell_value(v, ftype=None):
    if v is None or v == "":
        return None
    if ftype == "date" or isinstance(v, date):
        d = parse_date(v) if not isinstance(v, date) else v
        return d
    if ftype in ("decimal",) or isinstance(v, Decimal):
        return float(D(v))
    if ftype == "int":
        return int(D(v))
    return v


def _write_rows(ws, start_row, rows, ftypes=None):
    for r, row in enumerate(rows, start_row):
        for c, v in enumerate(row, 1):
            ft = ftypes[c - 1] if ftypes else None
            cell = ws.cell(row=r, column=c, value=_cell_value(v, ft))
            if isinstance(cell.value, (date, datetime)):
                cell.number_format = DATE_FMT
            elif isinstance(cell.value, float) and ft != "int":
                cell.number_format = NUM


# =========================================================================== templates
def write_template(reg: Register, path, example_rows=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    fields = [f for f in reg.fields if not (f.readonly and f.key != reg.key)]
    headers = [f.label + (" *" if f.required else "") for f in fields]
    _header(ws, 1, headers, [REQ_FILL if f.required else None for f in fields])
    for i, f in enumerate(fields, 1):
        col = get_column_letter(i)
        if f.ftype == "choice":
            dv = DataValidation(type="list", formula1='"' + ",".join(c for c in f.choices if c) + '"',
                                allow_blank=not f.required, showErrorMessage=True,
                                errorTitle="Invalid value", error=f"Choose one of the listed values for {f.label}")
            ws.add_data_validation(dv)
            dv.add(f"{col}2:{col}5000")
        elif f.ftype == "date":
            for r in range(2, 502):
                ws.cell(row=r, column=i).number_format = DATE_FMT
        ws.column_dimensions[col].width = max(14, min(40, len(f.label) + 4))
    if example_rows:
        ex = wb.create_sheet("Example")
        _header(ex, 1, headers)
        _write_rows(ex, 2, [[r.get(f.key) for f in fields] for r in example_rows], [f.ftype for f in fields])
        _autosize(ex)
    ins = wb.create_sheet("Instructions")
    ins.append([f"{reg.title} - upload template"])
    ins["A1"].font = Font(bold=True, size=14)
    ins.append(["Fill the 'Data' sheet (one row per record). Columns marked * (red header) are mandatory. "
                "Dates: DD-MM-YYYY or Excel dates. Amounts in INR without symbols. Do not rename headers."])
    ins.append([])
    ins.append(["Column", "Mandatory", "Type", "Allowed values / notes"])
    for c in ins[4]:
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
    for f in fields:
        notes = ", ".join(c for c in f.choices if c) if f.choices else ""
        if f.help:
            notes = (notes + "; " if notes else "") + f.help
        ins.append([f.label, "Yes" if f.required else "No", f.ftype.replace("lease", "Lease ID (text)"), notes])
    ins.column_dimensions["A"].width = 42
    ins.column_dimensions["D"].width = 90
    wb.save(path)
    return path


def write_gl_template(path, accounts: dict):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    _header(ws, 1, ["Month (YYYY-MM) *", "Entity", "Account code *", "Account name", "GL closing balance (Dr + / Cr -) *"],
            [REQ_FILL, None, REQ_FILL, None, REQ_FILL])
    for key in ("ROU_GROSS", "ROU_ACCDEP", "LEASE_LIAB", "INT_EXP", "DEP_EXP", "SD_ASSET", "SD_INT_INC"):
        code, name = accounts[key]
        ws.append(["2027-04", "ABC Retail Pvt Ltd", code, name, None])
    _autosize(ws)
    wb.save(path)
    return path


def write_journal_template(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "ERP upload"
    _header(ws, 1, ERP_HEADERS)
    _autosize(ws)
    wb.save(path)
    return path


def write_all_templates(folder, repo: Repository):
    from .. import sample_data as sd
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    ex = {"lease_master": [{**sd.COMMON, **r} for r in sd.LEASES[:3]], "escalations": sd.ESCALATIONS[:4],
          "modifications": sd.MODIFICATIONS, "terminations": sd.TERMINATIONS,
          "deposits": [dict(r, refundable="Refundable", interest_type="Interest-free", approval_status="Approved")
                       for r in sd.DEPOSITS[:5]]}
    names = {"lease_master": "01_Lease_Master", "escalations": "02_Rent_Escalation_Register",
             "payment_actuals": "03_Lease_Payment_Schedule_Actuals", "modifications": "04_Modification_Register",
             "terminations": "05_Termination_Register", "deposits": "06_07_Security_Deposit_Movement_Register"}
    for reg_name, fname in names.items():
        p = folder / f"{fname}_Template.xlsx"
        write_template(REGISTERS[reg_name], p, ex.get(reg_name))
        out.append(p)
    out.append(write_gl_template(folder / "08_GL_Balance_Upload_Template.xlsx", repo.db.accounts()))
    out.append(write_journal_template(folder / "09_Journal_Export_ERP_Template.xlsx"))
    return out


# =========================================================================== import
class ImportResult:
    def __init__(self):
        self.imported = 0
        self.errors = []      # (excel_row, key, message)
        self.error_report = None

    @property
    def ok(self):
        return not self.errors


def import_register(repo: Repository, reg: Register | str, path, update_existing=False,
                    error_report_path=None) -> ImportResult:
    """Validate every row first; import only if the whole file is clean (all-or-nothing)."""
    reg = REGISTERS[reg] if isinstance(reg, str) else reg
    res = ImportResult()
    xl = pd.ExcelFile(path)
    sheet = "Data" if "Data" in xl.sheet_names else xl.sheet_names[0]
    df = pd.read_excel(xl, sheet_name=sheet, dtype=object)
    label_map = {}
    for f in reg.fields:
        label_map[f.label.lower()] = f.key
        label_map[f.key.lower()] = f.key
    cols = {}
    for c in df.columns:
        k = label_map.get(str(c).replace("*", "").strip().lower())
        if k:
            cols[c] = k
    missing = [f.label for f in reg.fields if f.required and f.key not in cols.values()]
    if missing:
        res.errors.append((1, "", f"Missing mandatory columns: {', '.join(missing)}"))
    rows = []
    seen = set()
    for idx, rec in df.iterrows():
        raw = {cols[c]: (None if pd.isna(v) else v) for c, v in rec.items() if c in cols}
        if all(v is None or str(v).strip() == "" for v in raw.values()):
            continue
        excel_row = idx + 2
        for k, v in raw.items():
            if isinstance(v, (pd.Timestamp, datetime)):
                raw[k] = v.date()
        key = raw.get(reg.key)
        if key is not None:
            key = str(key).strip()
            raw[reg.key] = key
            if key in seen:
                res.errors.append((excel_row, key, f"Duplicate {reg.field(reg.key).label} within the file"))
            seen.add(key)
        exists = bool(key) and repo.get(reg, key) is not None
        if exists and not update_existing:
            res.errors.append((excel_row, key, f"{reg.field(reg.key).label} '{key}' already exists in the database"))
            continue
        try:
            repo.validate(reg, dict(raw), is_new=not exists, original_key=key if exists else None)
        except ValidationError as ve:
            for m in ve.errors:
                res.errors.append((excel_row, key or "", m))
        rows.append((excel_row, raw, exists))
    if not res.errors:
        for excel_row, raw, exists in rows:
            try:
                repo.save(reg, raw, f"Excel import: {Path(path).name}",
                          original_key=raw[reg.key] if exists else None)
                res.imported += 1
            except ValidationError as ve:
                for m in ve.errors:
                    res.errors.append((excel_row, raw.get(reg.key) or "", m))
    if res.errors:
        report = Path(error_report_path or Path(path).with_name(Path(path).stem + "_ERRORS.xlsx"))
        wb = Workbook()
        ws = wb.active
        ws.title = "Errors"
        _header(ws, 1, ["Excel row", "Record key", "Error"])
        for e in res.errors:
            ws.append(list(e))
        ws.column_dimensions["C"].width = 110
        ws.column_dimensions["B"].width = 20
        wb.save(report)
        res.error_report = report
    return res


# =========================================================================== exports
ERP_HEADERS = ["Journal source", "Voucher number", "Voucher date", "Accounting period", "Entity", "Account code",
               "Account name", "Debit", "Credit", "Cost centre / location", "Reference", "Narration"]

JOURNAL_COLS = [("month", "Accounting month"), ("accounting_date", "Accounting date"), ("lease_id", "Lease ID"),
                ("agreement_no", "Agreement number"), ("entity", "Entity"), ("location", "Location"),
                ("voucher_no", "Voucher number"), ("account_code", "Account code"), ("account_name", "Account name"),
                ("narration", "Narration"), ("debit", "Debit"), ("credit", "Credit"),
                ("journal_type", "Journal type"), ("calc_ref", "Calculation reference"),
                ("status", "Approval status")]


def _line_dict(l):
    if isinstance(l, dict):
        return l
    return {"month": l.accounting_month, "accounting_date": l.accounting_date, "lease_id": l.lease_id,
            "agreement_no": l.agreement_no, "entity": l.entity, "location": l.location, "voucher_no": l.voucher_no,
            "account_code": l.account_code, "account_name": l.account_name, "narration": l.narration,
            "debit": l.debit, "credit": l.credit, "journal_type": l.journal_type, "calc_ref": l.calc_ref,
            "status": l.status}


def export_journals(lines, path, month: date, results: dict | None = None, source="LEASE", company=""):
    lines = [_line_dict(l) for l in lines]
    wb = Workbook()
    ws = wb.active
    ws.title = "Journal lines"
    ws.append([f"{company} - Ind AS 116 monthly journals - {month:%B %Y}"])
    ws["A1"].font = Font(bold=True, size=13)
    _header(ws, 3, [h for _, h in JOURNAL_COLS])
    ftypes = ["text", "date", "text", "text", "text", "text", "text", "text", "text", "text", "decimal", "decimal",
              "text", "text", "text"]
    _write_rows(ws, 4, [[l[k] for k, _ in JOURNAL_COLS] for l in lines], ftypes)
    n = len(lines) + 3
    ws.cell(row=n + 1, column=10, value="Total").font = BOLD
    for col in (11, 12):
        c = ws.cell(row=n + 1, column=col, value=f"=SUM({get_column_letter(col)}4:{get_column_letter(col)}{n})")
        c.font = BOLD
        c.number_format = NUM
    _autosize(ws)

    erp = wb.create_sheet("ERP upload")
    _header(erp, 1, ERP_HEADERS)
    _write_rows(erp, 2, [[source, l["voucher_no"], l["accounting_date"], l["month"], l["entity"], l["account_code"],
                          l["account_name"], l["debit"], l["credit"], l["location"], l["calc_ref"], l["narration"]]
                         for l in lines],
                ["text", "text", "date", "text", "text", "text", "text", "decimal", "decimal", "text", "text", "text"])
    _autosize(erp)

    summ = wb.create_sheet("Account summary")
    _header(summ, 1, ["Account code", "Account name", "Debit", "Credit", "Net (Dr + / Cr -)"])
    agg = {}
    for l in lines:
        k = (l["account_code"], l["account_name"])
        d, c = agg.get(k, (ZERO, ZERO))
        agg[k] = (d + D(l["debit"]), c + D(l["credit"]))
    rows = [[k[0], k[1], d, c, d - c] for k, (d, c) in sorted(agg.items())]
    _write_rows(summ, 2, rows, ["text", "text", "decimal", "decimal", "decimal"])
    tr = len(rows) + 2
    summ.cell(row=tr, column=2, value="Total").font = BOLD
    for col in (3, 4, 5):
        c = summ.cell(row=tr, column=col, value=f"=SUM({get_column_letter(col)}2:{get_column_letter(col)}{tr - 1})")
        c.font = BOLD
        c.number_format = NUM
    _autosize(summ)

    jt = wb.create_sheet("By journal type")
    _header(jt, 1, ["Journal type", "Vouchers", "Debit", "Credit"])
    agg2 = {}
    for l in lines:
        v, d, c = agg2.get(l["journal_type"], (set(), ZERO, ZERO))
        v.add(l["voucher_no"])
        agg2[l["journal_type"]] = (v, d + D(l["debit"]), c + D(l["credit"]))
    _write_rows(jt, 2, [[k, len(v), d, c] for k, (v, d, c) in sorted(agg2.items())],
                ["text", "int", "decimal", "decimal"])
    _autosize(jt)

    if results:
        bal = wb.create_sheet("Lease balances")
        heads = ["Lease ID", "Location", "Opening lease liability", "Interest", "Lease payments", "Modification",
                 "Termination", "Additions", "Closing lease liability", "Current", "Non-current",
                 "Opening ROU (net)", "ROU additions", "ROU modification / termination", "Depreciation",
                 "Closing ROU (net)", "Opening security deposit", "Deposit additions (FV)", "Unwinding",
                 "Refunds (carrying)", "Closing security deposit (carrying)", "Deposit nominal balance"]
        _header(bal, 1, heads)
        rows = []
        for lid, res in results.items():
            row = res.month(month)
            if row is None:
                continue
            v = row.values
            rows.append([lid, res.lease.location, v["liab_open"], v["liab_interest"], -v["liab_payment"],
                         v["liab_modification"], v["liab_termination"], v["liab_initial"], v["liab_close"],
                         v["liab_current"], v["liab_non_current"], v["rou_open"], v["rou_addition"],
                         v["rou_mod_gross"] - v["rou_mod_accdep"] + v["rou_term_gross"] - v["rou_term_accdep"],
                         -v["rou_depreciation"], v["rou_close"], v["sd_open"], v["sd_addition"], v["sd_unwinding"],
                         -v["sd_refund"], v["sd_close"], v["sd_nominal_close"]])
        _write_rows(bal, 2, rows, ["text", "text"] + ["decimal"] * 20)
        tr = len(rows) + 2
        bal.cell(row=tr, column=1, value="Total").font = BOLD
        for col in range(3, len(heads) + 1):
            c = bal.cell(row=tr, column=col, value=f"=SUM({get_column_letter(col)}2:{get_column_letter(col)}{tr - 1})")
            c.font = BOLD
            c.number_format = NUM
        _autosize(bal, max_w=22)
    wb.save(path)
    return path


LIAB_COLS = [("liab_open", "Opening lease liability"), ("liab_initial", "Initial recognition"),
             ("liab_interest", "Interest expense"), ("liab_payment", "Lease payment"),
             ("liab_modification", "Modification adjustment"), ("liab_termination", "Termination adjustment"),
             ("liab_close", "Closing lease liability"), ("liab_current", "Current portion"),
             ("liab_non_current", "Non-current portion")]
ROU_COLS = [("rou_open", "Opening ROU (net)"), ("rou_addition", "Additions"), ("rou_mod_gross", "Modification - gross"),
            ("rou_mod_accdep", "Modification - acc. dep."), ("rou_term_gross", "Termination - gross"),
            ("rou_term_accdep", "Termination - acc. dep."), ("rou_depreciation", "Depreciation"),
            ("rou_close", "Closing ROU (net)"), ("rou_gross_close", "Closing gross block"),
            ("rou_accdep_close", "Closing accumulated depreciation")]
SD_COLS = [("sd_open", "Opening carrying amount"), ("sd_addition", "Additions at fair value"),
           ("sd_unwinding", "Unwinding (interest income)"), ("sd_refund", "Refunds (carrying)"),
           ("sd_close", "Closing carrying amount"), ("sd_nominal_close", "Nominal balance refundable")]


def export_lease_workbook(res: LeaseResult, path, basis_text=""):
    L = res.lease
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"Lease {L.lease_id} - {L.location} - Ind AS 116 workings"])
    ws["A1"].font = Font(bold=True, size=13)
    info = [("Agreement number", L.agreement_no), ("Landlord", L.landlord), ("Entity", L.entity),
            ("Commencement date", L.commencement), ("Lease end date (original)", L.end_date),
            ("Payment frequency (months)", L.frequency_months), ("Payment terms", L.timing),
            ("Monthly rent at commencement", L.monthly_rent), ("Discount rate / IBR % p.a.", L.annual_rate),
            ("Monthly rate used", res.summary["monthly_rate"]), ("Time / rate convention", basis_text),
            ("Rent-free months", L.rent_free_months), ("Initial lease liability", res.summary["initial_liability"]),
            ("Prepaid lease rentals", L.prepaid), ("Initial direct costs", L.idc),
            ("Restoration provision", L.restoration), ("Lease incentives received", -L.incentives),
            ("Other initial adjustments", L.other_adj), ("Initial ROU asset", res.summary["initial_rou"]),
            ("Total lease payments (accounted)", res.summary["total_lease_payments"]),
            ("Total interest over the lease", res.summary["total_interest"]),
            ("Total depreciation over the lease", res.summary["total_depreciation"])]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(row=i, column=1, value=k).font = BOLD
        c = ws.cell(row=i, column=2, value=_cell_value(v))
        if isinstance(c.value, date):
            c.number_format = DATE_FMT
        elif isinstance(c.value, float):
            c.number_format = "0.000000000" if k == "Monthly rate used" else NUM
    if res.warnings:
        ws.cell(row=len(info) + 4, column=1, value="Warnings").font = BOLD
        for j, w in enumerate(res.warnings):
            ws.cell(row=len(info) + 5 + j, column=1, value=w)
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 30

    st = wb.create_sheet("Rent steps")
    _header(st, 1, ["Version", "Effective date", "Escalation type", "Escalation %", "Absolute amount",
                    "Existing rent", "Revised rent", "Next escalation date", "Frequency (months)", "Remarks",
                    "Agreement ref"])
    rows = []
    for v in res.versions:
        for s in v.steps:
            rows.append([v.label, s.step_date, s.esc_type, s.pct, s.amount, s.existing_rent, s.revised_rent,
                         s.next_date, s.frequency_months, s.remarks, s.agreement_ref])
    _write_rows(st, 2, rows, ["text", "date", "text", "decimal", "decimal", "decimal", "decimal", "date", "int",
                              "text", "text"])
    _autosize(st)

    ps = wb.create_sheet("Payment schedule")
    _header(ps, 1, ["Version", "Period", "Period start", "Period end", "Payment due date", "Advance / Arrears",
                    "Opening rent (p.m.)", "Escalation amount", "Revised rent (p.m.)", "Months", "Rent-free months",
                    "Eligible lease payment", "Non-lease component", "GST", "Total payable", "Accounted"])
    eff = {id(p) for p in res.effective_payments}
    _write_rows(ps, 2, [[p.version_label, p.period_no, p.period_start, p.period_end, p.due_date, p.timing,
                         p.opening_rent, p.escalation_amount, p.revised_rent, p.months, p.rent_free_months,
                         p.eligible_payment, p.non_lease, p.gst, p.total_payable,
                         "Yes" if id(p) in eff else "Superseded"] for p in res.payments],
                ["text", "int", "date", "date", "date", "text", "decimal", "decimal", "decimal", "int", "int",
                 "decimal", "decimal", "decimal", "decimal", "text"])
    _autosize(ps)

    pv = wb.create_sheet("Initial PV workings")
    pv.append(["Monthly rate", float(res.summary["monthly_rate"])])
    pv["B1"].number_format = "0.000000000"
    pv.append(["Formula check: PV = payment / (1 + monthly rate) ^ t (t = months from commencement)"])
    _header(pv, 3, ["Period", "Period start", "Period end", "Due date", "Monthly rent", "Lease payment",
                    "t (months)", "Discount factor (engine)", "Present value (engine)", "PV - Excel formula",
                    "Difference"])
    r0 = 4
    for i, w in enumerate(res.initial_workings):
        r = r0 + i
        _write_rows(pv, r, [[w["period_no"], w["period_start"], w["period_end"], w["due_date"], w["monthly_rent"],
                             w["payment"], w["t_months"], w["discount_factor"], w["present_value"]]],
                    ["int", "date", "date", "date", "decimal", "decimal", "decimal", "decimal", "decimal"])
        pv.cell(row=r, column=7).number_format = "0.000000"
        pv.cell(row=r, column=8).number_format = "0.0000000000"
        c = pv.cell(row=r, column=10, value=f"=F{r}/(1+$B$1)^G{r}")
        c.number_format = NUM
        c = pv.cell(row=r, column=11, value=f"=ROUND(J{r}-I{r},2)")
        c.number_format = NUM
    rt = r0 + len(res.initial_workings)
    pv.cell(row=rt, column=5, value="Total").font = BOLD
    for col in (6, 9, 10, 11):
        c = pv.cell(row=rt, column=col, value=f"=SUM({get_column_letter(col)}{r0}:{get_column_letter(col)}{rt - 1})")
        c.font = BOLD
        c.number_format = NUM
    _autosize(pv, max_w=24)

    for title, cols in (("Lease liability schedule", LIAB_COLS), ("ROU asset schedule", ROU_COLS),
                        ("Security deposit schedule", SD_COLS)):
        sh = wb.create_sheet(title)
        _header(sh, 1, ["Month", "Financial year"] + [h for _, h in cols])
        from ..engine.dates import financial_year
        _write_rows(sh, 2, [[row.month.strftime("%b-%Y"), financial_year(row.month)] +
                            [row.values[k] for k, _ in cols] for row in res.months],
                    ["text", "text"] + ["decimal"] * len(cols))
        _autosize(sh, max_w=22)

    ev = wb.create_sheet("Events")
    _header(ev, 1, ["Date", "Event", "Reference", "Description", "Amounts"])
    for e in res.events:
        ev.append([e.event_date, e.kind, e.ref, e.description,
                   "; ".join(f"{k}={v}" for k, v in e.amounts.items() if k != "pv_exact")])
        ev.cell(row=ev.max_row, column=1).number_format = DATE_FMT
    _autosize(ev, max_w=120)
    wb.save(path)
    return path


def export_rows(headers, rows, path, title="Export", ftypes=None):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    _header(ws, 1, headers)
    _write_rows(ws, 2, rows, ftypes)
    _autosize(ws)
    wb.save(path)
    return path


def export_all_master_data(repo: Repository, path):
    wb = Workbook()
    wb.remove(wb.active)
    for name in ("lease_master", "escalations", "modifications", "terminations", "deposits", "payment_actuals",
                 "gl_balances"):
        reg = REGISTERS[name]
        ws = wb.create_sheet(reg.title[:31])
        _header(ws, 1, [f.label for f in reg.fields])
        _write_rows(ws, 2, [[r.get(f.key) for f in reg.fields] for r in repo.list_rows(reg)],
                    [f.ftype for f in reg.fields])
        _autosize(ws)
    au = wb.create_sheet("Audit log")
    rows = repo.audit_rows(limit=100000)
    _header(au, 1, ["Timestamp", "User", "Table", "Record", "Action", "Previous values", "Revised values", "Reason"])
    for r in rows:
        au.append([r["ts"], r["user"], r["table_name"], r["record_key"], r["action"], r["old_values"],
                   r["new_values"], r["reason"]])
    _autosize(au, max_w=60)
    wb.save(path)
    return path


def export_consolidated_schedules(results: dict, path):
    """Portfolio-level monthly roll-forward (all leases) - liability, ROU and deposits."""
    months = sorted({r.month for res in results.values() for r in res.months})
    wb = Workbook()
    ws = wb.active
    ws.title = "Consolidated"
    keys = [k for k, _ in LIAB_COLS + ROU_COLS + SD_COLS]
    heads = [h for _, h in LIAB_COLS + ROU_COLS + SD_COLS]
    _header(ws, 1, ["Month"] + heads)
    rows = []
    for m in months:
        tot = {k: ZERO for k in keys}
        for res in results.values():
            row = res.month(m)
            if row:
                for k in keys:
                    tot[k] += row.values[k]
        rows.append([m.strftime("%b-%Y")] + [tot[k] for k in keys])
    _write_rows(ws, 2, rows, ["text"] + ["decimal"] * len(keys))
    _autosize(ws, max_w=20)
    lw = wb.create_sheet("Lease-wise")
    _header(lw, 1, ["Lease ID", "Month"] + heads)
    rows = []
    for lid, res in results.items():
        for row in res.months:
            rows.append([lid, row.month.strftime("%b-%Y")] + [row.values[k] for k in keys])
    _write_rows(lw, 2, rows, ["text", "text"] + ["decimal"] * len(keys))
    _autosize(lw, max_w=20)
    wb.save(path)
    return path
