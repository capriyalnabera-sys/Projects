/**
 * Wedding_AP - Database layer (sql.js / SQLite persisted to a file)
 *
 * The whole app is driven by ONE schema definition (see SCHEMA below).
 * The generic CRUD routes and the front-end table UI both read from it,
 * so adding a field or a whole module is a one-place change.
 */
const initSqlJs = require('sql.js');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// Honour WEDDING_DB so a deployment can point at a persistent disk.
const DB_PATH = process.env.WEDDING_DB
  ? path.resolve(process.env.WEDDING_DB)
  : path.join(__dirname, 'wedding.db');

let db = null;
let SQL = null;

async function getDb() {
  if (db) return db;
  SQL = await initSqlJs();
  if (fs.existsSync(DB_PATH)) {
    db = new SQL.Database(fs.readFileSync(DB_PATH));
  } else {
    db = new SQL.Database();
  }
  initializeDatabase();
  return db;
}

function saveDb() {
  if (db) fs.writeFileSync(DB_PATH, Buffer.from(db.export()));
}

// ---------------------------------------------------------------------------
// Schema definition. Each resource lists its columns with a `type` used by the
// front-end to render the right input, and by the API to validate writes.
// types: text | textarea | number | money | date | time | select | checkbox | ref
// A `ref` column points at another resource (foreign key, rendered as a picker).
// ---------------------------------------------------------------------------
const SCHEMA = {
  functions: {
    label: 'Functions',
    singular: 'Function',
    icon: '🎉',
    order: 2,
    help: 'Every ceremony / event of the wedding. This powers the invite site schedule.',
    columns: [
      { key: 'name', label: 'Function', type: 'text', required: true },
      { key: 'event_date', label: 'Date', type: 'date' },
      { key: 'start_time', label: 'Start', type: 'time' },
      { key: 'end_time', label: 'End', type: 'time' },
      { key: 'venue', label: 'Venue', type: 'text' },
      { key: 'address', label: 'Address', type: 'textarea' },
      { key: 'map_url', label: 'Map link', type: 'text' },
      { key: 'dress_code', label: 'Dress code', type: 'text' },
      { key: 'theme_color', label: 'Theme colour', type: 'text' },
      { key: 'sequence', label: 'Order', type: 'number' },
      { key: 'description', label: 'Notes', type: 'textarea' },
    ],
  },

  guests: {
    label: 'Guests',
    singular: 'Guest',
    icon: '💌',
    order: 1,
    help: 'The master guest list. Each guest gets a personalised invite link.',
    listColumns: ['name', 'phone', 'side', 'category', 'city', 'headcount', 'rsvp_status', 'invite_sent'],
    columns: [
      { key: 'name', label: 'Name', type: 'text', required: true },
      { key: 'phone', label: 'Phone', type: 'text' },
      { key: 'email', label: 'Email', type: 'text' },
      { key: 'side', label: 'Side', type: 'select', options: ['Bride', 'Groom', 'Both'] },
      { key: 'category', label: 'Group', type: 'select', options: ['Family', 'Relatives', 'Friends', 'Colleagues', 'Neighbours', 'Other'] },
      { key: 'city', label: 'City', type: 'text' },
      { key: 'headcount', label: 'Headcount', type: 'number' },
      { key: 'meal_preference', label: 'Meal', type: 'select', options: ['Veg', 'Non-veg', 'Jain', 'Vegan', 'No preference'] },
      { key: 'rsvp_status', label: 'RSVP', type: 'select', options: ['Pending', 'Yes', 'No', 'Maybe'] },
      { key: 'invite_sent', label: 'Invite sent', type: 'checkbox' },
      { key: 'rsvp_message', label: 'RSVP message', type: 'textarea' },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  vendors: {
    label: 'Vendors',
    singular: 'Vendor',
    icon: '🤝',
    order: 6,
    help: 'Everyone you have hired, their contacts and money owed.',
    columns: [
      { key: 'name', label: 'Vendor', type: 'text', required: true },
      { key: 'category', label: 'Type', type: 'select', options: ['Caterer', 'Decorator', 'Photographer', 'Videographer', 'DJ / Sound', 'Makeup', 'Mehndi', 'Pandit / Priest', 'Florist', 'Transport', 'Venue', 'Invitations', 'Choreographer', 'Other'] },
      { key: 'contact_name', label: 'Contact person', type: 'text' },
      { key: 'phone', label: 'Phone', type: 'text' },
      { key: 'email', label: 'Email', type: 'text' },
      { key: 'contract_amount', label: 'Contract ₹', type: 'money' },
      { key: 'advance_paid', label: 'Advance ₹', type: 'money' },
      { key: 'status', label: 'Status', type: 'select', options: ['Enquiry', 'Booked', 'Confirmed', 'Completed', 'Cancelled'] },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
    computed: [{ key: 'balance', label: 'Balance ₹', formula: r => num(r.contract_amount) - num(r.advance_paid) }],
  },

  budget_items: {
    label: 'Budget',
    singular: 'Budget item',
    icon: '💰',
    order: 5,
    help: 'Estimated vs actual spend by category. Link an item to a vendor if you like.',
    columns: [
      { key: 'category', label: 'Category', type: 'select', options: ['Venue', 'Catering', 'Decor', 'Photography', 'Attire & Jewellery', 'Makeup', 'Music & Entertainment', 'Invitations', 'Gifts & Favours', 'Transport', 'Accommodation', 'Priest & Rituals', 'Miscellaneous'] },
      { key: 'item', label: 'Item', type: 'text', required: true },
      { key: 'estimated', label: 'Estimated ₹', type: 'money' },
      { key: 'actual', label: 'Actual ₹', type: 'money' },
      { key: 'paid', label: 'Paid ₹', type: 'money' },
      { key: 'vendor_id', label: 'Vendor', type: 'ref', ref: 'vendors' },
      { key: 'due_date', label: 'Due', type: 'date' },
      { key: 'status', label: 'Status', type: 'select', options: ['Planned', 'Partly paid', 'Paid', 'Cancelled'] },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
    computed: [{ key: 'balance', label: 'Balance ₹', formula: r => num(r.actual || r.estimated) - num(r.paid) }],
  },

  rooms: {
    label: 'Rooms',
    singular: 'Room',
    icon: '🏨',
    order: 8,
    help: 'Rooms available for out-of-town guests.',
    columns: [
      { key: 'hotel', label: 'Hotel / Block', type: 'text' },
      { key: 'room_number', label: 'Room no.', type: 'text', required: true },
      { key: 'room_type', label: 'Type', type: 'select', options: ['Single', 'Double', 'Twin', 'Suite', 'Family'] },
      { key: 'capacity', label: 'Capacity', type: 'number' },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  room_allocations: {
    label: 'Room allocation',
    singular: 'Allocation',
    icon: '🗝️',
    order: 9,
    help: 'Which guest is staying in which room.',
    columns: [
      { key: 'guest_id', label: 'Guest', type: 'ref', ref: 'guests', required: true },
      { key: 'room_id', label: 'Room', type: 'ref', ref: 'rooms', required: true },
      { key: 'check_in', label: 'Check-in', type: 'date' },
      { key: 'check_out', label: 'Check-out', type: 'date' },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  travel: {
    label: 'Travel',
    singular: 'Travel detail',
    icon: '✈️',
    order: 10,
    help: 'Arrivals & departures for guests, and who is picking them up.',
    columns: [
      { key: 'guest_id', label: 'Guest', type: 'ref', ref: 'guests', required: true },
      { key: 'direction', label: 'Direction', type: 'select', options: ['Arrival', 'Departure'] },
      { key: 'mode', label: 'Mode', type: 'select', options: ['Flight', 'Train', 'Bus', 'Car', 'Other'] },
      { key: 'detail', label: 'Flight / Train no.', type: 'text' },
      { key: 'datetime', label: 'Date & time', type: 'datetime' },
      { key: 'location', label: 'Airport / Station', type: 'text' },
      { key: 'pickup_needed', label: 'Pickup needed', type: 'checkbox' },
      { key: 'coordinator', label: 'Coordinator', type: 'text' },
      { key: 'status', label: 'Status', type: 'select', options: ['Pending', 'Arranged', 'Done'] },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  tasks: {
    label: 'To-do',
    singular: 'Task',
    icon: '✅',
    order: 4,
    help: 'Master checklist. Assign an owner and a due date.',
    columns: [
      { key: 'title', label: 'Task', type: 'text', required: true },
      { key: 'category', label: 'Category', type: 'select', options: ['Venue', 'Catering', 'Decor', 'Attire', 'Invitations', 'Photography', 'Music', 'Rituals', 'Logistics', 'Guests', 'Other'] },
      { key: 'owner', label: 'Owner', type: 'text' },
      { key: 'due_date', label: 'Due', type: 'date' },
      { key: 'priority', label: 'Priority', type: 'select', options: ['Low', 'Medium', 'High'] },
      { key: 'status', label: 'Status', type: 'select', options: ['To do', 'In progress', 'Done'] },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  run_of_show: {
    label: 'Run of show',
    singular: 'Schedule item',
    icon: '⏱️',
    order: 11,
    help: 'Minute-by-minute flow for each function.',
    columns: [
      { key: 'function_id', label: 'Function', type: 'ref', ref: 'functions', required: true },
      { key: 'time', label: 'Time', type: 'time' },
      { key: 'activity', label: 'Activity', type: 'text', required: true },
      { key: 'owner', label: 'Owner / Lead', type: 'text' },
      { key: 'duration', label: 'Duration', type: 'text' },
      { key: 'sequence', label: 'Order', type: 'number' },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  dance_performances: {
    label: 'Dance / Performances',
    singular: 'Performance',
    icon: '💃',
    order: 12,
    help: 'Sangeet performances in running order, with rehearsal tracking.',
    columns: [
      { key: 'title', label: 'Performance', type: 'text', required: true },
      { key: 'function_id', label: 'Function', type: 'ref', ref: 'functions' },
      { key: 'performers', label: 'Performers', type: 'textarea' },
      { key: 'song', label: 'Song(s)', type: 'text' },
      { key: 'sequence', label: 'Order', type: 'number' },
      { key: 'duration', label: 'Duration', type: 'text' },
      { key: 'rehearsal_date', label: 'Rehearsal', type: 'date' },
      { key: 'status', label: 'Status', type: 'select', options: ['Idea', 'Rehearsing', 'Ready', 'Performed'] },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  outfits: {
    label: 'Dress code / Outfits',
    singular: 'Outfit',
    icon: '👗',
    order: 7,
    help: 'Who wears what, per function, so photos coordinate.',
    columns: [
      { key: 'person', label: 'Person', type: 'text', required: true },
      { key: 'function_id', label: 'Function', type: 'ref', ref: 'functions' },
      { key: 'outfit', label: 'Outfit', type: 'text' },
      { key: 'color', label: 'Colour', type: 'text' },
      { key: 'accessories', label: 'Accessories / Jewellery', type: 'textarea' },
      { key: 'status', label: 'Status', type: 'select', options: ['To buy', 'Ordered', 'Ready', 'Altered'] },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  gifts_give: {
    label: 'Gifts to give',
    singular: 'Gift',
    icon: '🎁',
    order: 13,
    help: 'Return gifts, favours and gifts for family.',
    columns: [
      { key: 'occasion', label: 'Occasion / For', type: 'text' },
      { key: 'recipient', label: 'Recipient', type: 'text' },
      { key: 'item', label: 'Item', type: 'text', required: true },
      { key: 'quantity', label: 'Qty', type: 'number' },
      { key: 'cost', label: 'Cost ₹', type: 'money' },
      { key: 'status', label: 'Status', type: 'select', options: ['Idea', 'To buy', 'Ordered', 'Received', 'Given'] },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },

  gifts_received: {
    label: 'Gifts received',
    singular: 'Gift received',
    icon: '🧧',
    order: 14,
    help: 'Shagun / gifts received - track for thank-you notes.',
    columns: [
      { key: 'from_name', label: 'From', type: 'text', required: true },
      { key: 'guest_id', label: 'Guest', type: 'ref', ref: 'guests' },
      { key: 'item', label: 'Gift / Item', type: 'text' },
      { key: 'amount', label: 'Cash ₹', type: 'money' },
      { key: 'function_id', label: 'At function', type: 'ref', ref: 'functions' },
      { key: 'date_received', label: 'Date', type: 'date' },
      { key: 'thank_you_sent', label: 'Thank-you sent', type: 'checkbox' },
      { key: 'notes', label: 'Notes', type: 'textarea' },
    ],
  },
};

function num(v) {
  const n = parseFloat(v);
  return isNaN(n) ? 0 : n;
}

// ---------------------------------------------------------------------------
// Table creation is generated from SCHEMA so it never drifts from the app.
// ---------------------------------------------------------------------------
function sqlType(t) {
  if (t === 'number' || t === 'money') return 'REAL';
  if (t === 'checkbox') return 'INTEGER';
  return 'TEXT';
}

function initializeDatabase() {
  for (const [table, def] of Object.entries(SCHEMA)) {
    const cols = def.columns
      .map(c => `${c.key} ${sqlType(c.type)}`)
      .join(',\n      ');
    db.run(`
      CREATE TABLE IF NOT EXISTS ${table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ${cols},
        created_at TEXT
      )
    `);
    // Additive migration: add any column that doesn't exist yet.
    for (const c of def.columns) {
      try { db.run(`ALTER TABLE ${table} ADD COLUMN ${c.key} ${sqlType(c.type)}`); } catch (e) { /* exists */ }
    }
  }

  // Guests need a unique invite token for their personalised link.
  try { db.run(`ALTER TABLE guests ADD COLUMN invite_token TEXT`); } catch (e) { /* exists */ }
  try { db.run(`ALTER TABLE guests ADD COLUMN invites_configured INTEGER DEFAULT 0`); } catch (e) { /* exists */ }
  try { db.run(`CREATE UNIQUE INDEX IF NOT EXISTS idx_guests_token ON guests(invite_token)`); } catch (e) { /* pre-existing dup tokens */ }

  // guest_functions: per-function invite + RSVP (many-to-many).
  db.run(`
    CREATE TABLE IF NOT EXISTS guest_functions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      guest_id INTEGER NOT NULL,
      function_id INTEGER NOT NULL,
      invited INTEGER DEFAULT 1,
      rsvp TEXT DEFAULT 'Pending',
      headcount INTEGER,
      UNIQUE(guest_id, function_id)
    )
  `);

  // Free-form key/value settings (couple names, wedding date, hashtag, ...).
  db.run(`
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT
    )
  `);

  seedSettings();
  backfillInviteTokens();
  saveDb();
}

const DEFAULT_SETTINGS = {
  bride_name: 'Akansha',
  groom_name: 'Priyal',
  couple_initials: 'A & P',
  wedding_date: '2026-12-20',
  wedding_date_end: '2026-12-22',
  hashtag: '#HappilyEverAP',
  tagline: 'Two hearts, one journey',
  cover_message: 'Together with our families, we joyfully invite you to celebrate our wedding.',
  contact_name: '',
  contact_phone: '',
  rsvp_deadline: '',
  invite_message_template:
    'Dear {name}, 🌸\n\nWith great joy, {bride} & {groom} — together with their families — invite you to celebrate their wedding on {date}.\n\nHere is your personal invitation with all the details and to RSVP:\n{link}\n\nWe would be so happy to have you with us! 💕\n{hashtag}',
  our_story: '',
  travel_info: '',
  gift_note: '',
  gallery_urls: '',
  music_url: '',
};

function seedSettings() {
  for (const [k, v] of Object.entries(DEFAULT_SETTINGS)) {
    const existing = queryOne(`SELECT value FROM settings WHERE key = ?`, [k]);
    if (!existing) db.run(`INSERT INTO settings (key, value) VALUES (?, ?)`, [k, v]);
  }
}

function getSettings() {
  const rows = queryAll(`SELECT key, value FROM settings`);
  const out = {};
  rows.forEach(r => { out[r.key] = r.value; });
  return out;
}

// Only these settings are exposed on the public invite page.
const PUBLIC_SETTING_KEYS = ['bride_name', 'groom_name', 'couple_initials', 'wedding_date', 'wedding_date_end', 'hashtag', 'tagline', 'cover_message', 'rsvp_deadline', 'contact_name', 'contact_phone', 'our_story', 'travel_info', 'gift_note', 'gallery_urls', 'music_url'];
function publicSettings() {
  const s = getSettings();
  const out = {};
  PUBLIC_SETTING_KEYS.forEach(k => { out[k] = s[k] || ''; });
  return out;
}

function setSettings(obj) {
  const allowed = new Set(Object.keys(DEFAULT_SETTINGS));
  for (const [k, v] of Object.entries(obj)) {
    if (!allowed.has(k)) continue;
    db.run(
      `INSERT INTO settings (key, value) VALUES (?, ?)
       ON CONFLICT(key) DO UPDATE SET value = excluded.value`,
      [k, v == null ? '' : String(v)]
    );
  }
  saveDb();
  return getSettings();
}

function makeToken() {
  return crypto.randomBytes(16).toString('hex');
}

function makeUniqueToken() {
  let t = makeToken();
  while (queryOne(`SELECT 1 AS x FROM guests WHERE invite_token = ?`, [t])) t = makeToken();
  return t;
}

function backfillInviteTokens() {
  const rows = queryAll(`SELECT id FROM guests WHERE invite_token IS NULL OR invite_token = ''`);
  rows.forEach(r => {
    db.run(`UPDATE guests SET invite_token = ? WHERE id = ?`, [makeUniqueToken(), r.id]);
  });
}

// ---------------------------------------------------------------------------
// Low-level query helpers
// ---------------------------------------------------------------------------
function queryAll(sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const out = [];
  while (stmt.step()) out.push(stmt.getAsObject());
  stmt.free();
  return out;
}

function queryOne(sql, params = []) {
  const r = queryAll(sql, params);
  return r.length ? r[0] : null;
}

function lastId() {
  const r = queryOne(`SELECT last_insert_rowid() AS id`);
  return r ? r.id : null;
}

// ---------------------------------------------------------------------------
// Generic CRUD used by every resource
// ---------------------------------------------------------------------------
function validCols(table) {
  return SCHEMA[table].columns.map(c => c.key);
}

function withComputed(table, row) {
  const def = SCHEMA[table];
  if (!def || !def.computed || !row) return row;
  def.computed.forEach(c => { row[c.key] = c.formula(row); });
  return row;
}

function list(table) {
  const def = SCHEMA[table];
  const orderBy = def.columns.find(c => c.key === 'sequence') ? 'sequence ASC, id ASC'
    : def.columns.find(c => c.key === 'event_date') ? 'event_date ASC, id ASC'
    : 'id DESC';
  const rows = queryAll(`SELECT * FROM ${table} ORDER BY ${orderBy}`);
  return rows.map(r => withComputed(table, r));
}

function getOne(table, id) {
  return withComputed(table, queryOne(`SELECT * FROM ${table} WHERE id = ?`, [id]));
}

function coerce(col, value) {
  if (value === undefined || value === null || value === '') return null;
  if (col.type === 'checkbox') return value ? 1 : 0;
  if (col.type === 'number' || col.type === 'money') return num(value);
  return value;
}

function create(table, body) {
  const cols = SCHEMA[table].columns;
  const missing = cols.find(c => c.required && (body[c.key] === undefined || body[c.key] === null || String(body[c.key]).trim() === ''));
  if (missing) { const e = new Error(`${missing.label} is required`); e.status = 400; throw e; }
  const keys = [];
  const vals = [];
  cols.forEach(c => {
    if (c.key in body) { keys.push(c.key); vals.push(coerce(c, body[c.key])); }
  });
  keys.push('created_at'); vals.push(new Date().toISOString());
  const placeholders = keys.map(() => '?').join(', ');
  db.run(`INSERT INTO ${table} (${keys.join(', ')}) VALUES (${placeholders})`, vals);
  const id = lastId();
  if (table === 'guests') db.run(`UPDATE guests SET invite_token = ? WHERE id = ?`, [makeUniqueToken(), id]);
  saveDb();
  return getOne(table, id);
}

function update(table, id, body) {
  const cols = SCHEMA[table].columns;
  const sets = [];
  const vals = [];
  cols.forEach(c => {
    if (c.key in body) { sets.push(`${c.key} = ?`); vals.push(coerce(c, body[c.key])); }
  });
  if (!sets.length) return getOne(table, id);
  vals.push(id);
  db.run(`UPDATE ${table} SET ${sets.join(', ')} WHERE id = ?`, vals);
  saveDb();
  return getOne(table, id);
}

function remove(table, id) {
  db.run(`DELETE FROM ${table} WHERE id = ?`, [id]);
  // Clean up references so nothing dangles.
  if (table === 'guests') {
    db.run(`DELETE FROM guest_functions WHERE guest_id = ?`, [id]);
    db.run(`DELETE FROM room_allocations WHERE guest_id = ?`, [id]);
    db.run(`DELETE FROM travel WHERE guest_id = ?`, [id]);
    db.run(`UPDATE gifts_received SET guest_id = NULL WHERE guest_id = ?`, [id]);
  }
  if (table === 'functions') {
    db.run(`DELETE FROM guest_functions WHERE function_id = ?`, [id]);
    db.run(`UPDATE run_of_show SET function_id = NULL WHERE function_id = ?`, [id]);
    db.run(`UPDATE dance_performances SET function_id = NULL WHERE function_id = ?`, [id]);
    db.run(`UPDATE outfits SET function_id = NULL WHERE function_id = ?`, [id]);
    db.run(`UPDATE gifts_received SET function_id = NULL WHERE function_id = ?`, [id]);
  }
  if (table === 'vendors') db.run(`UPDATE budget_items SET vendor_id = NULL WHERE vendor_id = ?`, [id]);
  if (table === 'rooms') db.run(`UPDATE room_allocations SET room_id = NULL WHERE room_id = ?`, [id]);
  saveDb();
  return { deleted: true };
}

// ---------------------------------------------------------------------------
// Guest <-> function invitations & RSVP
// ---------------------------------------------------------------------------
function getGuestFunctions(guestId) {
  return queryAll(`SELECT * FROM guest_functions WHERE guest_id = ?`, [guestId]);
}

function setGuestFunctions(guestId, functionIds) {
  if (!functionIds.length) {
    // Empty set = invited to nothing. (NOT IN (NULL) would delete nothing, so special-case it.)
    db.run(`DELETE FROM guest_functions WHERE guest_id = ?`, [guestId]);
  } else {
    db.run(`DELETE FROM guest_functions WHERE guest_id = ? AND function_id NOT IN (${functionIds.map(() => '?').join(',')})`,
      [guestId, ...functionIds]);
    functionIds.forEach(fid => {
      const existing = queryOne(`SELECT id FROM guest_functions WHERE guest_id = ? AND function_id = ?`, [guestId, fid]);
      if (!existing) db.run(`INSERT INTO guest_functions (guest_id, function_id, invited, rsvp) VALUES (?, ?, 1, 'Pending')`, [guestId, fid]);
    });
  }
  // Mark that invites were explicitly configured (so getInviteData won't fall back to "invited to all").
  db.run(`UPDATE guests SET invites_configured = 1 WHERE id = ?`, [guestId]);
  saveDb();
  return getGuestFunctions(guestId);
}

function setFunctionRsvp(guestId, functionId, rsvp, headcount) {
  const existing = queryOne(`SELECT id FROM guest_functions WHERE guest_id = ? AND function_id = ?`, [guestId, functionId]);
  if (existing) {
    db.run(`UPDATE guest_functions SET rsvp = ?, headcount = ? WHERE id = ?`, [rsvp, headcount ?? null, existing.id]);
  } else {
    db.run(`INSERT INTO guest_functions (guest_id, function_id, invited, rsvp, headcount) VALUES (?, ?, 1, ?, ?)`, [guestId, functionId, rsvp, headcount ?? null]);
  }
  saveDb();
}

// ---------------------------------------------------------------------------
// Invite site data (public, by token)
// ---------------------------------------------------------------------------
function getGuestByToken(token) {
  return queryOne(`SELECT * FROM guests WHERE invite_token = ?`, [token]);
}

function getInviteData(token) {
  const guest = getGuestByToken(token);
  if (!guest) return null;
  const allFunctions = list('functions');
  const invitedRows = getGuestFunctions(guest.id);
  const invitedMap = {};
  invitedRows.forEach(r => { invitedMap[r.function_id] = r; });

  // "Not configured yet" => invited to all (convenience). An explicit empty set => invited to none.
  const hasExplicit = guest.invites_configured ? true : invitedRows.some(r => r.invited);
  const functions = allFunctions.map(f => {
    const gf = invitedMap[f.id];
    const invited = hasExplicit ? !!(gf && gf.invited) : true;
    return { ...f, invited, rsvp: gf ? gf.rsvp : 'Pending', headcount: gf ? gf.headcount : null };
  });

  return {
    guest: {
      id: guest.id, name: guest.name, rsvp_status: guest.rsvp_status,
      headcount: guest.headcount, meal_preference: guest.meal_preference,
    },
    functions,
    settings: publicSettings(),
  };
}

function submitRsvp(token, payload) {
  const guest = getGuestByToken(token);
  if (!guest) return null;
  // Overall guest RSVP + meal + headcount
  const overall = payload.attending === 'no' ? 'No' : (payload.attending === 'maybe' ? 'Maybe' : 'Yes');
  db.run(
    `UPDATE guests SET rsvp_status = ?, headcount = ?, meal_preference = COALESCE(?, meal_preference), rsvp_message = COALESCE(?, rsvp_message) WHERE id = ?`,
    [overall, payload.headcount ?? guest.headcount ?? null, payload.meal_preference || null,
     payload.message ? String(payload.message) : null, guest.id]
  );
  // Per-function RSVP
  if (Array.isArray(payload.functions)) {
    payload.functions.forEach(f => {
      setFunctionRsvp(guest.id, f.function_id, f.rsvp || overall, f.headcount ?? payload.headcount ?? null);
    });
  }
  saveDb();
  return getInviteData(token);
}

// ---------------------------------------------------------------------------
// Dashboard stats
// ---------------------------------------------------------------------------
function dashboard() {
  const s = getSettings();
  const guests = list('guests');
  const totalHeadcount = guests.reduce((a, g) => a + (g.rsvp_status === 'Yes' ? num(g.headcount || 1) : 0), 0);
  const rsvpYes = guests.filter(g => g.rsvp_status === 'Yes').length;
  const rsvpNo = guests.filter(g => g.rsvp_status === 'No').length;
  const rsvpPending = guests.filter(g => !g.rsvp_status || g.rsvp_status === 'Pending').length;

  const budget = list('budget_items');
  const estimated = budget.reduce((a, b) => a + num(b.estimated), 0);
  const actual = budget.reduce((a, b) => a + num(b.actual || b.estimated), 0);
  const paid = budget.reduce((a, b) => a + num(b.paid), 0);

  const vendors = list('vendors');
  const vendorBalance = vendors.reduce((a, v) => a + (num(v.contract_amount) - num(v.advance_paid)), 0);

  const tasks = list('tasks');
  const tasksDone = tasks.filter(t => t.status === 'Done').length;
  const tasksOpen = tasks.length - tasksDone;

  return {
    settings: s,
    counts: {
      guests: guests.length,
      functions: list('functions').length,
      vendors: vendors.length,
      rooms: list('rooms').length,
      performances: list('dance_performances').length,
    },
    rsvp: { yes: rsvpYes, no: rsvpNo, pending: rsvpPending, headcount: totalHeadcount },
    budget: { estimated, actual, paid, balance: actual - paid },
    vendors: { count: vendors.length, balance: vendorBalance },
    tasks: { total: tasks.length, done: tasksDone, open: tasksOpen },
  };
}

module.exports = {
  getDb, saveDb, SCHEMA,
  list, getOne, create, update, remove,
  getSettings, setSettings,
  getGuestFunctions, setGuestFunctions, setFunctionRsvp,
  getInviteData, submitRsvp, getGuestByToken,
  dashboard, queryAll, queryOne,
};
