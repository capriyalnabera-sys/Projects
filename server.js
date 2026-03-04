const express = require('express');
const cors = require('cors');
const path = require('path');
const cron = require('node-cron');
const { getDb, markOldInvestorsAsNotNew } = require('./database');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

async function start() {
  await getDb();

  const apiRoutes = require('./routes/api');
  app.use('/api', apiRoutes);

  app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
  });

  // Daily scrape at 6 AM - all sources
  cron.schedule('0 6 * * *', async () => {
    console.log('[Scheduler] Starting daily scrape...');
    markOldInvestorsAsNotNew();

    const sources = [
      { key: 'inc42', cls: () => require('./scrapers/inc42Scraper') },
    ];

    for (const src of sources) {
      try {
        const Scraper = src.cls();
        const scraper = new Scraper();
        const result = await scraper.run(3);
        console.log(`[Scheduler] ${src.key}: ${JSON.stringify(result)}`);
      } catch (err) {
        console.error(`[Scheduler] ${src.key} failed: ${err.message}`);
      }
    }

    // Multi-source scrapers
    const { NewsScraper } = require('./scrapers/newsScraper');
    for (const site of ['yourstory', 'livemint', 'vccircle', 'entrackr']) {
      try {
        const scraper = new NewsScraper(site);
        const result = await scraper.run(2);
        console.log(`[Scheduler] ${site}: ${JSON.stringify(result)}`);
      } catch (err) {
        console.error(`[Scheduler] ${site} failed: ${err.message}`);
      }
    }

    console.log('[Scheduler] Daily scrape complete');
  });

  app.listen(PORT, () => {
    console.log(`\n  Investor Tracker running at http://localhost:${PORT}`);
    console.log('  Sources: Inc42, YourStory, LiveMint, VCCircle, Entrackr');
    console.log('  Daily scrape at 6:00 AM | Manual: POST /api/scrape\n');
  });
}

start().catch(err => { console.error('Failed to start:', err); process.exit(1); });
