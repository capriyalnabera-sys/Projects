const express = require('express');
const cors = require('cors');
const path = require('path');
const cron = require('node-cron');
const { getDb, markOldInvestorsAsNotNew } = require('./database');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

async function start() {
  // Initialize database first
  await getDb();

  // API routes (loaded after DB init)
  const apiRoutes = require('./routes/api');
  app.use('/api', apiRoutes);

  // SPA fallback
  app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
  });

  // Schedule daily scraping at 6:00 AM
  cron.schedule('0 6 * * *', async () => {
    console.log('[Scheduler] Starting daily scrape...');

    // Mark yesterday's investors as not new
    markOldInvestorsAsNotNew();

    // Run inc42 scraper
    try {
      const Inc42Scraper = require('./scrapers/inc42Scraper');
      const scraper = new Inc42Scraper();
      const result = await scraper.run(3);
      console.log(`[Scheduler] Daily scrape completed: ${JSON.stringify(result)}`);
    } catch (err) {
      console.error(`[Scheduler] Daily scrape failed: ${err.message}`);
    }
  });

  app.listen(PORT, () => {
    console.log(`\n  Investor Tracker running at http://localhost:${PORT}\n`);
    console.log('  Daily scrape scheduled at 6:00 AM');
    console.log('  Manual scrape: POST /api/scrape\n');
  });
}

start().catch(err => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
