"""All desktop screens (one class per navigation section)."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QFileDialog,
                               QCheckBox)

from ..db.repository import ValidationError
from ..engine.dates import add_months, month_start, ym
from ..engine.decimal_utils import D, ZERO, fmt_inr
from ..engine.journals import DEFAULT_ACCOUNTS, JOURNAL_TYPES
from ..excel import workbook as xl
from ..registers import REGISTERS, parse_date
from .widgets import (RecordDialog, SearchableTable, button, confirm, error, fmt_value, hbox, html_table, info,
                      kpi_card, open_file_dialog, save_file_dialog)

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def open_path(p):
    try:
        if os.name == "nt":
            os.startfile(str(p))  # noqa
    except Exception:
        pass


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.svc = app.svc
        self.repo = app.svc.repo
        self.root = QVBoxLayout(self)
        head = QLabel(self.title)
        head.setObjectName("pageTitle")
        self.root.addWidget(head)
        if self.subtitle:
            s = QLabel(self.subtitle)
            s.setObjectName("pageSub")
            s.setWordWrap(True)
            self.root.addWidget(s)

    def refresh(self):
        pass


class MonthPicker(QWidget):
    def __init__(self, initial: date | None = None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.month = QComboBox()
        self.month.addItems(MONTHS)
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        d = initial or date.today()
        self.month.setCurrentIndex(d.month - 1)
        self.year.setValue(d.year)
        lay.addWidget(QLabel("Month"))
        lay.addWidget(self.month)
        lay.addWidget(QLabel("Year"))
        lay.addWidget(self.year)

    def value(self) -> date:
        return date(self.year.value(), self.month.currentIndex() + 1, 1)


# =========================================================================== dashboard
class DashboardPage(Page):
    title = "Dashboard"
    subtitle = "Portfolio position as at the selected month end. (Full dashboard and disclosures: Phase 4.)"

    def __init__(self, app):
        super().__init__(app)
        self.picker = MonthPicker(date(2027, 4, 1))
        self.root.addWidget(hbox(self.picker, button("Refresh", self.refresh, True)))
        self.grid = QGridLayout()
        gw = QWidget()
        gw.setLayout(self.grid)
        self.root.addWidget(gw)
        tabs = QTabWidget()
        self.expiries = SearchableTable([("lease_id", "Lease ID", ""), ("location", "Location", ""),
                                         ("end", "Lease end", "date"), ("days", "Days to expiry", "int")], search=False)
        self.escal = SearchableTable([("lease_id", "Lease ID", ""), ("date", "Escalation date", "date"),
                                      ("type", "Type", ""), ("existing", "Existing rent", "money"),
                                      ("revised", "Revised rent", "money")], search=False)
        self.refunds = SearchableTable([("lease_id", "Lease ID", ""), ("ref", "Deposit ref", ""),
                                        ("date", "Expected refund", "date"), ("amount", "Amount", "money")],
                                       search=False)
        tabs.addTab(self.expiries, "Upcoming lease expiries (12 months)")
        tabs.addTab(self.escal, "Upcoming rent escalations (6 months)")
        tabs.addTab(self.refunds, "Pending deposit refunds (12 months)")
        self.root.addWidget(tabs, 1)
        self.picker.month.currentIndexChanged.connect(self.refresh)
        self.picker.year.valueChanged.connect(self.refresh)

    def refresh(self):
        m = self.picker.value()
        snap = self.svc.portfolio_snapshot(m)
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        c = snap["counts"]
        cards = [
            ("Active leases", str(c["Active"]), f"New this month: {c['New']}"),
            ("Expired / terminated", f"{c['Expired']} / {c['Terminated']}", f"Modified this month: {c['Modified']}"),
            ("Not yet commenced", str(c["Not commenced"]), ""),
            ("ROU asset (net)", fmt_inr(snap["rou"], 0), ""),
            ("Lease liability", fmt_inr(snap["liability"], 0),
             f"Current {fmt_inr(snap['current'], 0)} | Non-current {fmt_inr(snap['non_current'], 0)}"),
            ("Security deposits (carrying)", fmt_inr(snap["sd_carrying"], 0), f"Nominal {fmt_inr(snap['sd_nominal'], 0)}"),
            ("Depreciation (month)", fmt_inr(snap["depreciation"], 0), ""),
            ("Interest (month)", fmt_inr(snap["interest"], 0), f"SD unwinding {fmt_inr(snap['sd_unwinding'], 0)}"),
            ("Lease rentals due (month)", fmt_inr(snap["rent"], 0), ""),
        ]
        for i, (t, v, s) in enumerate(cards):
            self.grid.addWidget(kpi_card(t, v, s), i // 3, i % 3)
        results = self.svc.calculate_all()
        exp, esc, refs = [], [], []
        for lid, res in results.items():
            v = res.versions[-1]
            terminated = any(e.kind == "TERMINATION" for e in res.events)
            if not terminated and m <= v.end_date <= add_months(m, 12):
                exp.append({"lease_id": lid, "location": res.lease.location, "end": v.end_date,
                            "days": (v.end_date - m).days})
            for ver in res.versions[-1:]:
                for s in ver.steps:
                    if m <= s.step_date < add_months(m, 6) and not terminated:
                        esc.append({"lease_id": lid, "date": s.step_date, "type": s.esc_type,
                                    "existing": s.existing_rent, "revised": s.revised_rent})
            for dm in res.lease.deposits:
                if dm.kind == "Refund":
                    continue
                rd = dm.expected_refund_date or res.versions[-1].end_date
                refunded = sum((x.amount for x in res.lease.deposits if x.kind == "Refund"), ZERO)
                if m <= rd <= add_months(m, 12) and refunded < sum((x.amount for x in res.lease.deposits
                                                                    if x.kind != "Refund"), ZERO):
                    refs.append({"lease_id": lid, "ref": dm.ref, "date": rd, "amount": dm.amount})
        self.expiries.set_rows(sorted(exp, key=lambda r: r["end"]))
        self.escal.set_rows(sorted(esc, key=lambda r: r["date"]))
        self.refunds.set_rows(sorted(refs, key=lambda r: r["date"]))


# =========================================================================== generic register page
class RegisterPage(Page):
    def __init__(self, app, reg_name, subtitle=""):
        self.reg = REGISTERS[reg_name]
        self.title = self.reg.title
        self.subtitle = subtitle
        super().__init__(app)
        cols = [(k, self.reg.field(k).label, self.reg.field(k).ftype) for k in (self.reg.list_columns or self.reg.keys)]
        self.table = SearchableTable(cols)
        self.lease_filter = QComboBox()
        self.lease_filter.currentIndexChanged.connect(self.refresh)
        bar = [button("Add", self.add, True), button("Edit", self.edit), button("Delete", self.delete),
               button("Import Excel", self.import_excel), button("Download template", self.template),
               button("Export to Excel", self.export)]
        if self.reg.child_of_lease:
            bar = ["Lease", self.lease_filter] + bar
        self.root.addWidget(hbox(*bar))
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        self.detail = QTextBrowser()
        split.addWidget(self.detail)
        split.setSizes([480, 260])
        self.root.addWidget(split, 1)
        self.table.view.doubleClicked.connect(lambda _: self.edit())
        self.table.view.selectionModel().selectionChanged.connect(lambda *_: self.show_detail())

    def refresh(self):
        if self.reg.child_of_lease:
            cur = self.lease_filter.currentText()
            self.lease_filter.blockSignals(True)
            self.lease_filter.clear()
            self.lease_filter.addItems(["All leases"] + self.repo.lease_ids())
            if cur:
                self.lease_filter.setCurrentText(cur)
            self.lease_filter.blockSignals(False)
        lid = self.lease_filter.currentText() if self.reg.child_of_lease else None
        rows = self.repo.list_rows(self.reg, None if lid in (None, "", "All leases") else lid)
        self.table.set_rows(rows)
        self.show_detail()

    def current_lease(self):
        t = self.lease_filter.currentText()
        return None if t in ("", "All leases") else t

    def add(self):
        preset = {"lease_id": self.current_lease()} if self.reg.child_of_lease and self.current_lease() else None
        dlg = RecordDialog(self.repo, self.reg, None, self, preset)
        if dlg.exec():
            self.refresh()

    def edit(self):
        row = self.table.selected_row()
        if not row:
            return info(self, "Edit", "Select a record first.")
        dlg = RecordDialog(self.repo, self.reg, row, self)
        if dlg.exec():
            self.refresh()

    def delete(self):
        row = self.table.selected_row()
        if not row:
            return info(self, "Delete", "Select a record first.")
        key = row[self.reg.key]
        extra = "\n\nAll escalations, modifications, terminations and deposits of this lease will also be deleted." \
            if self.reg.name == "lease_master" else ""
        if not confirm(self, "Confirm delete", f"Delete {self.reg.title} record '{key}'?{extra}"):
            return
        reason, ok = QInputDialog.getText(self, "Reason", "Reason for deletion (audit trail):")
        if not ok or not reason.strip():
            return info(self, "Delete", "Deletion cancelled - a reason is required.")
        try:
            self.repo.delete(self.reg, key, reason)
        except ValidationError as e:
            return error(self, "Cannot delete", "\n".join(e.errors))
        self.refresh()

    def import_excel(self):
        path = open_file_dialog(self, f"Import {self.reg.title}")
        if not path:
            return
        upd = confirm(self, "Existing records", "Update records that already exist (matched on "
                      f"{self.reg.field(self.reg.key).label})?\n\nNo = existing keys are reported as duplicates.")
        res = xl.import_register(self.repo, self.reg, path, update_existing=upd)
        if res.ok:
            info(self, "Import complete", f"{res.imported} record(s) imported successfully.")
        else:
            error(self, "Import failed - nothing was imported",
                  f"{len(res.errors)} error(s) found. First errors:\n\n" +
                  "\n".join(f"Row {r} {k}: {m}" for r, k, m in res.errors[:12]) +
                  f"\n\nFull error report saved to:\n{res.error_report}")
            open_path(res.error_report)
        self.refresh()

    def template(self):
        path = save_file_dialog(self, "Save template", f"{self.reg.title.replace(' ', '_')}_Template.xlsx")
        if path:
            from .. import sample_data as sd
            ex = {"lease_master": [{**sd.COMMON, **r} for r in sd.LEASES[:3]], "escalations": sd.ESCALATIONS[:4],
                  "modifications": sd.MODIFICATIONS, "terminations": sd.TERMINATIONS,
                  "deposits": [dict(r, refundable="Refundable", interest_type="Interest-free",
                                    approval_status="Approved") for r in sd.DEPOSITS[:5]]}.get(self.reg.name)
            xl.write_template(self.reg, path, ex)
            info(self, "Template saved", path)

    def export(self):
        path = save_file_dialog(self, "Export", f"{self.reg.title.replace(' ', '_')}.xlsx")
        if path:
            rows = self.table.visible_rows()
            xl.export_rows([f.label for f in self.reg.fields], [[r.get(f.key) for f in self.reg.fields] for r in rows],
                           path, self.reg.title, [f.ftype for f in self.reg.fields])
            info(self, "Exported", path)

    # ---------- detail panel (computed information for the selected record)
    def show_detail(self):
        row = self.table.selected_row()
        try:
            self.detail.setHtml(self.detail_html(row) if row else "<i>Select a record to see its calculated details.</i>")
        except Exception as exc:  # calculation problems should not crash the screen
            self.detail.setHtml(f"<b>Could not calculate:</b> {exc}")

    def detail_html(self, row):
        return ""


class LeaseMasterPage(RegisterPage):
    def __init__(self, app):
        super().__init__(app, "lease_master", "Add, edit, view and search leases. Lease ID is auto-generated. "
                                              "Double-click a row to edit.")

    def detail_html(self, row):
        res = self.svc.calculate(row["lease_id"])
        s = res.summary
        L = res.lease
        items = [("Initial lease liability", s["initial_liability"]), ("Prepaid lease rentals", L.prepaid),
                 ("Initial direct costs", L.idc), ("Restoration provision", L.restoration),
                 ("Lease incentives (less)", -L.incentives), ("Other adjustments", L.other_adj),
                 ("Initial ROU asset", s["initial_rou"]), ("Lease term (months)", s["lease_term_months"]),
                 ("Total lease payments", s["total_lease_payments"]), ("Total interest", s["total_interest"]),
                 ("Total depreciation", s["total_depreciation"])]
        warn = "".join(f"<p style='color:#C00000'>⚠ {w}</p>" for w in res.warnings)
        return f"<h3>{row['lease_id']} - {row['location']}</h3>{warn}" + html_table(["Item", "Amount"], items)


class EscalationPage(RegisterPage):
    def __init__(self, app):
        super().__init__(app, "escalations",
                         "Contractual escalations (percentage or absolute amount). A rule repeats every 'frequency' "
                         "months until the next rule. Escalations in the original agreement are included in the "
                         "initial lease liability. Subsequent contractual changes must go through Modifications.")

    def detail_html(self, row):
        res = self.svc.calculate(row["lease_id"])
        rows = []
        for v in res.versions:
            for s in v.steps:
                rows.append([v.label, s.step_date, s.esc_type, s.pct if s.esc_type == "Percentage" else "",
                             s.amount if s.esc_type != "Percentage" else "", s.existing_rent, s.revised_rent,
                             s.next_date or "", s.agreement_ref])
        return (f"<h3>Expanded rent steps - {row['lease_id']} (base rent {fmt_inr(res.lease.monthly_rent)})</h3>" +
                html_table(["Version", "Effective date", "Type", "%", "Amount", "Existing rent", "Revised rent",
                            "Next escalation", "Agreement ref"], rows))


def _event_html(res, ref):
    ev = next((e for e in res.events if e.ref == ref), None)
    if ev is None:
        return "<i>Not yet accounted - only <b>Approved</b> records within the lease term are calculated.</i>"
    rows = [[k.replace("_", " ").capitalize().replace("Rou ", "ROU ").replace(" rou", " ROU")
             .replace("accdep", "accumulated depreciation").replace(" pct", " %"), v]
            for k, v in ev.amounts.items() if k not in ("pv_exact",)]
    return f"<h3>{ev.description} ({ev.ref}) on {ev.event_date:%d-%m-%Y}</h3>" + html_table(["Item", "Value"], rows)


class ModificationPage(RegisterPage):
    def __init__(self, app):
        super().__init__(app, "modifications",
                         "Modifications not accounted for as a separate lease are remeasured at the revised discount "
                         "rate (Ind AS 116.45). Decreases in scope (area / term) are partially derecognised with a "
                         "gain or loss (46(a)); other changes adjust the ROU asset (46(b)). Only Approved records are "
                         "accounted. The original calculation is retained as version 'Original'.")

    def detail_html(self, row):
        return _event_html(self.svc.calculate(row["lease_id"]), row["mod_ref"])


class TerminationPage(RegisterPage):
    def __init__(self, app):
        super().__init__(app, "terminations",
                         "Full termination derecognises the ROU asset and lease liability; the difference less the "
                         "termination payment is a gain / loss. Partial termination is a decrease in scope.")

    def detail_html(self, row):
        return _event_html(self.svc.calculate(row["lease_id"]), row["term_ref"])


class DepositPage(RegisterPage):
    def __init__(self, app):
        super().__init__(app, "deposits",
                         "Original deposits, additional deposits and refunds. Refundable interest-free deposits are "
                         "measured at fair value (PV of refund) and unwound to the refund amount; the discount is a "
                         "prepaid lease payment added to the ROU asset. Additional deposits are NOT treated as lease "
                         "modifications.")

    def detail_html(self, row):
        res = self.svc.calculate(row["lease_id"])
        ev = _event_html(res, row["deposit_ref"])
        bal, rows = ZERO, []
        for dm in sorted(res.lease.deposits, key=lambda x: x.movement_date):
            opening = bal
            bal += -dm.amount if dm.kind == "Refund" else dm.amount
            rows.append([dm.ref, dm.movement_date, dm.kind, opening, dm.amount if dm.kind != "Refund" else "",
                         dm.amount if dm.kind == "Refund" else "", bal,
                         "Interest-free" if dm.interest_free else "Interest-bearing",
                         dm.expected_refund_date or res.versions[-1].end_date])
        today = month_start(date.today())
        r = res.month(today)
        carrying = f"<p>Carrying amount (amortised cost) at {today:%b-%Y}: <b>{fmt_inr(r.values['sd_close'])}</b></p>" \
            if r else ""
        return (f"<h3>Security deposit summary - {row['lease_id']}</h3>" +
                html_table(["Reference", "Date", "Type", "Existing balance", "Addition", "Refund", "Closing balance",
                            "Interest", "Expected refund"], rows) + carrying + "<br>" + ev)


# =========================================================================== payment schedule
class PaymentSchedulePage(Page):
    title = "Lease Payment Schedule"
    subtitle = ("Generated automatically from the lease terms and escalation register. Upload actual payments "
                "(date / amount) through Excel to track payment status. Superseded rows belong to terms replaced by a "
                "modification or termination.")

    def __init__(self, app):
        super().__init__(app)
        self.lease = QComboBox()
        self.lease.currentIndexChanged.connect(self.load)
        self.root.addWidget(hbox("Lease", self.lease, button("Export to Excel", self.export, True),
                                 button("Upload actual payments", self.upload),
                                 button("Download actuals template", self.template)))
        self.table = SearchableTable([
            ("lease_id", "Lease ID", ""), ("version", "Version", ""), ("period_no", "Period", "int"),
            ("month", "Month", ""), ("due_date", "Payment due date", "date"), ("timing", "Advance / Arrears", ""),
            ("opening_rent", "Opening rent", "money"), ("escalation", "Escalation amount", "money"),
            ("revised_rent", "Revised rent", "money"), ("rent_free", "Rent-free months", "int"),
            ("eligible", "Eligible lease payment", "money"), ("non_lease", "Non-lease component", "money"),
            ("gst", "GST", "money"), ("total", "Total payable", "money"), ("status", "Payment status", ""),
            ("actual_date", "Actual payment date", "date"), ("actual_amount", "Actual amount", "money"),
            ("accounted", "Accounted", "")])
        self.table.model.highlight = lambda r: QColor("#F2F2F2") if r.get("accounted") != "Yes" else None
        self.root.addWidget(self.table, 1)

    def refresh(self):
        cur = self.lease.currentText()
        self.lease.blockSignals(True)
        self.lease.clear()
        self.lease.addItems(self.repo.lease_ids())
        if cur:
            self.lease.setCurrentText(cur)
        self.lease.blockSignals(False)
        self.load()

    def rows(self):
        lid = self.lease.currentText()
        if not lid:
            return []
        res = self.svc.calculate(lid)
        actuals = {}
        for a in self.repo.list_rows("payment_actuals", lid):
            actuals.setdefault(a["due_date"], []).append(a)
        eff = {id(p) for p in res.effective_payments}
        out = []
        today = date.today()
        for p in res.payments:
            acts = actuals.get(p.due_date.isoformat(), [])
            paid = sum((D(a["actual_amount"]) for a in acts), ZERO)
            if id(p) not in eff:
                status = "Superseded"
            elif paid >= p.total_payable and p.total_payable > 0:
                status = "Paid"
            elif paid > 0:
                status = "Partially paid"
            elif p.total_payable == 0:
                status = "Rent-free"
            else:
                status = "Unpaid - overdue" if p.due_date < today else "Not yet due"
            out.append({"lease_id": lid, "version": p.version_label, "period_no": p.period_no,
                        "month": p.period_start.strftime("%b-%Y"), "due_date": p.due_date, "timing": p.timing,
                        "opening_rent": p.opening_rent, "escalation": p.escalation_amount,
                        "revised_rent": p.revised_rent, "rent_free": p.rent_free_months, "eligible": p.eligible_payment,
                        "non_lease": p.non_lease, "gst": p.gst, "total": p.total_payable, "status": status,
                        "actual_date": acts[-1]["actual_payment_date"] if acts else None,
                        "actual_amount": paid if acts else None,
                        "accounted": "Yes" if id(p) in eff else "Superseded"})
        return out

    def load(self):
        self.table.set_rows(self.rows())

    def export(self):
        path = save_file_dialog(self, "Export payment schedule", f"Payment_Schedule_{self.lease.currentText()}.xlsx")
        if path:
            cols = self.table.model.columns
            xl.export_rows([c[1] for c in cols], [[r.get(c[0]) for c in cols] for r in self.rows()], path,
                           "Payment schedule", ["money" == c[2] and "decimal" or c[2] for c in cols])
            info(self, "Exported", path)

    def template(self):
        path = save_file_dialog(self, "Actuals template", f"Payment_Actuals_{self.lease.currentText()}.xlsx")
        if not path:
            return
        reg = REGISTERS["payment_actuals"]
        rows = [{"payment_ref": f"{r['lease_id']}-{r['due_date']:%Y%m%d}", "lease_id": r["lease_id"],
                 "due_date": r["due_date"]} for r in self.rows() if r["accounted"] == "Yes"]
        xl.write_template(reg, path)
        from openpyxl import load_workbook
        wb = load_workbook(path)
        ws = wb["Data"]
        for i, r in enumerate(rows, 2):
            ws.cell(row=i, column=1, value=r["payment_ref"])
            ws.cell(row=i, column=2, value=r["lease_id"])
            c = ws.cell(row=i, column=3, value=r["due_date"])
            c.number_format = "DD-MMM-YYYY"
        wb.save(path)
        info(self, "Template saved", f"{path}\n\nFill actual payment date and amount, then use 'Upload actual payments'.")

    def upload(self):
        path = open_file_dialog(self, "Upload actual payments")
        if not path:
            return
        res = xl.import_register(self.repo, "payment_actuals", path, update_existing=True)
        if res.ok:
            info(self, "Upload complete", f"{res.imported} payment record(s) updated.")
        else:
            error(self, "Upload failed", "\n".join(f"Row {r}: {m}" for r, _, m in res.errors[:12]) +
                  f"\n\nError report: {res.error_report}")
        self.load()


# =========================================================================== calculations
class CalculationsPage(Page):
    title = "Lease Calculations"
    subtitle = "Lease-wise Ind AS 116 workings: initial measurement, liability (effective interest), ROU and deposits."

    def __init__(self, app):
        super().__init__(app)
        self.lease = QComboBox()
        self.lease.currentIndexChanged.connect(self.load)
        self.root.addWidget(hbox("Lease", self.lease, button("Export lease workings to Excel", self.export, True),
                                 button("Export consolidated schedules (all leases)", self.export_all)))
        self.tabs = QTabWidget()
        self.summary = QTextBrowser()
        self.pv = SearchableTable([("period_no", "Period", "int"), ("due_date", "Due date", "date"),
                                   ("monthly_rent", "Monthly rent", "money"), ("payment", "Lease payment", "money"),
                                   ("t_months", "t (months)", ""), ("discount_factor", "Discount factor", ""),
                                   ("present_value", "Present value", "money")], search=False)
        from ..excel.workbook import LIAB_COLS, ROU_COLS, SD_COLS
        mk = lambda cols: SearchableTable([("month", "Month", "")] + [(k, h, "money") for k, h in cols], search=False)
        self.liab, self.rou, self.sd = mk(LIAB_COLS), mk(ROU_COLS), mk(SD_COLS)
        self.events = QTextBrowser()
        for w, t in ((self.summary, "Summary"), (self.pv, "Initial PV workings"), (self.liab, "Lease liability"),
                     (self.rou, "ROU asset"), (self.sd, "Security deposit"), (self.events, "Events")):
            self.tabs.addTab(w, t)
        self.root.addWidget(self.tabs, 1)

    def refresh(self):
        cur = self.lease.currentText()
        self.lease.blockSignals(True)
        self.lease.clear()
        self.lease.addItems(self.repo.lease_ids())
        if cur:
            self.lease.setCurrentText(cur)
        self.lease.blockSignals(False)
        self.load()

    def load(self):
        lid = self.lease.currentText()
        if not lid:
            return
        res = self.svc.calculate(lid)
        L, s = res.lease, res.summary
        basis = self.svc.basis()
        items = [("Commencement", L.commencement), ("Lease end (current terms)", res.versions[-1].end_date),
                 ("IBR % p.a.", L.annual_rate),
                 ("Monthly rate", f"{s['monthly_rate']:.9f} ({basis.rate_basis}, {basis.time_basis} time basis)"),
                 ("Payment terms", f"Every {L.frequency_months} month(s) in {L.timing.lower()}"),
                 ("Present value of lease payments = initial lease liability", s["initial_liability"]),
                 ("Add: prepaid lease rentals", L.prepaid), ("Add: initial direct costs", L.idc),
                 ("Add: restoration / dismantling provision", L.restoration),
                 ("Less: lease incentives received", -L.incentives), ("Add: other adjustments", L.other_adj),
                 ("Initial ROU asset", s["initial_rou"]),
                 ("Total lease payments accounted", s["total_lease_payments"]),
                 ("Total interest", s["total_interest"]), ("Total depreciation", s["total_depreciation"])]
        warn = "".join(f"<p style='color:#C00000'>⚠ {w}</p>" for w in res.warnings)
        ver = "".join(f"<li>{v.label}: from {v.anchor:%d-%m-%Y} to {v.end_date:%d-%m-%Y}, base rent "
                      f"{fmt_inr(v.base_rent)}, IBR {v.annual_rate}%</li>" for v in res.versions)
        self.summary.setHtml(f"<h3>{lid} - {L.location}</h3>{warn}" + html_table(["Item", "Value"], items) +
                             f"<h4>Calculation versions</h4><ul>{ver}</ul>")
        self.pv.set_rows([dict(w, t_months=f"{w['t_months']:.4f}", discount_factor=f"{w['discount_factor']:.8f}")
                          for w in res.initial_workings])
        rows = [dict(r.values, month=r.month.strftime("%b-%Y"), _sort_month=r.month.isoformat()) for r in res.months]
        for t in (self.liab, self.rou, self.sd):
            t.set_rows(rows)
        self.events.setHtml("".join(_event_html(res, e.ref) + "<br>" for e in res.events if e.kind != "INIT"))

    def export(self):
        lid = self.lease.currentText()
        path = save_file_dialog(self, "Export workings", f"Lease_Workings_{lid}.xlsx")
        if path:
            b = self.svc.basis()
            xl.export_lease_workbook(self.svc.calculate(lid), path, f"{b.time_basis} / {b.rate_basis}")
            info(self, "Exported", path)

    def export_all(self):
        path = save_file_dialog(self, "Export consolidated schedules", "Consolidated_Lease_Schedules.xlsx")
        if path:
            xl.export_consolidated_schedules(self.svc.calculate_all(), path)
            info(self, "Exported", path)


# =========================================================================== monthly accounting
class MonthlyAccountingPage(Page):
    title = "Monthly Accounting / Month-End Closure"
    subtitle = ("Select a month and click 'Generate monthly entries'. All journals are balanced and stored as a "
                "Draft batch; duplicate generation is blocked once a batch is Approved or Posted. "
                "(Full 14-step closure workflow and GL reconciliation: Phase 3.)")

    def __init__(self, app):
        super().__init__(app)
        self.picker = MonthPicker(date(2027, 4, 1))
        self.status = QLabel()
        self.status.setObjectName("batchStatus")
        self.root.addWidget(hbox(self.picker, button("Generate monthly entries", self.generate, True),
                                 button("Regenerate draft", self.regenerate), button("Approve", self.approve),
                                 button("Mark as posted", self.post), button("Export Excel / ERP", self.export),
                                 None, self.status))
        self.f_lease, self.f_entity, self.f_loc, self.f_type, self.f_status = (QComboBox() for _ in range(5))
        for f in (self.f_lease, self.f_entity, self.f_loc, self.f_type, self.f_status):
            f.currentIndexChanged.connect(self.apply_filters)
        self.root.addWidget(hbox("Lease", self.f_lease, "Entity", self.f_entity, "Location", self.f_loc,
                                 "Journal type", self.f_type, "Status", self.f_status))
        self.tabs = QTabWidget()
        self.lines = SearchableTable([("lease_id", "Lease ID", ""), ("accounting_date", "Date", "date"),
                                      ("voucher_no", "Voucher", ""), ("journal_type", "Journal type", ""),
                                      ("account_code", "Account code", ""), ("account_name", "Account name", ""),
                                      ("debit", "Debit", "money"), ("credit", "Credit", "money"),
                                      ("narration", "Narration", ""), ("location", "Location", ""),
                                      ("entity", "Entity", ""), ("calc_ref", "Calculation ref", ""),
                                      ("status", "Status", "")])
        self.accounts = SearchableTable([("account_code", "Account code", ""), ("account_name", "Account name", ""),
                                         ("debit", "Debit", "money"), ("credit", "Credit", "money"),
                                         ("net", "Net (Dr + / Cr -)", "money")], search=False)
        self.bal = SearchableTable([("lease_id", "Lease ID", ""), ("location", "Location", ""),
                                    ("liab_open", "Opening liability", "money"), ("liab_close", "Closing liability", "money"),
                                    ("liab_current", "Current", "money"), ("liab_non_current", "Non-current", "money"),
                                    ("rou_open", "Opening ROU", "money"), ("rou_close", "Closing ROU", "money"),
                                    ("sd_open", "Opening SD", "money"), ("sd_close", "Closing SD (carrying)", "money"),
                                    ("sd_nominal_close", "SD nominal", "money")], search=False)
        self.tabs.addTab(self.lines, "Journal lines (lease-wise)")
        self.tabs.addTab(self.accounts, "Consolidated - account-wise summary")
        self.tabs.addTab(self.bal, "Opening / closing balances")
        self.root.addWidget(self.tabs, 1)
        self.totals = QLabel()
        self.totals.setObjectName("totals")
        self.root.addWidget(self.totals)
        self.all_lines = []
        self.picker.month.currentIndexChanged.connect(self.refresh)
        self.picker.year.valueChanged.connect(self.refresh)

    def refresh(self):
        m = self.picker.value()
        b = self.svc.batch(m)
        closed = self.svc.month_closed(m)
        if b:
            self.status.setText(f"{m:%B %Y}: batch <b>{b['status']}</b> - generated {b['generated_at']} by "
                                f"{b['generated_by']}" + (" - month CLOSED" if closed else ""))
            rows = self.svc.stored_lines(m)
            for r in rows:
                r["debit"], r["credit"] = D(r["debit"]), D(r["credit"])
        else:
            self.status.setText(f"{m:%B %Y}: no journals generated yet")
            rows = []
        self.all_lines = rows
        self._fill_filters()
        self.apply_filters()
        res = self.svc.calculate_all()
        bal = []
        tot = {}
        for lid, r in res.items():
            row = r.month(m)
            if row is None:
                continue
            d = dict(row.values, lease_id=lid, location=r.lease.location)
            bal.append(d)
            for k, v in row.values.items():
                tot[k] = tot.get(k, ZERO) + v
        if bal:
            bal.append(dict(tot, lease_id="Total", location="", _bold=True))
        self.bal.set_rows(bal)

    def _fill_filters(self):
        def fill(combo, values):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(["All"] + sorted({v for v in values if v}))
            if cur:
                combo.setCurrentText(cur)
            combo.blockSignals(False)
        fill(self.f_lease, [l["lease_id"] for l in self.all_lines])
        fill(self.f_entity, [l["entity"] for l in self.all_lines])
        fill(self.f_loc, [l["location"] for l in self.all_lines])
        fill(self.f_type, [l["journal_type"] for l in self.all_lines])
        fill(self.f_status, ["Draft", "Approved", "Posted"])

    def filtered(self):
        out = []
        for l in self.all_lines:
            ok = True
            for combo, key in ((self.f_lease, "lease_id"), (self.f_entity, "entity"), (self.f_loc, "location"),
                               (self.f_type, "journal_type"), (self.f_status, "status")):
                v = combo.currentText()
                if v and v != "All" and l[key] != v:
                    ok = False
            if ok:
                out.append(l)
        return out

    def apply_filters(self):
        rows = self.filtered()
        self.lines.set_rows(rows)
        agg = {}
        for l in rows:
            k = (l["account_code"], l["account_name"])
            d, c = agg.get(k, (ZERO, ZERO))
            agg[k] = (d + l["debit"], c + l["credit"])
        acc = [{"account_code": k[0], "account_name": k[1], "debit": d, "credit": c, "net": d - c}
               for k, (d, c) in sorted(agg.items())]
        td = sum((l["debit"] for l in rows), ZERO)
        tc = sum((l["credit"] for l in rows), ZERO)
        if acc:
            acc.append({"account_code": "", "account_name": "Total", "debit": td, "credit": tc, "net": td - tc,
                        "_bold": True})
        self.accounts.set_rows(acc)
        vouchers = len({l["voucher_no"] for l in rows})
        ok = "BALANCED ✔" if td == tc else "NOT BALANCED ✘"
        self.totals.setText(f"Lines: {len(rows)}   Vouchers: {vouchers}   Total debit: {fmt_inr(td)}   "
                            f"Total credit: {fmt_inr(tc)}   {ok if rows else ''}")

    def generate(self, regenerate=False):
        m = self.picker.value()
        try:
            lines = self.svc.generate_month(m, regenerate=regenerate)
        except ValidationError as e:
            return error(self, "Cannot generate", "\n".join(e.errors))
        self.refresh()
        info(self, "Journals generated", f"{len(lines)} journal lines generated for {m:%B %Y} "
                                         f"({len({l.voucher_no for l in lines})} vouchers) and saved as Draft.")

    def regenerate(self):
        if confirm(self, "Regenerate", "Replace the existing DRAFT journals for this month with a fresh calculation?"):
            self.generate(regenerate=True)

    def _status(self, status):
        m = self.picker.value()
        if not confirm(self, status, f"Mark all journals of {m:%B %Y} as {status}?"):
            return
        reason, ok = QInputDialog.getText(self, status, "Approval reference / remarks:")
        if not ok:
            return
        try:
            self.svc.set_batch_status(m, status, reason)
        except ValidationError as e:
            return error(self, status, "\n".join(e.errors))
        self.refresh()

    def approve(self):
        self._status("Approved")

    def post(self):
        self._status("Posted")

    def export(self):
        m = self.picker.value()
        if not self.all_lines:
            return info(self, "Export", "Generate the journals first.")
        path = save_file_dialog(self, "Export journals", f"Lease_Journals_{ym(m)}.xlsx")
        if path:
            s = self.svc.db.settings()
            xl.export_journals(self.filtered(), path, m, self.svc.calculate_all(), s.get("erp_journal_source", "LEASE"),
                               s.get("company_name", ""))
            info(self, "Exported", f"{path}\n\nSheets: Journal lines, ERP upload, Account summary, By journal type, "
                                   "Lease balances.")


# =========================================================================== placeholders for later phases
class GLReconPage(Page):
    title = "GL Reconciliation"
    subtitle = "Phase 3: upload monthly GL balances and reconcile against schedule balances."

    def __init__(self, app):
        super().__init__(app)
        self.root.addWidget(hbox(button("Download GL balance upload template", self.template, True)))
        self.root.addWidget(QLabel("The reconciliation screen (schedule balance vs GL balance, difference, reason, "
                                   "resolution status) will be delivered in Phase 3 after Phase 1 validation."))
        self.root.addStretch(1)

    def template(self):
        path = save_file_dialog(self, "GL template", "GL_Balance_Upload_Template.xlsx")
        if path:
            xl.write_gl_template(path, self.svc.db.accounts())
            info(self, "Saved", path)


class ReportsPage(Page):
    title = "Reports"
    subtitle = "Available now: consolidated schedules and journal exports. Ind AS 116 disclosures and PDF: Phase 4."

    def __init__(self, app):
        super().__init__(app)
        self.root.addWidget(hbox(button("Consolidated liability / ROU / deposit schedules (Excel)", self.sched, True),
                                 button("Export all master data (Excel)", self.master)))
        self.root.addStretch(1)

    def sched(self):
        path = save_file_dialog(self, "Export", "Consolidated_Lease_Schedules.xlsx")
        if path:
            xl.export_consolidated_schedules(self.svc.calculate_all(), path)
            info(self, "Exported", path)

    def master(self):
        path = save_file_dialog(self, "Export", "Lease_Master_Data_Export.xlsx")
        if path:
            xl.export_all_master_data(self.repo, path)
            info(self, "Exported", path)


# =========================================================================== settings
class SettingsPage(Page):
    title = "Settings - Accounting Configuration"
    subtitle = ("Accounting judgements below must be approved by Finance. Changing the time / rate convention changes "
                "every calculation; approved / posted journals already stored are never altered.")

    def __init__(self, app):
        super().__init__(app)
        g = QGroupBox("General and accounting policy")
        form = QFormLayout(g)
        self.company = QLineEdit()
        self.time_basis = QComboBox()
        self.time_basis.addItems(["monthly", "actual_365"])
        self.time_basis.setToolTip("monthly: equal monthly periods (recommended). actual_365: day count like Excel XNPV.")
        self.rate_basis = QComboBox()
        self.rate_basis.addItems(["effective", "nominal"])
        self.rate_basis.setToolTip("effective: monthly rate = (1+IBR)^(1/12)-1.  nominal: monthly rate = IBR/12.")
        self.dep_rate = QLineEdit()
        self.dep_rate.setPlaceholderText("blank = use each lease's IBR")
        self.auto_backup = QComboBox()
        self.auto_backup.addItems(["Yes", "No"])
        self.keep = QSpinBox()
        self.keep.setRange(1, 365)
        self.threshold = QLineEdit()
        self.source = QLineEdit()
        form.addRow("Company name", self.company)
        form.addRow("Currency", QLabel("INR (₹)"))
        form.addRow("Financial year", QLabel("April to March"))
        form.addRow("Time basis for discounting", self.time_basis)
        form.addRow("IBR conversion to monthly rate", self.rate_basis)
        form.addRow("Depreciation method", QLabel("Straight-line over the lease term (prospective on remeasurement)"))
        form.addRow("Default deposit discount rate % p.a.", self.dep_rate)
        form.addRow("Approval threshold (INR)", self.threshold)
        form.addRow("ERP journal source code", self.source)
        form.addRow("Automatic daily backup", self.auto_backup)
        form.addRow("Automatic backups to keep", self.keep)
        self.root.addWidget(g)
        self.root.addWidget(hbox(button("Save settings", self.save, True),
                                 button("Load sample (demo) data", self.sample),
                                 button("Download all Excel templates", self.templates)))
        g2 = QGroupBox("Journal account mapping (double-click a code or name to edit)")
        lay = QVBoxLayout(g2)
        self.acc = QTableWidget(0, 3)
        self.acc.setHorizontalHeaderLabels(["Mapping key", "Account code", "Account name"])
        self.acc.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.acc)
        lay.addWidget(hbox(button("Save account mapping", self.save_accounts, True)))
        self.root.addWidget(g2, 1)

    def refresh(self):
        s = self.svc.db.settings()
        self.company.setText(s.get("company_name", ""))
        self.time_basis.setCurrentText(s.get("time_basis", "monthly"))
        self.rate_basis.setCurrentText(s.get("rate_basis", "effective"))
        self.dep_rate.setText(s.get("default_deposit_rate", ""))
        self.auto_backup.setCurrentText(s.get("auto_backup", "Yes"))
        self.keep.setValue(int(s.get("backup_keep") or 30))
        self.threshold.setText(s.get("approval_threshold", ""))
        self.source.setText(s.get("erp_journal_source", "LEASE"))
        acc = self.svc.db.accounts()
        self.acc.setRowCount(len(acc))
        for i, (k, (code, name)) in enumerate(sorted(acc.items(), key=lambda x: x[1][0])):
            it = QTableWidgetItem(k)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.acc.setItem(i, 0, it)
            self.acc.setItem(i, 1, QTableWidgetItem(code))
            self.acc.setItem(i, 2, QTableWidgetItem(name))
        self.acc.resizeColumnsToContents()

    def save(self):
        s = self.svc.db.settings()
        new = {"company_name": self.company.text(), "time_basis": self.time_basis.currentText(),
               "rate_basis": self.rate_basis.currentText(), "default_deposit_rate": self.dep_rate.text().strip(),
               "auto_backup": self.auto_backup.currentText(), "backup_keep": str(self.keep.value()),
               "approval_threshold": self.threshold.text(), "erp_journal_source": self.source.text()}
        changed = {k: v for k, v in new.items() if s.get(k) != v}
        if not changed:
            return info(self, "Settings", "No changes.")
        reason, ok = QInputDialog.getText(self, "Reason", "Reason / Finance approval reference for this change:")
        if not ok or not reason.strip():
            return info(self, "Settings", "Not saved - a reason is required.")
        for k, v in changed.items():
            self.svc.db.set_setting(k, v, reason)
        self.svc.invalidate()
        info(self, "Settings", "Settings saved.")

    def save_accounts(self):
        reason, ok = QInputDialog.getText(self, "Reason", "Reason for account mapping change:")
        if not ok or not reason.strip():
            return
        acc = self.svc.db.accounts()
        for i in range(self.acc.rowCount()):
            k = self.acc.item(i, 0).text()
            code, name = self.acc.item(i, 1).text(), self.acc.item(i, 2).text()
            if acc.get(k) != (code, name):
                self.svc.db.set_account(k, code, name, reason)
        info(self, "Accounts", "Account mapping saved. It applies to journals generated from now on.")

    def sample(self):
        if not confirm(self, "Sample data", "Load the 8 demonstration leases (L0001-L0008)? Existing records with the "
                                            "same IDs are skipped."):
            return
        from ..sample_data import load_sample_data
        try:
            n = load_sample_data(self.repo)
        except ValidationError as e:
            return error(self, "Sample data", "\n".join(e.errors))
        info(self, "Sample data", f"{n} sample lease(s) loaded with escalations, deposits, modification and "
                                  "terminations.")

    def templates(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder for templates")
        if folder:
            files = xl.write_all_templates(Path(folder) / "Lease_Excel_Templates", self.repo)
            info(self, "Templates", "Saved:\n" + "\n".join(str(f) for f in files))


# =========================================================================== backup / audit
class BackupPage(Page):
    title = "Backup and Restore"
    subtitle = ("The database is saved on this computer. A backup is taken automatically once a day when the "
                "application starts, and before every restore.")

    def __init__(self, app):
        super().__init__(app)
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.root.addWidget(self.path_label)
        self.list = QListWidget()
        self.root.addWidget(hbox(button("Backup now", self.backup, True), button("Restore selected backup", self.restore),
                                 button("Restore from file...", self.restore_file),
                                 button("Export all master data + audit log (Excel)", self.export)))
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.list)
        self.audit = SearchableTable([("ts", "Timestamp", ""), ("user", "User", ""), ("table_name", "Table", ""),
                                      ("record_key", "Record", ""), ("action", "Action", ""),
                                      ("reason", "Reason", ""), ("old_values", "Previous values", ""),
                                      ("new_values", "Revised values", "")])
        box = QGroupBox("User-wise activity log / audit trail")
        QVBoxLayout(box).addWidget(self.audit)
        split.addWidget(box)
        split.setSizes([180, 460])
        self.root.addWidget(split, 1)

    def refresh(self):
        db = self.svc.db
        self.path_label.setText(f"Database: {db.path}\nBackup folder: {db.backup_dir}")
        self.list.clear()
        for p in db.list_backups():
            self.list.addItem(p.name)
        self.audit.set_rows(self.repo.audit_rows())

    def backup(self):
        p = self.svc.db.backup("manual")
        info(self, "Backup", f"Backup saved:\n{p}")
        self.refresh()

    def _restore(self, path):
        if not confirm(self, "Restore", f"Restore the database from\n{path}?\n\nThe current database will be backed up "
                                        "first. All screens will reload."):
            return
        try:
            self.svc.db.restore(path)
        except Exception as exc:
            return error(self, "Restore failed", str(exc))
        self.svc.invalidate()
        info(self, "Restore", "Database restored.")
        self.refresh()

    def restore(self):
        it = self.list.currentItem()
        if not it:
            return info(self, "Restore", "Select a backup first.")
        self._restore(self.svc.db.backup_dir / it.text())

    def restore_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Backup file", str(self.svc.db.backup_dir), "SQLite (*.sqlite *.db)")
        if path:
            self._restore(path)

    def export(self):
        path = save_file_dialog(self, "Export", "Lease_Master_Data_Export.xlsx")
        if path:
            xl.export_all_master_data(self.repo, path)
            info(self, "Exported", path)
