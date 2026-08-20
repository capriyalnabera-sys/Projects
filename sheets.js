/**
 * Wedding_AP - Google-Sheets-ready workbook export.
 * Builds a multi-tab .xlsx (one tab per module) that imports cleanly into
 * Google Sheets or Excel. References (vendor/guest/function/room) are resolved
 * to readable names, checkboxes become Yes/No, and guests include their invite
 * link so the whole plan is portable in one file.
 */
const ExcelJS = require('exceljs');
const db = require('./db');

const ACCENT = 'FF9C294B';

function refDisplay(refTable, row) {
  if (!row) return '';
  if (refTable === 'rooms') return [row.hotel, row.room_number].filter(Boolean).join(' · ') || ('#' + row.id);
  return row.name || row.title || row.item || row.person || ('#' + row.id);
}

function buildRefMap(refTable) {
  const map = {};
  db.list(refTable).forEach(r => { map[r.id] = refDisplay(refTable, r); });
  return map;
}

function sanitizeSheetName(name, used) {
  let n = String(name).replace(/[\\\/\?\*\[\]:]/g, '-').slice(0, 31).trim() || 'Sheet';
  let base = n, i = 2;
  while (used.has(n)) { n = (base.slice(0, 28) + ' ' + i).slice(0, 31); i++; }
  used.add(n);
  return n;
}

function styleHeader(ws) {
  const row = ws.getRow(1);
  row.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11 };
  row.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: ACCENT } };
  row.alignment = { vertical: 'middle' };
  row.height = 20;
  ws.views = [{ state: 'frozen', ySplit: 1 }];
}

function buildWorkbook(baseUrl) {
  const wb = new ExcelJS.Workbook();
  wb.creator = 'Wedding_AP';
  wb.created = undefined;

  const s = db.getSettings();
  const d = db.dashboard();
  const used = new Set();

  // --- Summary sheet ---
  const sum = wb.addWorksheet(sanitizeSheetName('Summary', used), { properties: { tabColor: { argb: ACCENT } } });
  sum.columns = [{ width: 28 }, { width: 40 }];
  sum.addRow(['Wedding', `${s.bride_name || ''} & ${s.groom_name || ''}`]);
  sum.addRow(['Date', s.wedding_date || '']);
  sum.addRow(['Hashtag', s.hashtag || '']);
  sum.addRow(['RSVP by', s.rsvp_deadline || '']);
  sum.addRow([]);
  sum.addRow(['Guests', d.counts.guests]);
  sum.addRow(['RSVP yes / no / pending', `${d.rsvp.yes} / ${d.rsvp.no} / ${d.rsvp.pending}`]);
  sum.addRow(['Expected headcount', d.rsvp.headcount]);
  sum.addRow(['Budget (actual)', d.budget.actual]);
  sum.addRow(['Budget paid', d.budget.paid]);
  sum.addRow(['Budget balance', d.budget.balance]);
  sum.addRow(['Vendor balance due', d.vendors.balance]);
  sum.addRow(['Tasks done / total', `${d.tasks.done} / ${d.tasks.total}`]);
  sum.getColumn(1).font = { bold: true };
  sum.addRow([]);
  sum.addRow(['Exported from Wedding_AP', 'Re-download any time from the planner to refresh this file.']);

  // --- One sheet per module ---
  for (const [table, def] of Object.entries(db.SCHEMA)) {
    const ws = wb.addWorksheet(sanitizeSheetName(def.label, used));
    const refMaps = {};
    def.columns.filter(c => c.type === 'ref').forEach(c => { refMaps[c.key] = buildRefMap(c.ref); });

    const headers = ['ID', ...def.columns.map(c => c.label), ...(def.computed || []).map(c => c.label)];
    if (table === 'guests') headers.push('Invite link');
    ws.addRow(headers);

    db.list(table).forEach(r => {
      const cells = [r.id];
      def.columns.forEach(c => {
        let v = r[c.key];
        if (c.type === 'ref') v = v == null || v === '' ? '' : (refMaps[c.key][v] || '');
        else if (c.type === 'checkbox') v = v ? 'Yes' : '';
        else if ((c.type === 'money' || c.type === 'number')) v = (v == null || v === '') ? null : Number(v);
        cells.push(v == null ? '' : v);
      });
      (def.computed || []).forEach(c => cells.push(Number(r[c.key]) || 0));
      if (table === 'guests') cells.push(r.invite_token ? `${baseUrl}/i/${r.invite_token}` : '');
      ws.addRow(cells);
    });

    // widths
    ws.columns.forEach((col, idx) => {
      let max = String(headers[idx] || '').length;
      col.eachCell({ includeEmpty: false }, cell => {
        const len = cell.value == null ? 0 : String(cell.value).length;
        if (len > max) max = len;
      });
      col.width = Math.min(Math.max(max + 2, 8), 42);
    });
    styleHeader(ws);
  }

  return wb;
}

module.exports = { buildWorkbook };
