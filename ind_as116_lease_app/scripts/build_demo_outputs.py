"""Builds the Phase 1 demonstration deliverables:

sample_data/demo_lease_accounting.sqlite      demo database (8 leases, April 2027 journals as Draft)
sample_data/Sample_Lease_Data.xlsx            all master data of the demo leases
sample_data/outputs/Journals_April_2027.xlsx  monthly journals (lines, ERP upload, account summary, balances)
sample_data/outputs/Lease_Workings_L000x.xlsx lease-wise workings with live Excel PV formulas
sample_data/outputs/Consolidated_Lease_Schedules.xlsx
templates/*.xlsx                              Excel input / output templates
docs/Accounting_Test_Results.xlsx             test results (input, expected, actual, difference, pass/fail)

Usage:  python scripts/build_demo_outputs.py
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from lease_app.db.database import Database  # noqa: E402
from lease_app.excel import workbook as xl  # noqa: E402
from lease_app.sample_data import load_sample_data  # noqa: E402
from lease_app.services import LeaseService  # noqa: E402


def main():
    out = ROOT / "sample_data" / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    dbp = ROOT / "sample_data" / "demo_lease_accounting.sqlite"
    if dbp.exists():
        dbp.unlink()
    db = Database(dbp)
    db.user = "demo"
    svc = LeaseService(db)
    load_sample_data(svc.repo)
    apr = date(2027, 4, 1)
    lines = svc.generate_month(apr)
    s = db.settings()
    xl.export_journals(lines, out / "Journals_April_2027.xlsx", apr, svc.calculate_all(), s["erp_journal_source"],
                       s["company_name"])
    b = svc.basis()
    for lid, res in svc.calculate_all().items():
        xl.export_lease_workbook(res, out / f"Lease_Workings_{lid}.xlsx", f"{b.time_basis} / {b.rate_basis}")
    xl.export_consolidated_schedules(svc.calculate_all(), out / "Consolidated_Lease_Schedules.xlsx")
    xl.export_all_master_data(svc.repo, ROOT / "sample_data" / "Sample_Lease_Data.xlsx")
    xl.write_all_templates(ROOT / "templates", svc.repo)
    db.close()
    for f in (ROOT / "sample_data" / "backups").glob("*"):
        f.unlink()
    (ROOT / "sample_data" / "backups").rmdir() if (ROOT / "sample_data" / "backups").exists() else None

    from scenarios import run_all
    results = run_all()
    xl.export_rows(["Test no.", "Scenario", "Check", "Input", "Expected (independent)", "Actual (application)",
                    "Difference", "Status"],
                   [[r["no"], r["scenario"], r["check"], r["input"], r["expected"], r["actual"], r["difference"],
                     r["status"]] for r in results],
                   ROOT / "docs" / "Accounting_Test_Results.xlsx", "Test results",
                   ["int", "text", "text", "text", "decimal", "decimal", "decimal", "text"])
    passed = sum(r["status"] == "Pass" for r in results)
    failed = sum(r["status"] == "Fail" for r in results)
    print(f"Journals April 2027: {len(lines)} lines; tests: {passed} pass, {failed} fail")


if __name__ == "__main__":
    main()
