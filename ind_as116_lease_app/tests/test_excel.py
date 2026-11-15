import os
import sys
import tempfile
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lease_app.db.database import Database  # noqa: E402
from lease_app.db.repository import Repository  # noqa: E402
from lease_app.excel import workbook as xl  # noqa: E402
from lease_app.registers import REGISTERS  # noqa: E402
from lease_app import sample_data as sd  # noqa: E402


def _copy_example_to_data(path):
    wb = load_workbook(path)
    ex, data = wb["Example"], wb["Data"]
    for row in ex.iter_rows(min_row=2, values_only=True):
        data.append(list(row))
    wb.save(path)


def test_template_round_trip_and_error_report():
    tmp = Path(tempfile.mkdtemp())
    repo = Repository(Database(tmp / "db.sqlite"))
    files = xl.write_all_templates(tmp / "tpl", repo)
    assert len(files) == 8
    lm = tmp / "tpl" / "01_Lease_Master_Template.xlsx"
    _copy_example_to_data(lm)
    res = xl.import_register(repo, "lease_master", lm)
    assert res.ok, res.errors
    assert res.imported == 3
    esc = tmp / "tpl" / "02_Rent_Escalation_Register_Template.xlsx"
    _copy_example_to_data(esc)
    res = xl.import_register(repo, "escalations", esc)
    assert res.ok and res.imported == 4

    # re-import the same lease file -> duplicates rejected, nothing imported, error report produced
    res = xl.import_register(repo, "lease_master", lm)
    assert not res.ok and res.imported == 0
    assert res.error_report and Path(res.error_report).exists()

    # bad rows: missing mandatory, invalid date, bad escalation (percentage without %)
    bad = tmp / "bad.xlsx"
    xl.write_template(REGISTERS["escalations"], bad)
    wb = load_workbook(bad)
    ws = wb["Data"]
    ws.append(["", "L0001", "31-02-2027", "Percentage", None, None, 12])     # invalid date
    ws.append(["", "L9999", "01-04-2027", "Percentage", 5, None, 12])        # unknown lease
    ws.append(["", "L0002", "01-07-2027", "Percentage", None, None, 12])     # % missing
    wb.save(bad)
    res = xl.import_register(repo, "escalations", bad)
    msgs = " | ".join(m for _, _, m in res.errors)
    assert "Invalid date" in msgs and "does not exist" in msgs and "Escalation % is required" in msgs
    assert len(repo.list_rows("escalations")) == 4          # all-or-nothing
