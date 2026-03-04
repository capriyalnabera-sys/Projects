const initSqlJs = require('sql.js');
const fs = require('fs');
const path = require('path');

const DB_PATH = path.join(__dirname, 'investor_database.db');

let db = null;
let SQL = null;

async function getDb() {
  if (db) return db;

  SQL = await initSqlJs();

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

  db.run(`
    CREATE TABLE IF NOT EXISTS funding_news (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      headline TEXT NOT NULL,
      summary TEXT,
      startup_name TEXT,
      amount TEXT,
      round_type TEXT,
      investors TEXT,
      sector TEXT,
      source TEXT,
      source_url TEXT,
      published_date TEXT,
      date_added TEXT NOT NULL
    )
  `);

  const indexes = [
    `CREATE INDEX IF NOT EXISTS idx_investors_name ON investors(name)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_institution ON investors(institution)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_sectors ON investors(sectors)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_stage ON investors(stage)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_geographies ON investors(geographies)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_date_added ON investors(date_added)`,
    `CREATE INDEX IF NOT EXISTS idx_investors_is_new ON investors(is_new)`,
    `CREATE INDEX IF NOT EXISTS idx_funding_news_date ON funding_news(date_added)`,
    `CREATE INDEX IF NOT EXISTS idx_funding_news_source ON funding_news(source)`
  ];

  indexes.forEach(sql => {
    try { db.run(sql); } catch (e) { /* index may already exist */ }
  });

  saveDb();
}

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

function queryOne(sql, params = []) {
  const results = queryAll(sql, params);
  return results.length > 0 ? results[0] : null;
}

function runSql(sql, params = []) {
  db.run(sql, params);
  saveDb();
}

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
    const lastId = queryOne(`SELECT last_insert_rowid() as id`);
    return { action: 'inserted', id: lastId ? lastId.id : null };
  }
}

function searchInvestors({ query, sector, stage, geography, source, isNew, page = 1, limit = 50, sortBy = 'date_added', sortOrder = 'DESC' }) {
  let where = [];
  let params = [];

  if (query) {
    where.push(`(name LIKE ? OR institution LIKE ? OR sectors LIKE ? OR notes LIKE ?)`);
    const q = `%${query}%`;
    params.push(q, q, q, q);
  }
  if (sector) { where.push(`sectors LIKE ?`); params.push(`%${sector}%`); }
  if (stage) { where.push(`stage LIKE ?`); params.push(`%${stage}%`); }
  if (geography) { where.push(`geographies LIKE ?`); params.push(`%${geography}%`); }
  if (source) { where.push(`source = ?`); params.push(source); }
  if (isNew !== undefined && isNew !== null) { where.push(`is_new = ?`); params.push(isNew ? 1 : 0); }

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

function getFilterOptions() {
  const allSectors = queryAll(`SELECT DISTINCT sectors FROM investors WHERE sectors IS NOT NULL`);
  const allStages = queryAll(`SELECT DISTINCT stage FROM investors WHERE stage IS NOT NULL`);
  const allGeographies = queryAll(`SELECT DISTINCT geographies FROM investors WHERE geographies IS NOT NULL`);
  const allSources = queryAll(`SELECT DISTINCT source FROM investors WHERE source IS NOT NULL`);

  return {
    sectors: flattenDistinct(allSectors.map(r => r.sectors)),
    stages: flattenDistinct(allStages.map(r => r.stage)),
    geographies: flattenDistinct(allGeographies.map(r => r.geographies)),
    sources: allSources.map(r => r.source).filter(Boolean).sort()
  };
}

function flattenDistinct(values) {
  const set = new Set();
  values.forEach(v => {
    if (v) v.split(',').map(s => s.trim()).filter(Boolean).forEach(item => set.add(item));
  });
  return [...set].sort();
}

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
  const newsCountRow = queryOne(`SELECT COUNT(*) as count FROM funding_news`);
  const newsCount = newsCountRow ? newsCountRow.count : 0;
  const roundsCountRow = queryOne(`SELECT COUNT(*) as count FROM funding_rounds`);
  const roundsCount = roundsCountRow ? roundsCountRow.count : 0;

  return { total, newToday, totalNew, lastScrape, sources, newsCount, roundsCount };
}

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

function deleteInvestor(id) {
  const existing = queryOne(`SELECT id FROM investors WHERE id = ?`, [id]);
  runSql(`DELETE FROM investors WHERE id = ?`, [id]);
  return { changes: existing ? 1 : 0 };
}

function getInvestor(id) {
  return queryOne(`SELECT * FROM investors WHERE id = ?`, [id]);
}

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

function insertFundingNews(news) {
  // Check for duplicate by headline + source
  const existing = queryOne(
    `SELECT id FROM funding_news WHERE LOWER(headline) = LOWER(?) AND source = ?`,
    [news.headline, news.source]
  );
  if (existing) return { action: 'skipped', id: existing.id };

  runSql(`
    INSERT INTO funding_news (headline, summary, startup_name, amount, round_type, investors, sector, source, source_url, published_date, date_added)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `, [
    news.headline, news.summary || null, news.startup_name || null,
    news.amount || null, news.round_type || null, news.investors || null,
    news.sector || null, news.source, news.source_url || null,
    news.published_date || null, new Date().toISOString().split('T')[0]
  ]);
  const lastId = queryOne(`SELECT last_insert_rowid() as id`);
  return { action: 'inserted', id: lastId ? lastId.id : null };
}

function searchFundingNews({ query, source, page = 1, limit = 50 }) {
  let where = [];
  let params = [];
  if (query) {
    where.push(`(headline LIKE ? OR summary LIKE ? OR startup_name LIKE ? OR investors LIKE ?)`);
    const q = `%${query}%`;
    params.push(q, q, q, q);
  }
  if (source) { where.push(`source = ?`); params.push(source); }
  const whereClause = where.length > 0 ? `WHERE ${where.join(' AND ')}` : '';
  const offset = (page - 1) * limit;
  const totalRow = queryOne(`SELECT COUNT(*) as total FROM funding_news ${whereClause}`, params);
  const total = totalRow ? totalRow.total : 0;
  const news = queryAll(
    `SELECT * FROM funding_news ${whereClause} ORDER BY date_added DESC, id DESC LIMIT ? OFFSET ?`,
    [...params, limit, offset]
  );
  return { news, total, page, limit, totalPages: Math.ceil(total / limit) };
}

function exportAll() {
  return queryAll(`SELECT * FROM investors ORDER BY date_added DESC`);
}

function getDbInstance() { return db; }

module.exports = {
  getDb, upsertInvestor, searchInvestors, getFilterOptions, getStats,
  logScrape, updateScrapeLog, deleteInvestor, getInvestor,
  markOldInvestorsAsNotNew, insertFundingRound, insertFundingNews,
  searchFundingNews, exportAll, getDbInstance, queryAll, queryOne, runSql, saveDb
};
