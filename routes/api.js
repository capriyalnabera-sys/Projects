const express = require('express');
const router = express.Router();
const {
  searchInvestors, getFilterOptions, getStats, upsertInvestor,
  deleteInvestor, getInvestor, exportAll, searchFundingNews,
  queryAll, queryOne, runSql
} = require('../database');

router.get('/stats', (req, res) => {
  try { res.json(getStats()); } catch (err) { res.status(500).json({ error: err.message }); }
});

router.get('/investors', (req, res) => {
  try {
    const { q: query, sector, stage, geography, source, is_new, page = 1, limit = 50, sort_by = 'date_added', sort_order = 'DESC' } = req.query;
    const isNew = is_new === '1' ? true : is_new === '0' ? false : undefined;
    res.json(searchInvestors({ query, sector, stage, geography, source, isNew, page: parseInt(page), limit: parseInt(limit), sortBy: sort_by, sortOrder: sort_order }));
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.get('/investors/:id', (req, res) => {
  try {
    const investor = getInvestor(parseInt(req.params.id));
    if (!investor) return res.status(404).json({ error: 'Investor not found' });
    res.json(investor);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.post('/investors', (req, res) => {
  try {
    if (!req.body.name) return res.status(400).json({ error: 'Name is required' });
    res.json({ success: true, ...upsertInvestor(req.body) });
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.put('/investors/:id', (req, res) => {
  try {
    const id = parseInt(req.params.id);
    if (!getInvestor(id)) return res.status(404).json({ error: 'Investor not found' });
    const fields = ['name','institution','title','avg_cheque_size','geographies','sectors','stage','shareholding','email','website','notes'];
    const updates = [], values = [];
    fields.forEach(f => { if (req.body[f] !== undefined) { updates.push(`${f} = ?`); values.push(req.body[f]); } });
    if (!updates.length) return res.status(400).json({ error: 'No fields to update' });
    updates.push('last_updated = ?'); values.push(new Date().toISOString()); values.push(id);
    runSql(`UPDATE investors SET ${updates.join(', ')} WHERE id = ?`, values);
    res.json({ success: true, id });
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.delete('/investors/:id', (req, res) => {
  try {
    const result = deleteInvestor(parseInt(req.params.id));
    if (result.changes === 0) return res.status(404).json({ error: 'Investor not found' });
    res.json({ success: true });
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.get('/filters', (req, res) => {
  try { res.json(getFilterOptions()); } catch (err) { res.status(500).json({ error: err.message }); }
});

router.get('/export', (req, res) => {
  try {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Content-Disposition', 'attachment; filename=investor_database.json');
    res.json(exportAll());
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.get('/export/csv', (req, res) => {
  try {
    const investors = exportAll();
    const headers = ['Name','Institution','Title','Avg Cheque Size','Geographies','Sectors','Stage','Shareholding','Email','Website','Source','Date Added'];
    const fields = ['name','institution','title','avg_cheque_size','geographies','sectors','stage','shareholding','email','website','source','date_added'];
    let csv = headers.join(',') + '\n';
    investors.forEach(inv => { csv += fields.map(f => `"${(inv[f]||'').toString().replace(/"/g,'""')}"`).join(',') + '\n'; });
    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', 'attachment; filename=investor_database.csv');
    res.send(csv);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// Funding news
router.get('/funding-news', (req, res) => {
  try {
    const { q: query, source, country, page = 1, limit = 50 } = req.query;
    res.json(searchFundingNews({ query, source, country, page: parseInt(page), limit: parseInt(limit) }));
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// Scrape trigger - supports all sources
router.post('/scrape', async (req, res) => {
  try {
    const { source = 'inc42', maxPages = 2 } = req.body;
    res.json({ success: true, message: `Scrape started for ${source}.` });

    if (source === 'inc42') {
      const Inc42Scraper = require('../scrapers/inc42Scraper');
      const scraper = new Inc42Scraper();
      scraper.run(maxPages).then(r => console.log(`[API] inc42 done: ${JSON.stringify(r)}`)).catch(e => console.error(`[API] inc42 failed: ${e.message}`));
    } else {
      const { NewsScraper, SITE_CONFIGS } = require('../scrapers/newsScraper');
      if (SITE_CONFIGS[source]) {
        const scraper = new NewsScraper(source);
        scraper.run(maxPages).then(r => console.log(`[API] ${source} done: ${JSON.stringify(r)}`)).catch(e => console.error(`[API] ${source} failed: ${e.message}`));
      }
    }
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// Scrape all sources at once
router.post('/scrape/all', async (req, res) => {
  try {
    const { maxPages = 2 } = req.body;
    res.json({ success: true, message: 'Scraping all sources...' });

    const sources = ['inc42', 'yourstory', 'livemint', 'vccircle', 'entrackr', 'e27', 'techinasia', 'dealstreetasia'];
    for (const src of sources) {
      try {
        if (src === 'inc42') {
          const Inc42Scraper = require('../scrapers/inc42Scraper');
          const scraper = new Inc42Scraper();
          await scraper.run(maxPages);
        } else {
          const { NewsScraper } = require('../scrapers/newsScraper');
          const scraper = new NewsScraper(src);
          await scraper.run(maxPages);
        }
      } catch (e) { console.error(`[API] ${src} error: ${e.message}`); }
    }
    console.log('[API] All scrapes finished');
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.get('/scrape/logs', (req, res) => {
  try { res.json(queryAll(`SELECT * FROM scrape_logs ORDER BY started_at DESC LIMIT 30`)); }
  catch (err) { res.status(500).json({ error: err.message }); }
});

router.get('/funding-rounds', (req, res) => {
  try {
    const { page = 1, limit = 50, country } = req.query;
    const offset = (parseInt(page) - 1) * parseInt(limit);
    let whereClause = '';
    let params = [];
    if (country) { whereClause = 'WHERE country = ?'; params.push(country); }
    const totalRow = queryOne(`SELECT COUNT(*) as count FROM funding_rounds ${whereClause}`, params);
    const rounds = queryAll(`SELECT * FROM funding_rounds ${whereClause} ORDER BY date_added DESC LIMIT ? OFFSET ?`, [...params, parseInt(limit), offset]);
    res.json({ rounds, total: totalRow ? totalRow.count : 0, page: parseInt(page), limit: parseInt(limit) });
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// Seed endpoint
router.post('/seed', async (req, res) => {
  try {
    const { seed } = require('../scrapers/seedData');
    await seed();
    res.json({ success: true, message: 'Global investor data seeded successfully.' });
  } catch (err) { res.status(500).json({ error: err.message }); }
});

module.exports = router;
