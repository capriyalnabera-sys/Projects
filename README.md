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

## Google Sheets mirror

Every module has a **⬇ CSV** button (and `/api/export/<module>.csv`) so you can
drop the data into a Google Sheet for family to view or back up. A one-click
two-way Google Sheets sync is the planned next step (Architecture "B").

---

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `ADMIN_PASSWORD` | `wedding` | Password to open the planner |
| `PORT` | `3000` | Port to listen on |
| `SESSION_SECRET` | derived | Overrides the login-cookie signing secret |

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

The invite site needs a public URL. Any Node host works (Render, Railway,
Fly.io, a small VPS). Set `ADMIN_PASSWORD`, run `npm start`, and share each
guest's `/i/<token>` link. Keep `wedding.db` on a persistent disk so data
survives restarts.
