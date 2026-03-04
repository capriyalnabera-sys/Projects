const initSqlJs = require('sql.js');
const fs = require('fs');
const path = require('path');

const DB_PATH = path.join(__dirname, 'investor_database.db');

let db = null;
let SQL = null;

async function getDb() {
  if (db) return db;

  SQL = await initSqlJs();

  // Load existing database or create new one
  if (fs.existsSync(DB_PATH)) {
    const buffer = fs.readFileSync(DB_PATH);
    db = new SQL.Database(buffer);
  } else {
    db = new SQL.Database();
  }

  initializeDatabase();
  return db;
}

function saveDb() {
  if (db) {
    const data = db.export();
    const buffer = Buffer.from(data);
    fs.writeFileSync(DB_PATH, buffer);
  }
}

function initializeDatabase() {
  db.run(`
    CREATE TABLE IF NOT EXISTS investors (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      institution TEXT,
      title TEXT,
      avg_cheque_size TEXT,
      geographies TEXT,
      sectors TEXT,
      stage TEXT,
      shareholding TEXT,
      email TEXT,
      website TEXT,
      source TEXT,
      source_url TEXT,
      date_added TEXT NOT NULL,
      last_updated TEXT NOT NULL,
      is_new INTEGER DEFAULT 1,
      notes TEXT
    )
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS scrape_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      status TEXT DEFAULT 'running',
      records_found INTEGER DEFAULT 0,
      new_records INTEGER DEFAULT 0,
      error_message TEXT
    )
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS funding_rounds (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      startup_name TEXT,
      amount TEXT,
      round_type TEXT,
      investors TEXT,
      sector TEXT,
      date_reported TEXT,
      source TEXT,
      source_url TEXT,
      date_added TEXT NOT NULL
    )
  `);

  // Create indexes (IF NOT EXISTS not supported for indexes in all versions, so try/catch)
  const indexes = [
    `CREATE INDEX IF NOT EXISTS idx_investors_name ON investors(name)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_institution ON investors(institution)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_sectors ON investors(sectors)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_stage ON investors(stage)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_geographies ON investors(geographies)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_date_added ON investors(date_added)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_is_new ON investors(is_new)`
  ];

  indexes.forEach(sql => {
    try { db.run(sql); } catch (e) { /* index may already exist */ }
  });

  saveDb();
}

// Helper to run a query and get results as array of objects
function queryAll(sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const results = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject());
  }
  stmt.free();
  return results;
}

// Helper to run a query and get first result as object
function queryOne(sql, params = []) {
  const results = queryAll(sql, params);
  return results.length > 0 ? results[0] : null;
}

// Helper to run a modification query
function runSql(sql, params = []) {
  db.run(sql, params);
  saveDb();
}

// Mark all investors older than today as not new
function markOldInvestorsAsNotNew() {
  const today = new Date().toISOString().split('T')[0];
  runSql(`UPDATE investors SET is_new = 0 WHERE date_added < ?`, [today]);
}

function mergeCommaSeparated(existing, incoming) {
  if (!existing && !incoming) return null;
  const existingSet = new Set(
    (existing || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean)
  );
  const incomingItems = (incoming || '').split(',').map(s => s.trim()).filter(Boolean);
  incomingItems.forEach(item => existingSet.add(item.toLowerCase()));
  return [...existingSet].join(', ') || null;
}

// Insert or update an investor
function upsertInvestor(investor) {
  const today = new Date().toISOString().split('T')[0];
  const now = new Date().toISOString();

  const existing = queryOne(
    `SELECT id, sectors, geographies, stage FROM investors WHERE LOWER(name) = LOWER(?) AND LOWER(COALESCE(institution,'')) = LOWER(COALESCE(?,''))`,
    [investor.name, investor.institution || '']
  );

  if (existing) {
    const mergedSectors = mergeCommaSeparated(existing.sectors, investor.sectors);
    const mergedGeo = mergeCommaSeparated(existing.geographies, investor.geographies);
    const mergedStage = mergeCommaSeparated(existing.stage, investor.stage);

    runSql(`
      UPDATE investors SET
        title = COALESCE(?, title),
        avg_cheque_size = COALESCE(?, avg_cheque_size),
        geographies = ?,
        sectors = ?,
        stage = ?,
        shareholding = COALESCE(?, shareholding),
        email = COALESCE(?, email),
        website = COALESCE(?, website),
        source = COALESCE(?, source),
        source_url = COALESCE(?, source_url),
        last_updated = ?,
        notes = COALESCE(?, notes)
      WHERE id = ?
    `, [
      investor.title || null,
      investor.avg_cheque_size || null,
      mergedGeo,
      mergedSectors,
      mergedStage,
      investor.shareholding || null,
      investor.email || null,
      investor.website || null,
      investor.source || null,
      investor.source_url || null,
      now,
      investor.notes || null,
      existing.id
    ]);
    return { action: 'updated', id: existing.id };
  } else {
    runSql(`
      INSERT INTO investors (name, institution, title, avg_cheque_size, geographies, sectors, stage, shareholding, email, website, source, source_url, date_added, last_updated, is_new, notes)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    `, [
      investor.name,
      investor.institution || null,
      investor.title || null,
      investor.avg_cheque_size || null,
      investor.geographies || null,
      investor.sectors || null,
      investor.stage || null,
      investor.shareholding || null,
      investor.email || null,
      investor.website || null,
      investor.source || null,
      investor.source_url || null,
      today,
      now,
      investor.notes || null
    ]);

    // Get the last inserted id
    const lastId = queryOne(`SELECT last_insert_rowid() as id`);
    return { action: 'inserted', id: lastId ? lastId.id : null };
  }
}

