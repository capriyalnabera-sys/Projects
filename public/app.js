/* Wedding_AP - planner front-end. Everything is driven by /api/schema. */

const state = { schema: {}, settings: {}, view: 'dashboard', rows: [], filter: '', refCache: {} };
let editingRow = null;
function safeUrl(u) { return /^(https?:|mailto:)/i.test(String(u || '').trim()) ? u : '#'; }

// ---- tiny helpers ----
const $ = sel => document.querySelector(sel);
async function api(path, method = 'GET', body) {
  const opt = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const r = await fetch('/api' + path, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.headers.get('content-type')?.includes('json') ? r.json() : r.text();
}
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('show'), 2200);
}
function money(v) { const n = parseFloat(v); return isNaN(n) || n === 0 ? '' : '₹' + n.toLocaleString('en-IN'); }
function esc(s) { return (s == null ? '' : String(s)).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function slug(v) { return String(v || '').toLowerCase().trim(); }

function displayName(resource, row) {
  if (!row) return '';
  if (resource === 'rooms') return [row.hotel, row.room_number].filter(Boolean).join(' · ') || ('#' + row.id);
  return row.name || row.title || row.item || row.person || row.activity || ('#' + row.id);
}

async function refList(resource) {
  if (!state.refCache[resource]) state.refCache[resource] = await api('/' + resource);
  return state.refCache[resource];
}
function refName(resource, id) {
  const list = state.refCache[resource] || [];
  const row = list.find(r => String(r.id) === String(id));
  return row ? displayName(resource, row) : '';
}

// ---- boot ----
async function boot() {
  try {
    state.schema = await api('/schema');
    state.settings = await api('/settings');
  } catch (e) { return; }
  applyBranding();
  buildNav();
  route('dashboard');
}

function applyBranding() {
  const s = state.settings;
  $('#brandInitials').textContent = s.couple_initials || 'A & P';
  $('#brandSub').textContent = s.hashtag || 'Wedding planner';
}

function buildNav() {
  const nav = $('#nav');
  const items = [{ key: 'dashboard', label: 'Dashboard', icon: '📊' }];
  const resources = Object.entries(state.schema)
    .map(([key, def]) => ({ key, ...def }))
    .sort((a, b) => (a.order || 99) - (b.order || 99));
  let html = '';
  html += navLink(items[0]);
  html += `<div class="group-label">Planning</div>`;
  resources.forEach(r => { html += navLink({ key: r.key, label: r.label, icon: r.icon }); });
  html += `<div class="group-label">Setup</div>`;
  html += navLink({ key: 'settings', label: 'Couple & invite settings', icon: '⚙️' });
  nav.innerHTML = html;
}
function navLink(it) {
  return `<a data-view="${it.key}" onclick="route('${it.key}')"><span class="ico">${it.icon}</span> ${esc(it.label)}</a>`;
}

function route(view) {
  state.view = view; state.filter = '';
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  $('#sidebar').classList.remove('open');
  if (view === 'dashboard') return renderDashboard();
  if (view === 'settings') return renderSettings();
  return renderResource(view);
}

// ---- dashboard ----
async function renderDashboard() {
  $('#pageTitle').textContent = 'Dashboard';
  $('#pageHint').textContent = 'Your wedding at a glance';
  $('#addBtn').style.display = 'none';
  const [d, syncStatus] = await Promise.all([api('/dashboard'), api('/sync/status').catch(() => ({ configured: false }))]);
  const s = d.settings;
  let daysHtml = '';
  if (s.wedding_date) {
    const days = Math.ceil((new Date(s.wedding_date) - new Date()) / 86400000);
    daysHtml = days >= 0
      ? `<div class="days">${days}<small> days to go</small></div>`
      : `<div class="days"><small>Married! 🎉</small></div>`;
  } else {
    daysHtml = `<div class="days"><small>Set your date in Settings</small></div>`;
  }
  const budgetPct = d.budget.actual ? Math.min(100, Math.round(d.budget.paid / d.budget.actual * 100)) : 0;
  const rsvpTotal = d.rsvp.yes + d.rsvp.no + d.rsvp.pending || 1;
  const taskPct = d.tasks.total ? Math.round(d.tasks.done / d.tasks.total * 100) : 0;

  $('#content').innerHTML = `
    <div class="grid cards">
      <div class="card countdown">
        <div class="names">${esc(s.bride_name || 'Bride')} &amp; ${esc(s.groom_name || 'Groom')}</div>
        <div class="date">${s.wedding_date ? formatDateRange(s.wedding_date, s.wedding_date_end) : ''}</div>
        ${daysHtml}
      </div>

      <div class="card"><div class="k">Guests</div><div class="v">${d.counts.guests}</div>
        <div class="sub">${d.rsvp.headcount} expected heads</div></div>

      <div class="card"><div class="k">RSVP</div>
        <div class="v">${d.rsvp.yes}<small> yes</small></div>
        <div class="sub">${d.rsvp.no} no · ${d.rsvp.pending} pending</div>
        <div class="bar"><span style="width:${Math.round(d.rsvp.yes / rsvpTotal * 100)}%"></span></div></div>

      <div class="card"><div class="k">Budget</div>
        <div class="v">${money(d.budget.actual) || '₹0'}</div>
        <div class="sub">${money(d.budget.paid) || '₹0'} paid · ${money(d.budget.balance) || '₹0'} left</div>
        <div class="bar"><span style="width:${budgetPct}%"></span></div></div>

      <div class="card"><div class="k">Vendors</div><div class="v">${d.vendors.count}</div>
        <div class="sub">${money(d.vendors.balance) || '₹0'} balance due</div></div>

      <div class="card"><div class="k">To-do</div>
        <div class="v">${d.tasks.done}<small> / ${d.tasks.total}</small></div>
        <div class="sub">${d.tasks.open} open</div>
        <div class="bar"><span style="width:${taskPct}%"></span></div></div>

      <div class="card"><div class="k">Functions</div><div class="v">${d.counts.functions}</div>
        <div class="sub">${d.counts.performances} performances planned</div></div>

      <div class="card"><div class="k">Rooms</div><div class="v">${d.counts.rooms}</div>
        <div class="sub">for out-of-town guests</div></div>
    </div>
    <p class="section-help" style="margin-top:22px">Tip: start with <b>Functions</b> (your events), then add <b>Guests</b> and send them their personalised invite links from the Guests tab.</p>
    <p class="section-help" style="margin-top:-8px">Backup anytime with <b>⬇ Excel</b> (top-right) — one workbook with every module as a tab, ready to open or import into Google Sheets.</p>
    ${syncPanel(syncStatus)}
  `;
}

function formatDate(d) {
  if (!d) return '';
  const dt = new Date(d + (d.length === 10 ? 'T00:00:00' : ''));
  if (isNaN(dt)) return esc(d);
  return dt.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
}
function formatDateRange(start, end) {
  if (!start) return '';
  if (!end || end === start) return formatDate(start);
  const a = new Date(start + (start.length === 10 ? 'T00:00:00' : ''));
  const b = new Date(end + (end.length === 10 ? 'T00:00:00' : ''));
  if (isNaN(a) || isNaN(b)) return formatDate(start);
  if (a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear())
    return `${a.getDate()}–${b.getDate()} ${a.toLocaleDateString('en-IN', { month: 'long' })} ${a.getFullYear()}`;
  return `${a.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} – ${b.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}`;
}

function syncPanel(st) {
  if (st && st.configured) {
    return `<div class="card" style="grid-column:1/-1;margin-top:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
        <div>
          <div class="k">🔄 Google Sheets sync — connected</div>
          <div class="sub">${st.sheetUrl ? `<a href="${esc(safeUrl(st.sheetUrl))}" target="_blank" rel="noopener">Open the Sheet</a> · ` : ''}service account: ${esc(st.serviceAccount || '')}</div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn small primary" onclick="syncPush(this)">⬆ Push to Sheet</button>
          <button class="btn small" onclick="syncPull(this)">⬇ Pull from Sheet</button>
        </div>
      </div></div>`;
  }
  return `<div class="card" style="grid-column:1/-1;margin-top:8px">
    <div class="k">🔄 Google Sheets sync — not set up</div>
    <div class="sub">Add a Google service account and a Sheet ID (env: <code>GOOGLE_SHEET_ID</code>, <code>GOOGLE_SERVICE_ACCOUNT_JSON</code>) to enable two-way sync. See the README. Until then, use <b>⬇ Excel</b> above.</div>
  </div>`;
}

async function syncPush(btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Pushing…'; }
  try {
    const r = await api('/sync/push', 'POST', {});
    toast(`Pushed ${r.result.pushed} tabs to Google Sheets`);
  } catch (e) { toast('Push failed: ' + e.message); }
  if (btn) { btn.disabled = false; btn.textContent = '⬆ Push to Sheet'; }
}

async function syncPull(btn) {
  if (!confirm('Pull changes from the Google Sheet into the planner? This updates rows by their ID.')) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Pulling…'; }
  try {
    const r = await api('/sync/pull', 'POST', {});
    const n = Object.values(r.result).reduce((a, x) => a + x.updated + x.created, 0);
    toast(n ? `Pulled ${n} change(s) from Google Sheets` : 'Sheet already in sync');
    state.refCache = {};
  } catch (e) { toast('Pull failed: ' + e.message); }
  if (btn) { btn.disabled = false; btn.textContent = '⬇ Pull from Sheet'; }
}

// ---- generic resource table ----
async function renderResource(resource) {
  const def = state.schema[resource];
  $('#pageTitle').textContent = def.label;
  $('#pageHint').textContent = def.help || '';
  $('#addBtn').style.display = '';
  $('#addBtn').onclick = () => openForm(resource);

  // preload referenced resources for display + pickers
  const refs = def.columns.filter(c => c.type === 'ref').map(c => c.ref);
  await Promise.all([...new Set(refs)].map(refList));
  state.rows = await api('/' + resource);
  state.refCache[resource] = state.rows;

  drawTable(resource);
}

function drawTable(resource) {
  const def = state.schema[resource];
  const cols = def.listColumns
    ? def.listColumns.map(k => def.columns.find(c => c.key === k)).filter(Boolean)
    : def.columns.filter(c => c.type !== 'textarea').slice(0, 7);
  const computed = def.computed || [];
  const q = slug(state.filter);
  const rows = state.rows.filter(r => !q || JSON.stringify(r).toLowerCase().includes(q));

  const isGuests = resource === 'guests';
  let html = `
    <div class="toolbar">
      <input class="search" placeholder="Search ${esc(def.label.toLowerCase())}…" value="${esc(state.filter)}"
        oninput="state.filter=this.value; drawTable('${resource}')" />
      <a class="btn small" href="/api/export/${resource}.csv" title="Download CSV for your Google Sheet">⬇ CSV</a>
      <button class="btn small primary" onclick="openForm('${resource}')">+ ${esc(def.singular)}</button>
    </div>`;

  if (!rows.length) {
    html += `<div class="table-wrap"><div class="empty">Nothing here yet. Click “+ ${esc(def.singular)}” to add the first one.</div></div>`;
    $('#content').innerHTML = html; return;
  }

  html += `<div class="table-wrap"><table><thead><tr>`;
  cols.forEach(c => html += `<th>${esc(c.label)}</th>`);
  computed.forEach(c => html += `<th>${esc(c.label)}</th>`);
  if (isGuests) html += `<th>Invite</th>`;
  html += `<th></th></tr></thead><tbody>`;

  rows.forEach(r => {
    html += `<tr>`;
    cols.forEach(c => html += `<td><div class="cellwrap">${cell(c, r)}</div></td>`);
    computed.forEach(c => html += `<td>${money(r[c.key]) || '—'}</td>`);
    if (isGuests) {
      html += `<td><div style="display:flex;gap:6px">
        <button class="btn small" onclick="event.stopPropagation(); waInvite(${r.id})" title="Send invite on WhatsApp">💬 WhatsApp</button>
        <button class="btn small" onclick="event.stopPropagation(); copyInvite('${r.invite_token}')" title="Copy invite link">🔗</button>
      </div></td>`;
    }
    html += `<td class="actions">
      <button class="btn small" onclick="openForm('${resource}', ${r.id})">Edit</button>
      <button class="btn small danger" onclick="delRow('${resource}', ${r.id})">Delete</button>
    </td></tr>`;
  });
  html += `</tbody></table></div>`;
  $('#content').innerHTML = html;
}

function cell(col, row) {
  const v = row[col.key];
  if (col.type === 'checkbox') return v ? '✓' : '';
  if (col.type === 'money') return money(v) || '—';
  if (col.type === 'date') return v ? formatDate(v) : '';
  if (col.type === 'ref') return esc(refName(col.ref, v)) || '—';
  if (col.type === 'select' && v) return `<span class="pill ${esc(slug(v))}">${esc(v)}</span>`;
  return esc(v) || '';
}

// ---- add / edit modal ----
async function openForm(resource, id) {
  const def = state.schema[resource];
  const row = id ? await api(`/${resource}/${id}`) : {};
  editingRow = row;
  const refs = def.columns.filter(c => c.type === 'ref').map(c => c.ref);
  await Promise.all([...new Set(refs)].map(refList));

  $('#modalTitle').textContent = (id ? 'Edit ' : 'New ') + def.singular.toLowerCase();
  let body = '';
  def.columns.forEach(c => { body += fieldHtml(c, row[c.key]); });

  // Guests: pick which functions they're invited to + show invite link
  if (resource === 'guests') {
    const funcs = await refList('functions');
    let invited = [];
    if (id) invited = (await api(`/guests/${id}/functions`)).filter(x => x.invited).map(x => x.function_id);
    body += `<div class="field"><label>Invited to which functions?</label><div class="check-list">`;
    if (!funcs.length) body += `<div class="section-help">Add functions first (Functions tab).</div>`;
    funcs.forEach(f => {
      body += `<label><input type="checkbox" name="fn" value="${f.id}" ${invited.includes(f.id) ? 'checked' : ''}/> ${esc(f.name)}</label>`;
    });
    body += `</div></div>`;
    if (id && row.invite_token) {
      const link = `${location.origin}/i/${row.invite_token}`;
      body += `<div class="field"><label>Personalised invite link</label>
        <div class="link-box"><code id="lnk">${esc(link)}</code>
        <button class="btn small" type="button" onclick="waInvite(${id})">💬 WhatsApp</button>
        <button class="btn small" type="button" onclick="copyInvite('${row.invite_token}')">Copy</button></div></div>`;
    }
  }

  $('#modalBody').innerHTML = body;
  $('#modalFooter').innerHTML = `
    <button class="btn" onclick="closeModal()">Cancel</button>
    <button class="btn primary" onclick="saveForm('${resource}', ${id || 'null'})">${id ? 'Save' : 'Add'}</button>`;
  $('#modalBack').classList.add('open');
}

function fieldHtml(col, value) {
  const id = 'f_' + col.key;
  let input;
  if (col.type === 'textarea') {
    input = `<textarea id="${id}">${esc(value)}</textarea>`;
  } else if (col.type === 'checkbox') {
    input = `<label style="display:flex;gap:8px;align-items:center;font-size:14px;color:var(--ink)">
      <input type="checkbox" id="${id}" style="width:auto" ${value ? 'checked' : ''}/> Yes</label>`;
  } else if (col.type === 'select') {
    input = `<select id="${id}"><option value="">—</option>` +
      col.options.map(o => `<option ${slug(o) === slug(value) ? 'selected' : ''}>${esc(o)}</option>`).join('') + `</select>`;
  } else if (col.type === 'ref') {
    const list = state.refCache[col.ref] || [];
    input = `<select id="${id}"><option value="">—</option>` +
      list.map(r => `<option value="${r.id}" ${String(r.id) === String(value) ? 'selected' : ''}>${esc(displayName(col.ref, r))}</option>`).join('') + `</select>`;
  } else {
    const t = col.type === 'money' || col.type === 'number' ? 'number'
      : col.type === 'date' ? 'date' : col.type === 'time' ? 'time'
      : col.type === 'datetime' ? 'datetime-local' : 'text';
    input = `<input type="${t}" id="${id}" value="${esc(value)}" ${col.type === 'money' || col.type === 'number' ? 'step="any"' : ''}/>`;
  }
  return `<div class="field"><label>${esc(col.label)}${col.required ? ' *' : ''}</label>${input}</div>`;
}

async function saveForm(resource, id) {
  const def = state.schema[resource];
  const body = {};
  let missing = null;
  def.columns.forEach(c => {
    const el = document.getElementById('f_' + c.key);
    if (!el) return;
    let v = c.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
    if (c.required && (v === '' || v == null)) missing = c.label;
    body[c.key] = v;
  });
  if (missing) { toast(missing + ' is required'); return; }

  try {
    let saved;
    if (id) saved = await api(`/${resource}/${id}`, 'PUT', body);
    else saved = await api(`/${resource}`, 'POST', body);

    if (resource === 'guests') {
      const fnIds = [...document.querySelectorAll('input[name="fn"]:checked')].map(x => Number(x.value));
      await api(`/guests/${saved.id}/functions`, 'PUT', { function_ids: fnIds });
    }
    state.refCache = {}; // invalidate caches (names may have changed)
    closeModal();
    toast('Saved');
    renderResource(resource);
  } catch (e) { toast('Error: ' + e.message); }
}

async function delRow(resource, id) {
  if (!confirm('Delete this ' + state.schema[resource].singular.toLowerCase() + '?')) return;
  await api(`/${resource}/${id}`, 'DELETE');
  state.refCache = {};
  toast('Deleted');
  renderResource(resource);
}

function copyInvite(token) {
  const link = `${location.origin}/i/${token}`;
  navigator.clipboard?.writeText(link).then(() => toast('Invite link copied')).catch(() => {
    prompt('Copy this invite link:', link);
  });
}

function inviteMessage(name, token) {
  const s = state.settings || {};
  const link = `${location.origin}/i/${token}`;
  const tpl = s.invite_message_template || 'Dear {name}, here is your wedding invitation: {link}';
  return tpl
    .replace(/{name}/g, name || 'there')
    .replace(/{link}/g, link)
    .replace(/{bride}/g, s.bride_name || '')
    .replace(/{groom}/g, s.groom_name || '')
    .replace(/{date}/g, s.wedding_date ? formatDate(s.wedding_date) : '')
    .replace(/{hashtag}/g, s.hashtag || '');
}

// Open WhatsApp with a pre-filled personalised invite for this guest.
function waInvite(id) {
  const g = (editingRow && String(editingRow.id) === String(id)) ? editingRow : (state.rows || []).find(r => String(r.id) === String(id));
  if (!g) { toast('Guest not found'); return; }
  if (!g.invite_token) { toast('No invite link yet — save the guest first'); return; }
  const digits = (g.phone || '').replace(/\D/g, '');
  const url = `https://wa.me/${digits}?text=${encodeURIComponent(inviteMessage(g.name, g.invite_token))}`;
  window.open(url, '_blank', 'noopener');
}

function closeModal() { $('#modalBack').classList.remove('open'); }
$('#modalBack')?.addEventListener('click', e => { if (e.target.id === 'modalBack') closeModal(); });

// ---- settings ----
async function renderSettings() {
  $('#pageTitle').textContent = 'Couple & invite settings';
  $('#pageHint').textContent = 'These details appear on the invite website';
  $('#addBtn').style.display = 'none';
  const s = await api('/settings');
  const fields = [
    ['bride_name', 'Bride\'s name', 'text'],
    ['groom_name', 'Groom\'s name', 'text'],
    ['couple_initials', 'Monogram / initials', 'text'],
    ['wedding_date', 'Wedding date (first day)', 'date'],
    ['wedding_date_end', 'Wedding date (last day, optional)', 'date'],
    ['tagline', 'Tagline', 'text'],
    ['hashtag', 'Hashtag', 'text'],
    ['cover_message', 'Invite welcome message', 'textarea'],
    ['invite_message_template', 'WhatsApp invite message — placeholders: {name} {link} {bride} {groom} {date} {hashtag}', 'textarea'],
    ['rsvp_deadline', 'RSVP by', 'date'],
    ['contact_name', 'Contact person', 'text'],
    ['contact_phone', 'Contact phone', 'text'],
  ];
  let html = `<div class="card" style="max-width:620px">`;
  fields.forEach(([k, label, type]) => {
    const v = esc(s[k] || '');
    const input = type === 'textarea' ? `<textarea id="s_${k}">${v}</textarea>`
      : `<input type="${type}" id="s_${k}" value="${v}"/>`;
    html += `<div class="field"><label>${label}</label>${input}</div>`;
  });
  html += `<button class="btn primary" onclick="saveSettings()">Save settings</button></div>`;
  $('#content').innerHTML = html;
}

async function saveSettings() {
  const keys = ['bride_name', 'groom_name', 'couple_initials', 'wedding_date', 'wedding_date_end', 'tagline', 'hashtag', 'cover_message', 'invite_message_template', 'rsvp_deadline', 'contact_name', 'contact_phone'];
  const body = {};
  keys.forEach(k => { const el = document.getElementById('s_' + k); if (el) body[k] = el.value; });
  state.settings = await api('/settings', 'PUT', body);
  applyBranding();
  toast('Settings saved');
}

async function logout() { await api('/logout', 'POST').catch(() => {}); location.href = '/login'; }

boot();
