const express = require('express');
const router = express.Router();
const {
  searchInvestors,
  getFilterOptions,
  getStats,
  upsertInvestor,
  deleteInvestor,
  getInvestor,
  exportAll,
  queryAll,
  queryOne,
  runSql
} = require('../database');

// GET /api/stats - Dashboard statistics
router.get('/stats', (req, res) => {
  try {
    const stats = getStats();
    res.json(stats);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/investors - Search and filter investors
router.get('/investors', (req, res) => {
  try {
    const {
      q: query,
      sector,
      stage,
      geography,
      is_new,
      page = 1,
      limit = 50,
      sort_by = 'date_added',
      sort_order = 'DESC'
    } = req.query;

    const isNew = is_new === '1' ? true : is_new === '0' ? false : undefined;

    const result = searchInvestors({
      query,
      sector,
      stage,
      geography,
      isNew,
      page: parseInt(page),
      limit: parseInt(limit),
      sortBy: sort_by,
      sortOrder: sort_order
    });

    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/investors/:id - Get single investor
router.get('/investors/:id', (req, res) => {
  try {
    const investor = getInvestor(parseInt(req.params.id));
    if (!investor) return res.status(404).json({ error: 'Investor not found' });
    res.json(investor);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /api/investors - Add or update an investor manually
router.post('/investors', (req, res) => {
  try {
    const investor = req.body;
    if (!investor.name) {
      return res.status(400).json({ error: 'Name is required' });
    }
    const result = upsertInvestor(investor);
    res.json({ success: true, ...result });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// PUT /api/investors/:id - Update an investor
router.put('/investors/:id', (req, res) => {
  try {
    const id = parseInt(req.params.id);
    const existing = getInvestor(id);
    if (!existing) return res.status(404).json({ error: 'Investor not found' });

    const fields = ['name', 'institution', 'title', 'avg_cheque_size', 'geographies',
      'sectors', 'stage', 'shareholding', 'email', 'website', 'notes'];

    const updates = [];
    const values = [];

    fields.forEach(field => {
      if (req.body[field] !== undefined) {
        updates.push(`${field} = ?`);
        values.push(req.body[field]);
      }
    });

    if (updates.length === 0) {
      return res.status(400).json({ error: 'No fields to update' });
    }

    updates.push('last_updated = ?');
    values.push(new Date().toISOString());
    values.push(id);

    runSql(`UPDATE investors SET ${updates.join(', ')} WHERE id = ?`, values);
    res.json({ success: true, id });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// DELETE /api/investors/:id - Delete an investor
router.delete('/investors/:id', (req, res) => {
  try {
    const result = deleteInvestor(parseInt(req.params.id));
    if (result.changes === 0) return res.status(404).json({ error: 'Investor not found' });
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/filters - Get filter dropdown options
router.get('/filters', (req, res) => {
  try {
    const options = getFilterOptions();
    res.json(options);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/export - Export all investors as JSON
router.get('/export', (req, res) => {
  try {
    const investors = exportAll();
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Content-Disposition', 'attachment; filename=investor_database.json');
    res.json(investors);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/export/csv - Export all investors as CSV
router.get('/export/csv', (req, res) => {
  try {
    const investors = exportAll();
    const headers = ['Name', 'Institution', 'Title', 'Avg Cheque Size', 'Geographies',
      'Sectors', 'Stage', 'Shareholding', 'Email', 'Website', 'Source', 'Date Added'];
    const fields = ['name', 'institution', 'title', 'avg_cheque_size', 'geographies',
      'sectors', 'stage', 'shareholding', 'email', 'website', 'source', 'date_added'];

    let csv = headers.join(',') + '\n';
    investors.forEach(inv => {
      const row = fields.map(f => {
        const val = (inv[f] || '').toString().replace(/"/g, '""');
        return `"${val}"`;
      });
      csv += row.join(',') + '\n';
    });

    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', 'attachment; filename=investor_database.csv');
    res.send(csv);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /api/scrape - Trigger a manual scrape
router.post('/scrape', async (req, res) => {
  try {
    const { source = 'inc42', maxPages = 2 } = req.body;

    // Respond immediately
    res.json({ success: true, message: `Scrape started for ${source}. Check logs for progress.` });

    // Run scrape in background
    if (source === 'inc42') {
      const Inc42Scraper = require('../scrapers/inc42Scraper');
      const scraper = new Inc42Scraper();
      scraper.run(maxPages).then(result => {
        console.log(`[API] Scrape completed: ${JSON.stringify(result)}`);
      }).catch(err => {
        console.error(`[API] Scrape failed: ${err.message}`);
      });
    }
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/scrape/logs - Get scrape history
router.get('/scrape/logs', (req, res) => {
  try {
    const logs = queryAll(`SELECT * FROM scrape_logs ORDER BY started_at DESC LIMIT 20`);
    res.json(logs);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /api/funding-rounds - Get funding rounds
router.get('/funding-rounds', (req, res) => {
  try {
    const { page = 1, limit = 50 } = req.query;
    const offset = (parseInt(page) - 1) * parseInt(limit);
    const totalRow = queryOne(`SELECT COUNT(*) as count FROM funding_rounds`);
    const total = totalRow ? totalRow.count : 0;
    const rounds = queryAll(
      `SELECT * FROM funding_rounds ORDER BY date_added DESC LIMIT ? OFFSET ?`,
      [parseInt(limit), offset]
    );
    res.json({ rounds, total, page: parseInt(page), limit: parseInt(limit) });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
