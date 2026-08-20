/**
 * Wedding_AP - two-way Google Sheets sync (optional).
 *
 * Uses a Google **service account** so it also works on a deployed server
 * (unlike a personal OAuth session). Configure via env:
 *   GOOGLE_SHEET_ID              the spreadsheet to sync with
 *   GOOGLE_SERVICE_ACCOUNT_JSON  the service-account key as one line of JSON
 *   GOOGLE_SERVICE_ACCOUNT_FILE  ...or a path to the key file
 * Share that Sheet with the service account's client_email (Editor).
 *
 * push()  planner -> Sheet   (overwrites each tab from the database)
 * pull()  Sheet -> planner   (upserts rows by their ID column)
 *
 * Reference columns (vendor/guest/room/function) are written as readable
 * names and are treated as read-only on pull, so family can edit everything
 * else in Sheets without breaking the links.
 */
const fs = require('fs');
const db = require('./db');

const SHEET_ID = process.env.GOOGLE_SHEET_ID || '';

function readCreds() {
  let raw = null;
  if (process.env.GOOGLE_SERVICE_ACCOUNT_JSON && process.env.GOOGLE_SERVICE_ACCOUNT_JSON.trim()) {
    raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON.trim();
  } else if (process.env.GOOGLE_SERVICE_ACCOUNT_FILE && process.env.GOOGLE_SERVICE_ACCOUNT_FILE.trim()) {
    try { raw = fs.readFileSync(process.env.GOOGLE_SERVICE_ACCOUNT_FILE.trim(), 'utf8'); } catch (e) { return null; }
  }
  if (!raw) return null;
  try { return JSON.parse(raw); }
  catch (e) {
    try { return JSON.parse(Buffer.from(raw, 'base64').toString('utf8')); } catch (_) { return null; }
  }
}

function isConfigured() { return !!(readCreds() && SHEET_ID); }

function status() {
  const c = readCreds();
  return {
    configured: isConfigured(),
    sheetId: SHEET_ID || null,
    sheetUrl: SHEET_ID ? `https://docs.google.com/spreadsheets/d/${SHEET_ID}` : null,
    serviceAccount: c ? c.client_email : null,
    reason: isConfigured() ? null
      : (!SHEET_ID ? 'GOOGLE_SHEET_ID not set' : 'Service-account key not set/valid'),
  };
}

let _client = null;
function client() {
  if (_client) return _client;
  const { JWT } = require('google-auth-library');
  const c = readCreds();
  if (!c) throw new Error('Google service-account key is not configured');
  _client = new JWT({ email: c.client_email, key: c.private_key, scopes: ['https://www.googleapis.com/auth/spreadsheets'] });
  return _client;
}

async function api(method, sub, data) {
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${sub}`;
  const res = await client().request({ method, url, data });
  return res.data;
}
const range = tab => encodeURIComponent(`'${tab.replace(/'/g, "''")}'`);
const a1 = (tab, cell) => `'${String(tab).replace(/'/g, "''")}'!${cell}`;

// ---- tab layout (kept identical between push and pull) ----
function sanitize(name, used) {
  let n = String(name).replace(/[\\\/\?\*\[\]:]/g, '-').slice(0, 31).trim() || 'Sheet';
  let base = n, i = 2;
  while (used.has(n)) { n = (base.slice(0, 28) + ' ' + i).slice(0, 31); i++; }
  used.add(n);
  return n;
}
function moduleTabs() {
  const used = new Set(['Summary']);
  return Object.entries(db.SCHEMA).map(([table, def]) => ({ table, def, tab: sanitize(def.label, used) }));
}
function refMap(refTable) {
  const m = {};
  db.list(refTable).forEach(r => {
    m[r.id] = refTable === 'rooms'
      ? [r.hotel, r.room_number].filter(Boolean).join(' · ') || ('#' + r.id)
      : (r.name || r.title || r.item || r.person || ('#' + r.id));
  });
  return m;
}
function header(def, table) {
  const h = ['ID', ...def.columns.map(c => c.label), ...(def.computed || []).map(c => c.label)];
  if (table === 'guests') h.push('Invite link');
  return h;
}
function rows(table, def, baseUrl) {
  const refs = {};
  def.columns.filter(c => c.type === 'ref').forEach(c => { refs[c.key] = refMap(c.ref); });
  return db.list(table).map(r => {
    const cells = [r.id];
    def.columns.forEach(c => {
      let v = r[c.key];
      if (c.type === 'ref') v = (v == null || v === '') ? '' : (refs[c.key][v] || '');
      else if (c.type === 'checkbox') v = v ? 'Yes' : '';
      else if (c.type === 'money' || c.type === 'number') v = (v == null || v === '') ? '' : Number(v);
      cells.push(v == null ? '' : v);
    });
    (def.computed || []).forEach(c => cells.push(Number(r[c.key]) || 0));
    if (table === 'guests') cells.push(r.invite_token ? `${baseUrl}/i/${r.invite_token}` : '');
    return cells;
  });
}
function summaryRows() {
  const s = db.getSettings(), d = db.dashboard();
  return [
    ['Wedding', `${s.bride_name || ''} & ${s.groom_name || ''}`],
    ['Dates', s.wedding_date_end ? `${s.wedding_date || ''} to ${s.wedding_date_end}` : (s.wedding_date || '')],
    ['Hashtag', s.hashtag || ''],
    ['Guests', d.counts.guests],
    ['RSVP yes / no / pending', `${d.rsvp.yes} / ${d.rsvp.no} / ${d.rsvp.pending}`],
    ['Expected headcount', d.rsvp.headcount],
    ['Budget actual / paid / balance', `${d.budget.actual} / ${d.budget.paid} / ${d.budget.balance}`],
    ['Vendor balance due', d.vendors.balance],
    ['Tasks done / total', `${d.tasks.done} / ${d.tasks.total}`],
    ['', ''],
    ['Synced from Wedding_AP', 'Edit any tab; press "Pull from Sheet" in the planner to import changes.'],
  ];
}

