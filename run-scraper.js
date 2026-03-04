// Standalone script to run the scraper manually
// Usage: node run-scraper.js [maxPages]

const { getDb } = require('./database');
const Inc42Scraper = require('./scrapers/inc42Scraper');

async function main() {
  const maxPages = parseInt(process.argv[2]) || 3;

  console.log('Initializing database...');
  await getDb();

  console.log(`Starting Inc42 scraper (max ${maxPages} pages per section)...\n`);
  const scraper = new Inc42Scraper();
  const result = await scraper.run(maxPages);

  console.log('\n=== Scrape Summary ===');
  console.log(`Total records processed: ${result.totalFound}`);
  console.log(`New records added: ${result.totalNew}`);
  process.exit(0);
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
