"""CRUD for the registers with business validation and a full audit trail."""
from __future__ import annotations

import re
from datetime import date, datetime

from ..engine.decimal_utils import D
from ..engine.dates import TimeBasis, month_start, ym
from ..registers import REGISTERS, Register, normalise, parse_date
from .database import Database


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ read
    def list_rows(self, reg: Register | str, lease_id: str | None = None, order: str | None = None):
        reg = REGISTERS[reg] if isinstance(reg, str) else reg
        sql = f"SELECT * FROM {reg.table}"
        params = ()
        if lease_id and reg.child_of_lease:
            sql += " WHERE lease_id = ?"
            params = (lease_id,)
        sql += f" ORDER BY {order or 'id'}"
        return self.db.query(sql, params)

    def get(self, reg: Register | str, key):
        reg = REGISTERS[reg] if isinstance(reg, str) else reg
        rows = self.db.query(f'SELECT * FROM {reg.table} WHERE "{reg.key}" = ?', (key,))
        return rows[0] if rows else None

    def lease_ids(self):
        return [r["lease_id"] for r in self.db.query("SELECT lease_id FROM leases ORDER BY lease_id")]

    def next_key(self, reg: Register) -> str:
        prefix = reg.key_prefix or reg.key[:3].upper()
        n = 0
        for r in self.db.query(f'SELECT "{reg.key}" AS k FROM {reg.table}'):
            m = re.fullmatch(rf"{re.escape(prefix)}(\d+)", r["k"] or "")
            if m:
                n = max(n, int(m.group(1)))
        width = 4 if prefix == "L" else 5
        return f"{prefix}{n + 1:0{width}d}"

    # ------------------------------------------------------------------ validation
    def validate(self, reg: Register, raw: dict, is_new: bool, original_key=None) -> dict:
        values, errors = normalise(reg, raw)
        key = values.get(reg.key)
        if is_new and key and self.get(reg, key):
            errors.append(f"{reg.field(reg.key).label} '{key}' already exists (duplicate)")
        lease = None
        if reg.child_of_lease and values.get("lease_id"):
            lease = self.get("lease_master", values["lease_id"])
            if lease is None:
                errors.append(f"Lease ID '{values['lease_id']}' does not exist in Lease Master")
        if not errors:
            errors += getattr(self, f"_check_{reg.name}", lambda v, l, n, o: [])(values, lease, is_new, original_key)
        if errors:
            raise ValidationError(errors)
        return values

    @staticmethod
    def _d(v):
        return parse_date(v) if v else None

    def _check_lease_master(self, v, lease, is_new, original_key):
        e = []
        c, end, ag = self._d(v["commencement_date"]), self._d(v["lease_end_date"]), self._d(v["agreement_start_date"])
        if c and end and end <= c:
            e.append("Lease end date must be after commencement date")
        if ag and c and ag > c:
            e.append("Agreement start date cannot be after commencement date")
        if D(v["monthly_rent"]) < 0:
            e.append("Monthly rent cannot be negative")
        rate = D(v["discount_rate"])
        if rate <= 0 or rate > 50:
            e.append("Discount rate / IBR must be between 0 and 50 % p.a.")
        for k in ("security_deposit", "prepaid_lease_rentals", "initial_direct_costs", "lease_incentives",
                  "restoration_provision", "gst_rate", "non_lease_monthly"):
            if D(v.get(k)) < 0:
                e.append(f"{REGISTERS['lease_master'].field(k).label} cannot be negative")
        if c and end:
            term = (end.year - c.year) * 12 + end.month - c.month + 1
            if int(v.get("rent_free_months") or 0) >= term:
                e.append("Rent-free period must be shorter than the lease term")
            v["lease_tenure_months"] = str(TimeBasis().t(c, end.fromordinal(end.toordinal() + 1)).quantize(D("0.01")))
        dup = self.db.query("SELECT lease_id FROM leases WHERE agreement_no = ? AND lease_id IS NOT ?",
                            (v["agreement_no"], original_key or v.get("lease_id")))
        if dup:
            e.append(f"Agreement number '{v['agreement_no']}' already used by lease {dup[0]['lease_id']}")
        return e

    def _lease_window(self, lease):
        return self._d(lease["commencement_date"]), self._d(lease["lease_end_date"])

    def _check_escalations(self, v, lease, is_new, original_key):
        e = []
        c, end = self._lease_window(lease)
        d = self._d(v["effective_date"])
        if d and (d <= c or d > end):
            e.append(f"Escalation effective date must be after commencement ({c:%d-%m-%Y}) and on/before "
                     f"lease end ({end:%d-%m-%Y})")
        if v["escalation_type"] == "Percentage":
            if D(v.get("escalation_pct")) == 0:
                e.append("Escalation % is required for a Percentage escalation")
            if D(v.get("escalation_pct")) < -100 or D(v.get("escalation_pct")) > 100:
                e.append("Escalation % looks incorrect (must be between -100 and 100)")
            if D(v.get("escalation_amount")):
                e.append("Absolute amount must be blank for a Percentage escalation")
        else:
            if D(v.get("escalation_amount")) == 0:
                e.append("Absolute escalation amount is required for an Absolute Amount escalation")
            if D(v.get("escalation_pct")):
                e.append("Escalation % must be blank for an Absolute Amount escalation")
        if int(v.get("frequency_months") or 0) < 0:
            e.append("Escalation frequency cannot be negative")
        dup = self.db.query("SELECT escalation_ref FROM escalations WHERE lease_id=? AND effective_date=? "
                            "AND escalation_ref IS NOT ?", (v["lease_id"], v["effective_date"],
                                                            original_key or v.get("escalation_ref")))
        if dup:
            e.append(f"Lease {v['lease_id']} already has an escalation effective {d:%d-%m-%Y} ({dup[0]['escalation_ref']})")
        return e

    def _check_modifications(self, v, lease, is_new, original_key):
        e = []
        c, end = self._lease_window(lease)
        d = self._d(v["effective_date"])
        if d and (d <= c or d > end):
            e.append("Modification effective date must fall within the lease term (after commencement)")
        rev_end = self._d(v.get("revised_end_date"))
        if rev_end and d and rev_end < d:
            e.append("Revised expiry date cannot be before the effective date")
        pct = D(v.get("area_reduction_pct"))
        if pct < 0 or pct >= 100:
            e.append("Area / scope reduction % must be between 0 and 99.99 (use Termination for 100 %)")
        if v.get("revised_escalation_type"):
            if not v.get("revised_first_escalation_date"):
                e.append("First revised escalation date is required when a revised escalation type is given")
            if v["revised_escalation_type"] == "Percentage" and not D(v.get("revised_escalation_pct")):
                e.append("Revised escalation % is required")
            if v["revised_escalation_type"] == "Absolute Amount" and not D(v.get("revised_escalation_amount")):
                e.append("Revised escalation amount is required")
        if v.get("revised_discount_rate") and not (0 < D(v["revised_discount_rate"]) <= 50):
            e.append("Revised discount rate must be between 0 and 50 % p.a.")
        return e

    def _check_terminations(self, v, lease, is_new, original_key):
        e = []
        c, end = self._lease_window(lease)
        d = self._d(v["effective_date"])
        if d and (d <= c or d > end):
            e.append("Termination effective date must fall within the lease term (after commencement)")
        if v["termination_type"] == "Partial" and not (0 < D(v.get("partial_pct")) < 100):
            e.append("Partial termination % must be between 0 and 100")
        if D(v.get("termination_payment")) < 0:
            e.append("Termination payment cannot be negative")
        if v["approval_status"] == "Approved":
            other = self.db.query("SELECT term_ref FROM terminations WHERE lease_id=? AND termination_type='Full' "
                                  "AND approval_status='Approved' AND term_ref IS NOT ?",
                                  (v["lease_id"], original_key or v["term_ref"]))
            if other and v["termination_type"] == "Full":
                e.append(f"Lease already has an approved full termination ({other[0]['term_ref']})")
        return e

    def _check_deposits(self, v, lease, is_new, original_key):
        e = []
        if D(v["amount"]) <= 0:
            e.append("Amount must be greater than zero")
        md, rd = self._d(v["movement_date"]), self._d(v.get("expected_refund_date"))
        if rd and md and rd <= md:
            e.append("Expected refund date must be after the deposit date")
        if v["movement_type"] == "Refund":
            bal = D(0)
            for r in self.db.query("SELECT * FROM deposit_movements WHERE lease_id=? AND approval_status='Approved' "
                                   "AND deposit_ref IS NOT ?", (v["lease_id"], original_key or v["deposit_ref"])):
                if r["refundable"] != "Refundable":
                    continue
                bal += -D(r["amount"]) if r["movement_type"] == "Refund" else D(r["amount"])
            if D(v["amount"]) > bal:
                e.append(f"Refund {v['amount']} exceeds the refundable deposit balance {bal}")
        if v.get("discount_rate") and not (0 <= D(v["discount_rate"]) <= 50):
            e.append("Deposit discount rate must be between 0 and 50 % p.a.")
        return e

    # ------------------------------------------------------------------ write
    def save(self, reg: Register | str, raw: dict, reason: str = "", original_key=None) -> str:
        reg = REGISTERS[reg] if isinstance(reg, str) else reg
        is_new = original_key is None
        if is_new and not raw.get(reg.key):
            raw = dict(raw, **{reg.key: self.next_key(reg)})
        if not is_new and not raw.get(reg.key):
            raw = dict(raw, **{reg.key: original_key})
        values = self.validate(reg, raw, is_new, original_key)
        now = datetime.now().isoformat(timespec="seconds")
        cols = list(values)
        if is_new:
            self.db.execute(
                f"INSERT INTO {reg.table} ({', '.join(chr(34) + c + chr(34) for c in cols)}, created_at, created_by) "
                f"VALUES ({', '.join('?' for _ in cols)}, ?, ?)", [values[c] for c in cols] + [now, self.db.user])
            self.db.audit(reg.table, values[reg.key], "INSERT", None, values, reason or "New record")
        else:
            old = self.get(reg, original_key)
            if old is None:
                raise ValidationError([f"Record {original_key} not found"])
            changed = {c: values[c] for c in cols if (old.get(c) or None) != (values[c] or None)}
            if not changed:
                return values[reg.key]
            self.db.execute(
                f"UPDATE {reg.table} SET {', '.join(chr(34) + c + chr(34) + '=?' for c in cols)}, updated_at=?, "
                f'updated_by=? WHERE "{reg.key}"=?', [values[c] for c in cols] + [now, self.db.user, original_key])
            self.db.audit(reg.table, values[reg.key], "UPDATE", {c: old.get(c) for c in changed}, changed,
                          reason or "Edited")
            if reg.name == "lease_master" and values[reg.key] != original_key:
                for child in ("escalations", "modifications", "terminations", "deposit_movements", "payment_actuals"):
                    self.db.execute(f"UPDATE {child} SET lease_id=? WHERE lease_id=?", (values[reg.key], original_key))
        return values[reg.key]

    def delete(self, reg: Register | str, key, reason: str):
        reg = REGISTERS[reg] if isinstance(reg, str) else reg
        old = self.get(reg, key)
        if old is None:
            return
        if reg.name == "lease_master":
            posted = self.db.query("SELECT COUNT(*) n FROM journal_lines WHERE lease_id=? AND status IN ('Approved','Posted')",
                                   (key,))[0]["n"]
            if posted:
                raise ValidationError([f"Lease {key} has approved/posted journals and cannot be deleted. "
                                       "Change its status instead."])
            for child in ("escalations", "modifications", "terminations", "deposit_movements", "payment_actuals"):
                for r in self.db.query(f"SELECT * FROM {child} WHERE lease_id=?", (key,)):
                    self.db.audit(child, r.get("id"), "DELETE", r, None, f"Cascade from lease {key}: {reason}")
                self.db.execute(f"DELETE FROM {child} WHERE lease_id=?", (key,))
        self.db.execute(f'DELETE FROM {reg.table} WHERE "{reg.key}"=?', (key,))
        self.db.audit(reg.table, key, "DELETE", old, None, reason)

    def audit_rows(self, limit=2000, table=None, key=None):
        sql, params = "SELECT * FROM audit_log", []
        cond = []
        if table:
            cond.append("table_name=?"); params.append(table)
        if key:
            cond.append("record_key=?"); params.append(key)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self.db.query(sql, params)
