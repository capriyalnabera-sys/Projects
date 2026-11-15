# Ind AS 116 Lease Accounting – Windows desktop application

This is a standalone, offline desktop application for lease accounting under Ind AS 116, built with
Python, PySide6 (Qt), SQLite and Excel (openpyxl / pandas). It needs no browser, web server, hosting or
internet connection.

**Status: Phase 1 delivered for validation.** Phases 2–5 will start only after the Phase 1
calculations have been validated.

| Phase | Scope | Status |
|---|---|---|
| 1 | Desktop framework, SQLite database, Excel templates, calculation engine, demo with April 2027 journals | **Delivered** |
| 2 | Hardening of escalations, deposits, modifications and terminations (engine already supports the demo cases) | Pending validation |
| 3 | Month-end closure workflow, GL reconciliation, month lock/reopen | Pending |
| 4 | Dashboard, Ind AS 116 disclosures, PDF reports | Pending |
| 5 | Full test pack, Windows installer packaging | Pending (`build_exe.bat` already works) |

## Run it (Windows)

1. **Install Python once:** download Python 3.12 (64-bit) from https://www.python.org/downloads/windows/
   and tick **"Add python.exe to PATH"** in the installer.
2. **Copy the `ind_as116_lease_app` folder** to a simple location, for example `C:\LeaseApp`.
3. **Double-click `run_from_source.bat`.** On the first run it creates its own environment and downloads
   the required packages (internet needed once, 2–5 minutes). After that it starts offline in seconds.

The launcher checks each step and keeps the window open with a plain-language message if anything
fails (Python missing, wrong version, proxy blocking downloads). If the application itself fails to
start, the details are saved to `%LOCALAPPDATA%\IndAS116LeaseApp\startup_error.log`.

To load the 8 demonstration leases into an empty database, use **Settings → Load sample (demo) data**,
or start from a command prompt with `run_from_source.bat --demo`. Then go to **Monthly Accounting**,
select **April 2027**, and click **Generate monthly entries**.

To open the prepared demo database:

```bat
run_from_source.bat --db sample_data\demo_lease_accounting.sqlite
```

### Build the Windows .exe

```bat
build_exe.bat
```

Run `run_from_source.bat` once first. The build script then installs the build tools, **runs the
accounting tests (and stops if any fail)**, then builds `dist\IndAS116LeaseApp\IndAS116LeaseApp.exe` with
PyInstaller. Copy the whole `dist\IndAS116LeaseApp` folder to any Windows PC; Python is not needed
there.

## Folder structure

```
main.py                         application entry point
lease_app/engine/               calculation engine - pure Python Decimal, no UI / DB code
    rent.py                     escalation expansion, payment schedule
    lease_engine.py             liability, ROU, modifications, terminations, deposits
    journals.py                 monthly journal generation + default chart of accounts
lease_app/registers.py          single definition of every register (DB, forms, templates, validation)
lease_app/db/                   SQLite schema, settings, audit trail, backup / restore, repository
lease_app/services.py           links the database and the engine; journal batches; duplicate prevention
lease_app/excel/workbook.py     templates, validated import + error report, exports
lease_app/ui/                   PySide6 desktop screens
tests/                          independent accounting tests (pytest)
scripts/build_demo_outputs.py   regenerates all sample outputs below
templates/                      Excel input / output templates (9)
sample_data/                    demo database, sample lease data, April 2027 journals, lease workings
docs/                           accounting method, user manual, demo note, test results
```

## Deliverables in this phase

* Source code (this folder).
* Demo database: `sample_data/demo_lease_accounting.sqlite`.
* Sample lease data: `sample_data/Sample_Lease_Data.xlsx`.
* **Sample monthly journals for April 2027:** `sample_data/outputs/Journals_April_2027.xlsx`.
* Lease-wise workings with live Excel PV formulas: `sample_data/outputs/Lease_Workings_L0001..8.xlsx`.
* Excel templates: `templates/`.
* Accounting method and judgements: `docs/ACCOUNTING_METHOD.md`.
* User manual, including backup and restore: `docs/USER_MANUAL.md`.
* Demo walk-through with April 2027 figures: `docs/PHASE1_DEMO_APRIL_2027.md`.
* Test results (input, independent expected value, actual, difference, pass/fail):
  `docs/Accounting_Test_Results.xlsx`.

## Tests

```bash
python -m pytest -q tests
python scripts/build_demo_outputs.py     # rebuilds sample outputs and the test-results workbook
```

The tests cover 21 of the 24 required scenarios with 66 checks. Scenarios 22–24 (GL reconciliation,
month closure and reopening) belong to Phase 3. Expected values are computed independently, using
annuity formulas and explicit roll-forwards in `tests/scenarios.py`.