// ---- push: planner -> Sheet ----
async function push(baseUrl) {
  if (!isConfigured()) throw new Error(status().reason || 'not configured');
  const meta = await api('GET', SHEET_ID);
  const existing = new Set((meta.sheets || []).map(s => s.properties.title));
  const tabs = moduleTabs();

  const add = [];
  ['Summary', ...tabs.map(t => t.tab)].forEach(title => {
    if (!existing.has(title)) add.push({ addSheet: { properties: { title } } });
  });
  if (add.length) await api('POST', `${SHEET_ID}:batchUpdate`, { requests: add });

  const data = [{ range: a1('Summary', 'A1'), values: summaryRows() }];
  await api('POST', `${SHEET_ID}/values/${range('Summary')}:clear`);
  for (const t of tabs) {
    await api('POST', `${SHEET_ID}/values/${range(t.tab)}:clear`);
    data.push({ range: a1(t.tab, 'A1'), values: [header(t.def, t.table), ...rows(t.table, t.def, baseUrl)] });
  }
  await api('POST', `${SHEET_ID}/values:batchUpdate`, { valueInputOption: 'RAW', data });
  return { pushed: tabs.length + 1, tabs: ['Summary', ...tabs.map(t => t.tab)] };
}

// ---- record<->row helpers (pure, unit-testable) ----
function coerce(col, v) {
  if (v === undefined || v === null) return null;
  const s = String(v).trim();
  if (col.type === 'checkbox') return /^(yes|true|1|✓|y)$/i.test(s) ? 1 : 0;
  if (col.type === 'money' || col.type === 'number') {
    const cleaned = s.replace(/[^0-9.\-]/g, '');
    return cleaned === '' ? null : Number(cleaned);   // "TBD" -> null (not 0)
  }
  return s;
}
function rowToRecord(def, headerRow, row) {
  const byLabel = {};
  def.columns.forEach(c => { byLabel[c.label] = c; });
  const rec = {};
  headerRow.forEach((label, idx) => {
    if (idx === 0) return;               // ID column
    const c = byLabel[label];
    if (!c || c.type === 'ref') return;  // computed / invite link / refs are read-only
    const raw = row[idx];
    if (raw === undefined || raw === null || String(raw).trim() === '') return; // blank cell = leave unchanged
    const val = coerce(c, raw);
    if (val === null) return;            // uncoercible (e.g. "TBD" in a number) -> leave unchanged
    rec[c.key] = val;
  });
  return rec;
}

// A blank-ID Sheet row can be created in the planner only if it isn't missing a
// required value we can actually set. Refs can't be set from the Sheet, so a
// table that REQUIRES a ref (room allocation, travel, run-of-show) can't gain
// rows this way — those are added in the app.
function canCreate(def, rec) {
  if (def.columns.some(c => c.required && c.type === 'ref')) return false;
  return !def.columns.some(c => c.required && c.type !== 'ref' && (rec[c.key] == null || rec[c.key] === ''));
}

// ---- pull: Sheet -> planner ----
async function pull() {
  if (!isConfigured()) throw new Error(status().reason || 'not configured');
  const tabs = moduleTabs();
  const summary = {};
  for (const t of tabs) {
    let resp;
    try { resp = await api('GET', `${SHEET_ID}/values/${range(t.tab)}`); }
    catch (e) { continue; }
    const values = resp.values || [];
    if (values.length < 2) continue;
    const head = values[0];
    let updated = 0, created = 0;
    const idWrites = [];
    for (let i = 1; i < values.length; i++) {
      const row = values[i] || [];
      if (row.every(c => c === '' || c == null)) continue;
      const rec = rowToRecord(t.def, head, row);
      const id = row[0];
      const existingId = (id != null && String(id).trim() !== '' && db.getOne(t.table, Number(id))) ? Number(id) : null;
      if (existingId != null) {
        try { db.update(t.table, existingId, rec); updated++; } catch (e) { /* skip bad row */ }
      } else if (canCreate(t.def, rec)) {
        try {
          const createdRow = db.create(t.table, rec);
          created++;
          // Write the new ID back so a later pull updates this row instead of duplicating it.
          idWrites.push({ range: a1(t.tab, 'A' + (i + 1)), values: [[createdRow.id]] });
        } catch (e) { /* skip invalid row */ }
      }
    }
    if (idWrites.length) {
      try { await api('POST', `${SHEET_ID}/values:batchUpdate`, { valueInputOption: 'RAW', data: idWrites }); } catch (e) { /* best effort */ }
    }
    if (updated || created) summary[t.tab] = { updated, created };
  }
  return summary;
}

module.exports = { isConfigured, status, push, pull, rowToRecord, coerce, moduleTabs, canCreate };
