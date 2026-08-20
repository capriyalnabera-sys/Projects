# 💍 Wedding_AP — All-in-one wedding planner + invite site

An A-to-Z wedding tracker for the couple and family, plus a beautiful
**personalised invite website** for guests. Built as one small Node app so
there is a single source of truth and nothing to babysit.

---

## What's inside

**The planner** (password protected) — a tab per module:

| Module | What it tracks |
|---|---|
| 📊 Dashboard | Live countdown, guest/RSVP/budget/task summary |
| 💌 Guests | Master list, side & group, meal, headcount, **personalised invite link** |
| 🎉 Functions | Every event: date, time, venue, dress code, theme colour, map |
| ✅ To-do | Tasks with owner, due date, priority, status |
| 💰 Budget | Estimated vs actual vs paid, auto **balance**, link to a vendor |
| 🤝 Vendors | Contacts, contract, advance, auto **balance due** |
| 👗 Dress code / Outfits | Who wears what, per function, so photos coordinate |
| 🏨 Rooms & 🗝️ Allocation | Rooms and which guest stays where, check-in/out |
| ✈️ Travel | Arrivals & departures, pickup needed, coordinator |
| ⏱️ Run of show | Minute-by-minute flow for each function |
| 💃 Dance / Performances | Sangeet line-up, song, order, rehearsal status |
| 🎁 Gifts to give / 🧧 received | Return gifts + shagun received (for thank-yous) |

**The invite site** — each guest gets a link like `/i/<token>` that:
- greets them **by name**,
- shows the **full schedule** with the functions they're invited to highlighted,
- collects a **per-function RSVP**, headcount and meal preference,
- writes the response straight back into the planner's guest list.

---

## Quick start

```bash
npm install
npm run seed      # optional: loads a demo wedding so you can look around
npm start         # http://localhost:3000
```

- Planner password defaults to `wedding`. **Set your own:**
  `ADMIN_PASSWORD=your-secret npm start`
- Guest invite links are shown in the **Guests** tab — click **🔗 Copy** on any row.
- Change couple names, date, hashtag and the invite welcome message under
  **Couple & invite settings**.

To start fresh (remove the demo data), delete `wedding.db` and restart.

---

## Google Sheets & Excel

Three ways to get the plan into a spreadsheet, in increasing power:

1. **⬇ CSV** on each module (`/api/export/<module>.csv`) — quick single-table grab.
2. **⬇ Excel** (top bar, `/api/export.xlsx`) — the whole plan as one workbook,
   every module a tab, references resolved to names, invite links included.
   Opens in Excel and imports straight into Google Sheets.
3. **Two-way Google Sheets sync** (optional) — the planner mirrors to a live
   Google Sheet and can read family's edits back. See below.

### Two-way Google Sheets sync setup

Because this must also work on a deployed server, sync uses a Google
**service account** (not a personal login):

1. In [Google Cloud Console](https://console.cloud.google.com/): create a
   project → enable the **Google Sheets API** → create a **Service account** →
   add a **JSON key** and download it.
2. Create a Google Sheet in *your personal Drive* and copy its ID from the URL
   (`https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`).
3. **Share** that Sheet with the service account's `client_email` as **Editor**.
4. Set env vars (locally in `.env`, or in your host):
   - `GOOGLE_SHEET_ID` = the Sheet ID
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = the key file's contents on one line
     (or `GOOGLE_SERVICE_ACCOUNT_FILE` = a path to it)
5. Restart. The Dashboard shows **🔄 Google Sheets sync — connected** with
   **⬆ Push to Sheet** and **⬇ Pull from Sheet** buttons.

Notes: **Push** overwrites each tab from the planner. **Pull** upserts rows by
their **ID** column (edit existing rows, or add a new row leaving ID blank).
Reference columns (vendor/guest/room/function) are shown as names and are
**read-only on pull** — manage those links in the app. Deletes are not synced
(remove rows in the planner).

---

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `ADMIN_PASSWORD` | `wedding` | Password to open the planner |
| `PORT` | `3000` | Port to listen on |
| `SESSION_SECRET` | derived | Overrides the login-cookie signing secret |
| `WEDDING_DB` | `./wedding.db` | Path to the SQLite file (point at a persistent disk when hosted) |
| `GOOGLE_SHEET_ID` | — | Target spreadsheet for two-way sync (optional) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | — | Service-account key JSON for sync (or `_FILE` for a path) |

---

## How it's built (and how to extend it)

The whole app is driven by **one schema** in [`db.js`](db.js) (`SCHEMA`). Each
module lists its columns and types; the database tables, the REST CRUD API
([`routes/api.js`](routes/api.js)) and the front-end tables & forms
([`public/app.js`](public/app.js)) all read from it. So **adding a field or a
whole new module is a one-place change** — add it to `SCHEMA` and it appears
everywhere, migrations included.

```
server.js            Express app: auth gate + planner + open invite routes
db.js                Schema, SQLite (sql.js) storage, CRUD, dashboard, invites
routes/api.js        Generic REST API for every module + CSV export
public/              The planner UI (index.html, app.js, styles.css, login.html)
invite/invite.html   The guest-facing personalised invite site
seed.js              Demo data
```

Data lives in a single `wedding.db` file (SQLite via `sql.js`), which is
git-ignored.

---

## Deploying (so guests can open their links)

The invite site needs a public URL. Any Node host works.

**One-click on Render:** this repo ships a [`render.yaml`](render.yaml)
blueprint. In Render → **New + → Blueprint** → connect this repo. It provisions
the web service and a 1 GB persistent disk mounted at `/data`
(`WEDDING_DB=/data/wedding.db`) so the database survives restarts, and asks you
to set `ADMIN_PASSWORD`. There's also a [`Procfile`](Procfile) for
Heroku-style hosts.

After it's live: sign in, set your details, and share each guest's
`/i/<token>` link (the **🔗 Copy** button in the Guests tab).
