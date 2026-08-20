# Google Sheets sync — setup guide

The planner can mirror **every module into a Google Sheet** (one tab each) and read
family edits back. It's optional and off until you configure it. The planner is
always the source of truth.

- **Push** (planner → Sheet): fills/overwrites each tab from the planner.
- **Pull** (Sheet → planner): imports edits family made in the Sheet.

It uses a Google **service account** (not a personal login) so it works on the
deployed server without anyone staying signed in.

---

## One-time setup (~10 minutes)

You do this once, ideally right after we deploy (the keys live on the server).

1. **Create the Sheet.** In Google Drive → New → Google Sheets. Name it e.g.
   "Akansha & Priyal — Planner". From its URL copy the **ID** (the long code
   between `/d/` and `/edit`).

2. **Create a Google Cloud project.** Go to https://console.cloud.google.com →
   create a project (any name) → in "APIs & Services → Library" enable
   **Google Sheets API**.

3. **Create a service account.** APIs & Services → Credentials → Create
   credentials → **Service account**. Give it a name; no roles needed. Open it →
   **Keys** → Add key → **JSON** → download the file. It contains a
   `client_email` like `wedding@…iam.gserviceaccount.com`.

4. **Share the Sheet with that email.** Open your Sheet → Share → paste the
   service account's `client_email` → give it **Editor** → Send.

5. **Set two environment variables** on the server (on Render: your service →
   Environment):
   - `GOOGLE_SHEET_ID` = the ID from step 1
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = the entire contents of the JSON file from
     step 3 (paste it as one value)

   *(Locally instead, put the key in `./secrets/` and set
   `GOOGLE_SERVICE_ACCOUNT_FILE=./secrets/your-key.json`. Never commit the key —
   `secrets/` is git-ignored.)*

6. **Use it.** In the planner's **Sync** panel: **Push to Sheet** fills the Sheet;
   **Pull from Sheet** imports changes family made there.

---

## How it behaves (worth knowing)

- **The planner wins on Push.** Push overwrites the Sheet tabs from the planner,
  so pull *before* you push if family edited the Sheet since the last push.
- **Blank cell = "leave unchanged."** Clearing a cell in the Sheet does **not**
  erase that field in the planner (this protects your data). To clear a field,
  do it in the planner.
- **Linked columns are read-only in the Sheet.** Guest/Vendor/Room/Function
  columns show names for reference; edit those links in the planner.
- **Adding rows from the Sheet:** leave the **ID blank** and fill the required
  field (e.g. a guest's Name). On the next Pull it's created and its new ID is
  written back automatically (so it's never duplicated). Tables that must link to
  something — Room allocation, Travel, Run-of-show — are added in the app, not the
  Sheet.

## No-setup alternative

If you'd rather skip all of the above, the planner's **⬇ Excel** button already
exports every module as a ready-to-open workbook you can drop into Google Sheets
anytime — no keys, no configuration.
