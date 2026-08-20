/**
 * Wedding_AP - REST API
 * Generic CRUD for every resource in SCHEMA + a few special endpoints.
 */
const express = require('express');
const router = express.Router();
const db = require('../db');
const { buildWorkbook } = require('../sheets');
const sync = require('../sheets-sync');

const RESOURCES = Object.keys(db.SCHEMA);
function isResource(name) { return RESOURCES.includes(name); }

// Expose the schema so the front-end can render itself.
router.get('/schema', (req, res) => {
  // Strip the JS `formula` functions from computed columns before sending.
  const clean = {};
  for (const [k, def] of Object.entries(db.SCHEMA)) {
    clean[k] = {
      ...def,
      computed: (def.computed || []).map(c => ({ key: c.key, label: c.label })),
    };
  }
  res.json(clean);
});

router.get('/dashboard', (req, res) => res.json(db.dashboard()));

// Settings (couple names, wedding date, hashtag, ...)
router.get('/settings', (req, res) => res.json(db.getSettings()));
router.put('/settings', (req, res) => res.json(db.setSettings(req.body || {})));

// ---- Guests: invitations + convenience link ----
router.get('/guests/:id/functions', (req, res) => {
  res.json(db.getGuestFunctions(Number(req.params.id)));
});
router.put('/guests/:id/functions', (req, res) => {
  const ids = Array.isArray(req.body.function_ids) ? req.body.function_ids.map(Number) : [];
  res.json(db.setGuestFunctions(Number(req.params.id), ids));
});

// ---- Full workbook export (all modules -> one .xlsx, Google-Sheets ready) ----
router.get('/export.xlsx', async (req, res) => {
  try {
    const proto = req.headers['x-forwarded-proto'] || req.protocol;
    const baseUrl = `${proto}://${req.get('host')}`;
    const wb = buildWorkbook(baseUrl);
    res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    res.setHeader('Content-Disposition', 'attachment; filename="Wedding_AP-planner.xlsx"');
    await wb.xlsx.write(res);
    res.end();
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ---- Two-way Google Sheets sync ----
router.get('/sync/status', (req, res) => res.json(sync.status()));

router.post('/sync/push', async (req, res) => {
  try {
    const proto = req.headers['x-forwarded-proto'] || req.protocol;
    const baseUrl = `${proto}://${req.get('host')}`;
    res.json({ ok: true, result: await sync.push(baseUrl) });
  } catch (e) { res.status(400).json({ ok: false, error: e.message }); }
});

router.post('/sync/pull', async (req, res) => {
  try {
    res.json({ ok: true, result: await sync.pull() });
  } catch (e) { res.status(400).json({ ok: false, error: e.message }); }
});

// ---- CSV export for the Google Sheets mirror / backup ----
router.get('/export/:resource.csv', (req, res) => {
  const { resource } = req.params;
  if (!isResource(resource)) return res.status(404).json({ error: 'Unknown resource' });
  const rows = db.list(resource);
  const cols = db.SCHEMA[resource].columns.map(c => c.key)
    .concat((db.SCHEMA[resource].computed || []).map(c => c.key));
  const header = ['id', ...cols];
  const esc = v => {
    if (v == null) return '';
    const s = String(v).replace(/"/g, '""');
    return /[",\n]/.test(s) ? `"${s}"` : s;
  };
  const lines = [header.join(',')];
  rows.forEach(r => lines.push(header.map(c => esc(r[c])).join(',')));
  res.setHeader('Content-Type', 'text/csv');
  res.setHeader('Content-Disposition', `attachment; filename="${resource}.csv"`);
  res.send(lines.join('\n'));
});

// ---- Generic CRUD (must come after the specific routes above) ----
router.get('/:resource', (req, res) => {
  const { resource } = req.params;
  if (!isResource(resource)) return res.status(404).json({ error: 'Unknown resource' });
  res.json(db.list(resource));
});

router.get('/:resource/:id', (req, res) => {
  const { resource, id } = req.params;
  if (!isResource(resource)) return res.status(404).json({ error: 'Unknown resource' });
  const row = db.getOne(resource, Number(id));
  if (!row) return res.status(404).json({ error: 'Not found' });
  res.json(row);
});

router.post('/:resource', (req, res) => {
  const { resource } = req.params;
  if (!isResource(resource)) return res.status(404).json({ error: 'Unknown resource' });
  res.status(201).json(db.create(resource, req.body || {}));
});

router.put('/:resource/:id', (req, res) => {
  const { resource, id } = req.params;
  if (!isResource(resource)) return res.status(404).json({ error: 'Unknown resource' });
  res.json(db.update(resource, Number(id), req.body || {}));
});

router.delete('/:resource/:id', (req, res) => {
  const { resource, id } = req.params;
  if (!isResource(resource)) return res.status(404).json({ error: 'Unknown resource' });
  res.json(db.remove(resource, Number(id)));
});

module.exports = router;