// Search and filter investors
function searchInvestors({ query, sector, stage, geography, isNew, page = 1, limit = 50, sortBy = 'date_added', sortOrder = 'DESC' }) {
  let where = [];
  let params = [];

  if (query) {
    where.push(`(name LIKE ? OR institution LIKE ? OR sectors LIKE ? OR notes LIKE ?)`);
    const q = `%${query}%`;
    params.push(q, q, q, q);
  }
  if (sector) {
    where.push(`sectors LIKE ?`);
    params.push(`%${sector}%`);
  }
  if (stage) {
    where.push(`stage LIKE ?`);
    params.push(`%${stage}%`);
  }
  if (geography) {
    where.push(`geographies LIKE ?`);
    params.push(`%${geography}%`);
  }
  if (isNew !== undefined && isNew !== null) {
    where.push(`is_new = ?`);
    params.push(isNew ? 1 : 0);
  }

  const whereClause = where.length > 0 ? `WHERE ${where.join(' AND ')}` : '';

  const allowedSortColumns = ['name', 'institution', 'date_added', 'last_updated', 'stage', 'sectors'];
  const sortCol = allowedSortColumns.includes(sortBy) ? sortBy : 'date_added';
  const order = sortOrder === 'ASC' ? 'ASC' : 'DESC';

  const offset = (page - 1) * limit;

  const totalRow = queryOne(`SELECT COUNT(*) as total FROM investors ${whereClause}`, params);
  const total = totalRow ? totalRow.total : 0;

  const investors = queryAll(
    `SELECT * FROM investors ${whereClause} ORDER BY ${sortCol} ${order} LIMIT ? OFFSET ?`,
    [...params, limit, offset]
  );

  return { investors, total, page, limit, totalPages: Math.ceil(total / limit) };
}

// Get distinct values for filter dropdowns
function getFilterOptions() {
  const allSectors = queryAll(`SELECT DISTINCT sectors FROM investors WHERE sectors IS NOT NULL`);
  const allStages = queryAll(`SELECT DISTINCT stage FROM investors WHERE stage IS NOT NULL`);
  const allGeographies = queryAll(`SELECT DISTINCT geographies FROM investors WHERE geographies IS NOT NULL`);

  const sectors = flattenDistinct(allSectors.map(r => r.sectors));
  const stages = flattenDistinct(allStages.map(r => r.stage));
  const geographies = flattenDistinct(allGeographies.map(r => r.geographies));

  return { sectors, stages, geographies };
}

function flattenDistinct(values) {
  const set = new Set();
  values.forEach(v => {
    if (v) {
      v.split(',').map(s => s.trim()).filter(Boolean).forEach(item => set.add(item));
    }
  });
  return [...set].sort();
}

// Get dashboard stats
function getStats() {
  const totalRow = queryOne(`SELECT COUNT(*) as count FROM investors`);
  const total = totalRow ? totalRow.count : 0;

  const today = new Date().toISOString().split('T')[0];
  const newTodayRow = queryOne(`SELECT COUNT(*) as count FROM investors WHERE date_added = ?`, [today]);
  const newToday = newTodayRow ? newTodayRow.count : 0;

  const totalNewRow = queryOne(`SELECT COUNT(*) as count FROM investors WHERE is_new = 1`);
  const totalNew = totalNewRow ? totalNewRow.count : 0;

  const lastScrape = queryOne(`SELECT * FROM scrape_logs ORDER BY started_at DESC LIMIT 1`);
  const sources = queryAll(`SELECT source, COUNT(*) as count FROM investors GROUP BY source`);

  return { total, newToday, totalNew, lastScrape, sources };
}

// Log a scrape run
function logScrape(source) {
  runSql(`INSERT INTO scrape_logs (source, started_at) VALUES (?, ?)`, [source, new Date().toISOString()]);
  const row = queryOne(`SELECT last_insert_rowid() as id`);
  return row ? row.id : null;
}

function updateScrapeLog(id, { status, records_found, new_records, error_message }) {
  runSql(`
    UPDATE scrape_logs SET finished_at = ?, status = ?, records_found = ?, new_records = ?, error_message = ?
    WHERE id = ?
  `, [new Date().toISOString(), status, records_found || 0, new_records || 0, error_message || null, id]);
}

// Delete an investor
function deleteInvestor(id) {
  const existing = queryOne(`SELECT id FROM investors WHERE id = ?`, [id]);
  runSql(`DELETE FROM investors WHERE id = ?`, [id]);
  return { changes: existing ? 1 : 0 };
}

// Get a single investor
function getInvestor(id) {
  return queryOne(`SELECT * FROM investors WHERE id = ?`, [id]);
}

// Log a funding round
function insertFundingRound(round) {
  runSql(`
    INSERT INTO funding_rounds (startup_name, amount, round_type, investors, sector, date_reported, source, source_url, date_added)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `, [
    round.startup_name, round.amount, round.round_type,
    round.investors, round.sector, round.date_reported,
    round.source, round.source_url, new Date().toISOString().split('T')[0]
  ]);
}

// Export all investors as JSON
function exportAll() {
  return queryAll(`SELECT * FROM investors ORDER BY date_added DESC`);
}

// Direct DB access for custom queries in routes
function getDbInstance() {
  return db;
}

module.exports = {
  getDb,
  upsertInvestor,
  searchInvestors,
  getFilterOptions,
  getStats,
  logScrape,
  updateScrapeLog,
  deleteInvestor,
  getInvestor,
  markOldInvestorsAsNotNew,
  insertFundingRound,
  exportAll,
  getDbInstance,
  queryAll,
  queryOne,
  runSql,
  saveDb
};
