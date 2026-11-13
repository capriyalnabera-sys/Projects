"""Local SQLite database: schema, settings, audit trail and backup / restore."""
from __future__ import annotations

import getpass
import json
import os
import shutil
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

from ..engine.journals import DEFAULT_ACCOUNTS
from ..registers import REGISTERS

APP_NAME = "IndAS116LeaseApp"

DEFAULT_SETTINGS = {
    "company_name": "My Company Ltd",
    "currency": "INR",
    "fy_start_month": "4",
    "time_basis": "monthly",            # monthly | actual_365
    "rate_basis": "effective",          # effective | nominal
    "depreciation_method": "Straight-line over lease term",
    "default_deposit_rate": "",         # blank -> lease IBR
    "auto_backup": "Yes",
    "backup_keep": "30",
    "approval_threshold": "1000000",
    "erp_journal_source": "LEASE",
}

EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS accounts (key TEXT PRIMARY KEY, code TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, table_name TEXT, record_key TEXT,
    action TEXT, old_values TEXT, new_values TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS calc_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, purpose TEXT, month TEXT,
    lease_count INTEGER, settings TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS journal_batches (
    month TEXT PRIMARY KEY, status TEXT, calc_run_id INTEGER, generated_at TEXT, generated_by TEXT,
    approved_at TEXT, approved_by TEXT, posted_at TEXT, posted_by TEXT, line_count INTEGER,
    total_debit TEXT, total_credit TEXT);
CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT, accounting_date TEXT, lease_id TEXT,
    agreement_no TEXT, entity TEXT, location TEXT, voucher_no TEXT, account_key TEXT, account_code TEXT,
    account_name TEXT, narration TEXT, debit TEXT, credit TEXT, journal_type TEXT, calc_ref TEXT,
    status TEXT, UNIQUE(month, voucher_no, account_key, narration));
CREATE INDEX IF NOT EXISTS ix_jl_month ON journal_lines(month);
CREATE TABLE IF NOT EXISTS month_status (
    month TEXT PRIMARY KEY, status TEXT, closed_at TEXT, closed_by TEXT, reopened_at TEXT,
    reopened_by TEXT, reopen_reason TEXT);
"""


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path.home() / ".local" / "share"
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover
        return "user"


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.user = current_user()
        self.data_version = 0
        self.create_schema()

    # ------------------------------------------------------------------ schema
    def create_schema(self):
        cur = self.conn.cursor()
        for reg in REGISTERS.values():
            cols = ", ".join(f'"{f.key}" TEXT' for f in reg.fields)
            cur.execute(
                f'CREATE TABLE IF NOT EXISTS {reg.table} (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols}, '
                f'created_at TEXT, created_by TEXT, updated_at TEXT, updated_by TEXT, UNIQUE("{reg.key}"))')
            existing = {r[1] for r in cur.execute(f"PRAGMA table_info({reg.table})")}
            for f in reg.fields:            # forward-compatible column additions
                if f.key not in existing:
                    cur.execute(f'ALTER TABLE {reg.table} ADD COLUMN "{f.key}" TEXT')
        cur.executescript(EXTRA_SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        for k, (code, name) in DEFAULT_ACCOUNTS.items():
            cur.execute("INSERT OR IGNORE INTO accounts(key, code, name) VALUES (?, ?, ?)", (k, code, name))
        self.conn.commit()

    # ------------------------------------------------------------------ helpers
    def query(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        self.data_version += 1
        return cur

    def settings(self) -> dict:
        return {r["key"]: r["value"] for r in self.query("SELECT key, value FROM settings")}

    def set_setting(self, key, value, reason="Settings updated"):
        old = self.settings().get(key)
        if old == value:
            return
        self.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))
        self.audit("settings", key, "UPDATE", {"value": old}, {"value": value}, reason)

    def accounts(self) -> dict:
        return {r["key"]: (r["code"], r["name"]) for r in self.query("SELECT * FROM accounts ORDER BY code")}

    def set_account(self, key, code, name, reason="Account mapping updated"):
        old = self.accounts().get(key)
        self.execute("INSERT OR REPLACE INTO accounts(key, code, name) VALUES (?, ?, ?)", (key, code, name))
        self.audit("accounts", key, "UPDATE", {"code": old[0], "name": old[1]} if old else None,
                   {"code": code, "name": name}, reason)

    def audit(self, table, key, action, old, new, reason=""):
        self.conn.execute(
            "INSERT INTO audit_log(ts, user, table_name, record_key, action, old_values, new_values, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), self.user, table, str(key), action,
             json.dumps(old, default=str) if old is not None else None,
             json.dumps(new, default=str) if new is not None else None, reason))
        self.conn.commit()

    # ------------------------------------------------------------------ backup
    @property
    def backup_dir(self) -> Path:
        p = self.path.parent / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def backup(self, label="manual") -> Path:
        target = self.backup_dir / f"lease_db_{datetime.now():%Y%m%d_%H%M%S}_{label}.sqlite"
        dest = sqlite3.connect(str(target))
        with dest:
            self.conn.backup(dest)
        dest.close()
        self.audit("database", target.name, "BACKUP", None, {"file": str(target)}, label)
        self._prune_backups()
        return target

    def _prune_backups(self):
        keep = int(self.settings().get("backup_keep") or 30)
        autos = sorted(self.backup_dir.glob("lease_db_*_auto.sqlite"))
        for old in autos[:-keep]:
            old.unlink(missing_ok=True)

    def auto_backup_if_due(self):
        if self.settings().get("auto_backup", "Yes") != "Yes":
            return None
        today = date.today().strftime("%Y%m%d")
        if any(self.backup_dir.glob(f"lease_db_{today}_*_auto.sqlite")):
            return None
        return self.backup("auto")

    def list_backups(self):
        return sorted(self.backup_dir.glob("lease_db_*.sqlite"), reverse=True)

    def restore(self, backup_file: str | Path):
        backup_file = Path(backup_file)
        # verify the file is a valid database of this application
        test = sqlite3.connect(str(backup_file))
        try:
            tables = {r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            test.close()
        if "leases" not in tables or "audit_log" not in tables:
            raise ValueError("Selected file is not a lease application backup")
        self.backup("pre_restore")
        self.conn.close()
        shutil.copyfile(backup_file, self.path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.create_schema()
        self.data_version += 1
        self.audit("database", backup_file.name, "RESTORE", None, {"file": str(backup_file)}, "Restore")

    def close(self):
        self.conn.close()
