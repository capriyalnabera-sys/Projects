"""Application services: bridge between the database and the calculation engine."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from .db.database import Database
from .db.repository import Repository, ValidationError
from .engine.dates import TimeBasis, month_start, ym
from .engine.decimal_utils import D, ZERO
from .engine.journals import JournalLine, build_month_journals, check_balanced
from .engine.lease_engine import LeaseResult, calculate_lease
from .engine.models import (FREQUENCY_MONTHS, DepositMovementInput, EscalationRule, LeaseInput,
                            ModificationInput, TerminationInput)
from .registers import parse_date


def _opt_dec(v):
    return D(v) if v not in (None, "") else None


class LeaseService:
    def __init__(self, db: Database):
        self.db = db
        self.repo = Repository(db)
        self._cache = None
        self._cache_version = None

    # ------------------------------------------------------------------ inputs
    def basis(self) -> TimeBasis:
        s = self.db.settings()
        return TimeBasis(s.get("time_basis", "monthly"), s.get("rate_basis", "nominal"))

    def build_input(self, lease: dict) -> LeaseInput:
        lid = lease["lease_id"]
        settings = self.db.settings()
        esc = [EscalationRule(parse_date(r["effective_date"]), r["escalation_type"], D(r["escalation_pct"]),
                              D(r["escalation_amount"]), int(r["frequency_months"] or 0), r["remarks"] or "",
                              r["agreement_ref"] or "", r["id"])
               for r in self.repo.list_rows("escalations", lid)]
        mods = []
        for r in self.repo.list_rows("modifications", lid):
            if r["approval_status"] != "Approved":
                continue
            rev_esc = []
            if r.get("revised_escalation_type"):
                rev_esc.append(EscalationRule(parse_date(r["revised_first_escalation_date"]),
                                              r["revised_escalation_type"], D(r["revised_escalation_pct"]),
                                              D(r["revised_escalation_amount"]),
                                              int(r["revised_escalation_frequency"] or 0), f"Per {r['mod_ref']}"))
            mods.append(ModificationInput(
                r["mod_ref"], parse_date(r["effective_date"]), r["modification_type"],
                _opt_dec(r["revised_monthly_rent"]), parse_date(r["revised_end_date"]),
                _opt_dec(r["revised_discount_rate"]),
                FREQUENCY_MONTHS.get(r["revised_payment_frequency"] or ""),
                r["revised_payment_timing"] or None, D(r["area_reduction_pct"]),
                (r["keep_existing_escalations"] or "Yes") == "Yes", rev_esc, r["separate_lease"] == "Yes"))
        terms = [TerminationInput(r["term_ref"], parse_date(r["effective_date"]), r["termination_type"] == "Full",
                                  D(r["partial_pct"]), D(r["termination_payment"]),
                                  _opt_dec(r["revised_monthly_rent"]))
                 for r in self.repo.list_rows("terminations", lid) if r["approval_status"] == "Approved"]
        default_rate = settings.get("default_deposit_rate") or None
        deps = [DepositMovementInput(r["deposit_ref"], parse_date(r["movement_date"]), r["movement_type"],
                                     D(r["amount"]), r["refundable"] == "Refundable",
                                     r["interest_type"] == "Interest-free",
                                     _opt_dec(r["discount_rate"]) if r["discount_rate"] else _opt_dec(default_rate),
                                     parse_date(r["expected_refund_date"]))
                for r in self.repo.list_rows("deposits", lid) if r["approval_status"] == "Approved"]
        if not deps and D(lease.get("security_deposit")) > 0:
            deps.append(DepositMovementInput(f"{lid}-SD", parse_date(lease["commencement_date"]), "Original",
                                             D(lease["security_deposit"]), True, True, _opt_dec(default_rate), None))
        return LeaseInput(
            lid, parse_date(lease["commencement_date"]), parse_date(lease["lease_end_date"]),
            D(lease["monthly_rent"]), FREQUENCY_MONTHS.get(lease["payment_frequency"], 1),
            lease["payment_timing"] or "Advance", D(lease["discount_rate"]), int(lease["rent_free_months"] or 0),
            esc, D(lease["prepaid_lease_rentals"]), D(lease["initial_direct_costs"]), D(lease["lease_incentives"]),
            D(lease["restoration_provision"]), D(lease["other_initial_adjustments"]), D(lease["gst_rate"]),
            D(lease["non_lease_monthly"]), mods, terms, deps, lease["agreement_no"] or "", lease["entity"] or "",
            lease["location"] or "", lease["landlord_name"] or "")

    # ------------------------------------------------------------------ calculations
    def calculate_all(self) -> dict[str, LeaseResult]:
        if self._cache is not None and self._cache_version == self.db.data_version:
            return self._cache
        basis = self.basis()
        out = {}
        for lease in self.repo.list_rows("lease_master", order="lease_id"):
            out[lease["lease_id"]] = calculate_lease(self.build_input(lease), basis)
        self._cache, self._cache_version = out, self.db.data_version
        return out

    def calculate(self, lease_id: str) -> LeaseResult:
        return self.calculate_all()[lease_id]

    def invalidate(self):
        self._cache = None

    # ------------------------------------------------------------------ journals
    def batch(self, month: date):
        rows = self.db.query("SELECT * FROM journal_batches WHERE month=?", (ym(month),))
        return rows[0] if rows else None

    def month_closed(self, month: date) -> bool:
        rows = self.db.query("SELECT status FROM month_status WHERE month=?", (ym(month),))
        return bool(rows) and rows[0]["status"] == "Closed"

    def preview_month(self, month: date) -> list[JournalLine]:
        accounts = self.db.accounts()
        lines = []
        for lid, res in self.calculate_all().items():
            lines.extend(build_month_journals(res, month, accounts))
        return lines

    def generate_month(self, month: date, regenerate: bool = False) -> list[JournalLine]:
        """Generate and store Draft journals for a month.  Approved / posted batches and closed
        months are protected - duplicate generation is prevented."""
        month = month_start(month)
        key = ym(month)
        if self.month_closed(month):
            raise ValidationError([f"{month:%B %Y} is closed. Reopen the month (with approval) to regenerate."])
        existing = self.batch(month)
        if existing:
            if existing["status"] in ("Approved", "Posted"):
                raise ValidationError([f"Journals for {month:%B %Y} are already {existing['status']} - "
                                       "duplicate generation is not allowed."])
            if not regenerate:
                raise ValidationError([f"Draft journals for {month:%B %Y} already exist. "
                                       "Use 'Regenerate draft' to replace them."])
        lines = self.preview_month(month)
        bad = check_balanced(lines)
        if bad:
            raise ValidationError([f"Unbalanced vouchers: {', '.join(bad)}"])
        totals_dr = sum((l.debit for l in lines), ZERO)
        totals_cr = sum((l.credit for l in lines), ZERO)
        settings = self.db.settings()
        cur = self.db.conn.cursor()
        cur.execute("INSERT INTO calc_runs(ts, user, purpose, month, lease_count, settings, summary) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (datetime.now().isoformat(timespec="seconds"), self.db.user, "Monthly journals", key,
                     len(self.calculate_all()), json.dumps({k: settings[k] for k in ("time_basis", "rate_basis")}),
                     json.dumps({"lines": len(lines), "debit": str(totals_dr), "credit": str(totals_cr)})))
        run_id = cur.lastrowid
        cur.execute("DELETE FROM journal_lines WHERE month=? AND status='Draft'", (key,))
        for l in lines:
            cur.execute(
                "INSERT INTO journal_lines(month, accounting_date, lease_id, agreement_no, entity, location, voucher_no,"
                " account_key, account_code, account_name, narration, debit, credit, journal_type, calc_ref, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, l.accounting_date.isoformat(), l.lease_id, l.agreement_no, l.entity, l.location, l.voucher_no,
                 l.account_key, l.account_code, l.account_name, l.narration, str(l.debit), str(l.credit),
                 l.journal_type, l.calc_ref, "Draft"))
        now = datetime.now().isoformat(timespec="seconds")
        cur.execute("INSERT OR REPLACE INTO journal_batches(month, status, calc_run_id, generated_at, generated_by,"
                    " line_count, total_debit, total_credit) VALUES (?,?,?,?,?,?,?,?)",
                    (key, "Draft", run_id, now, self.db.user, len(lines), str(totals_dr), str(totals_cr)))
        self.db.conn.commit()
        self.db.audit("journal_batches", key, "REGENERATE" if existing else "GENERATE", existing,
                      {"lines": len(lines), "debit": str(totals_dr), "credit": str(totals_cr), "calc_run": run_id},
                      "Monthly journal generation")
        return lines

    def stored_lines(self, month: date) -> list[dict]:
        return self.db.query("SELECT * FROM journal_lines WHERE month=? ORDER BY lease_id, voucher_no, id",
                             (ym(month),))

    def set_batch_status(self, month: date, status: str, reason: str = ""):
        b = self.batch(month)
        if not b:
            raise ValidationError(["Generate journals first"])
        order = ["Draft", "Approved", "Posted"]
        if order.index(status) != order.index(b["status"]) + 1:
            raise ValidationError([f"Batch is {b['status']}; it can only move to the next status in "
                                   "Draft -> Approved -> Posted"])
        now = datetime.now().isoformat(timespec="seconds")
        col = "approved" if status == "Approved" else "posted"
        self.db.execute(f"UPDATE journal_batches SET status=?, {col}_at=?, {col}_by=? WHERE month=?",
                        (status, now, self.db.user, ym(month)))
        self.db.execute("UPDATE journal_lines SET status=? WHERE month=?", (status, ym(month)))
        self.db.audit("journal_batches", ym(month), status.upper(), {"status": b["status"]}, {"status": status},
                      reason)

    # ------------------------------------------------------------------ portfolio summaries
    def portfolio_snapshot(self, month: date) -> dict:
        month = month_start(month)
        res_all = self.calculate_all()
        out = {k: ZERO for k in ("rou", "liability", "current", "non_current", "sd_carrying", "sd_nominal",
                                 "depreciation", "interest", "rent", "sd_unwinding")}
        counts = {"Active": 0, "Expired": 0, "Terminated": 0, "New": 0, "Modified": 0, "Not commenced": 0}
        for lid, res in res_all.items():
            row = res.month(month)
            L = res.lease
            terminated = any(e.kind == "TERMINATION" and month_start(e.event_date) <= month for e in res.events)
            end = res.versions[-1].end_date
            if terminated:
                counts["Terminated"] += 1
            elif month_start(L.commencement) > month:
                counts["Not commenced"] += 1
            elif end < month:
                counts["Expired"] += 1
            else:
                counts["Active"] += 1
            if month_start(L.commencement) == month:
                counts["New"] += 1
            if any(e.kind in ("MODIFICATION", "PARTIAL_TERMINATION") and month_start(e.event_date) == month
                   for e in res.events):
                counts["Modified"] += 1
            if row is None:
                # after the last calculated month: deposit / balances are nil
                continue
            v = row.values
            out["rou"] += v["rou_close"]
            out["liability"] += v["liab_close"]
            out["current"] += v["liab_current"]
            out["non_current"] += v["liab_non_current"]
            out["sd_carrying"] += v["sd_close"]
            out["sd_nominal"] += v["sd_nominal_close"]
            out["depreciation"] += v["rou_depreciation"]
            out["interest"] += v["liab_interest"]
            out["rent"] += v["rent_eligible"]
            out["sd_unwinding"] += v["sd_unwinding"]
        out["counts"] = counts
        return out
