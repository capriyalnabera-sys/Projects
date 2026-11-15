# User manual (Phase 1)

The application is a Windows desktop program. It works fully offline; no browser or server is needed.
All data is stored in one local SQLite file:

`%LOCALAPPDATA%\IndAS116LeaseApp\lease_accounting.sqlite` (backups are in the `backups` sub-folder)

## First start

1. Start **IndAS116LeaseApp.exe**, or run `python main.py` from source.
2. If the database is empty, either:
   * go to **Settings → Load sample (demo) data** to load the 8 demonstration leases, or
   * add leases in **Lease Master**, or import them from the Excel template.

## Screens

| Section | What you do there |
|---|---|
| Dashboard | Portfolio KPIs for any month: active, new, modified and terminated leases; ROU; liability (current and non-current); deposits; the month's depreciation, interest and rent; upcoming expiries, escalations and refunds |
| Lease Master | Add, edit, delete, search and import leases. The bottom panel shows the initial liability and ROU of the selected lease |
| Rent Escalation | Percentage and absolute escalation rules. The bottom panel shows the expanded rent steps (existing rent, revised rent, next escalation date) |
| Payment Schedule | The generated schedule per lease. Export it, download the actual-payments template, and upload actual payment date and amount to see the status (Paid, Partially paid, Overdue) |
| Lease Calculations | Lease-wise workings: summary, initial PV table, liability, ROU and deposit schedules, events. Export to Excel (includes live PV formulas) or export consolidated schedules |
| Modifications | The modification register. Only *Approved* records are accounted for. The bottom panel shows the remeasurement: liability before and after, ROU adjustment, gain/loss |
| Terminations | Full and partial terminations, with the derecognition result |
| Security Deposits | Original and additional deposits and refunds. The bottom panel shows the deposit summary and the fair-value working |
| Monthly Accounting | Select a month and year, click **Generate monthly entries**, filter by lease, entity, location, journal type and status, then view the lines, the account-wise summary and the opening/closing balances. **Approve**, **Mark as posted**, **Export Excel / ERP** |
| GL Reconciliation | GL upload template (the full screen comes in Phase 3) |
| Reports | Consolidated schedules and master-data export (disclosures and PDF come in Phase 4) |
| Settings | Accounting conventions, deposit rate, backup options, journal account mapping, sample data, all templates |
| Backup and Restore | Back up now, restore, export all data, and the audit trail (user, time, previous and revised values, reason) |

## Generating April 2027 journals (demonstration)

1. **Monthly Accounting** → Month = April, Year = 2027 → **Generate monthly entries**.
2. 88 lines and 36 vouchers are created as **Draft**. The total debit equals the total credit (the
   footer shows *BALANCED ✔*).
3. Use the filters or tabs to review the lines, the consolidated account-wise summary and the
   opening/closing balances of the liability, ROU and deposits.
4. **Approve**, then **Mark as posted**. Once a batch is approved, generating that month again is
   blocked, so duplicate journals cannot be created.
5. **Export Excel / ERP** creates a workbook with these sheets: *Journal lines*, *ERP upload*,
   *Account summary*, *By journal type* and *Lease balances*.

To correct inputs after a Draft has been generated, change the records and click **Regenerate draft**.

## Excel import

1. Download a template (each register has a **Download template** button, or use **Settings →
   Download all Excel templates**).
2. Fill the **Data** sheet. Red headers are mandatory, and the *Instructions* sheet explains every
   column. The *Example* sheet shows filled rows.
3. Click **Import Excel**. Every row is validated first: mandatory fields, duplicate IDs, dates,
   numbers, allowed values, whether the lease exists, and escalation consistency.
   **If any row fails, nothing is imported**, and an error report (`<file>_ERRORS.xlsx`, listing the
   row, key and error) is saved next to the file.

## Controls

* Editing a record requires a **reason**. Previous and revised values are kept in the audit log.
* Deleting asks for confirmation and a reason. A lease with approved or posted journals cannot be
  deleted.
* Approved and posted journal batches are never overwritten.
* Every journal generation is logged as a calculation run, with the settings used.

## Backup and restore

* **Automatic:** one backup a day when the application starts (the last 30 are kept; this is
  configurable).
* **Manual:** go to *Backup and Restore* → **Backup now**.
* **Restore:** select a backup → **Restore selected backup** (or *Restore from file...*). The current
  database is backed up automatically before every restore.
* To move to another PC, copy `lease_accounting.sqlite` (or any backup file), then use *Restore from
  file...*.
