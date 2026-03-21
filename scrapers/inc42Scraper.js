const puppeteer = require('puppeteer');
const { upsertInvestor, logScrape, updateScrapeLog, insertFundingRound } = require('../database');

// Regex patterns to extract funding info from article text
const AMOUNT_PATTERN = /(?:INR|Rs\.?|USD|\$|US\$|S\$|SGD)?\s*[\d.,]+\s*(?:million|mn|m|billion|bn|b|cr|crore|lakh|k|Cr|Mn|Bn)\b/gi;
const ROUND_PATTERN = /\b(seed|pre-seed|series\s*[a-f]|angel|bridge|pre-series\s*[a-f]|growth|debt|venture|ipo|late[\s-]stage|early[\s-]stage)\b/gi;
const VALUATION_PATTERN = /(?:valued?\s+at|valuation\s+(?:of|at|around|near|approximately)?)\s*(?:INR|Rs\.?|USD|\$|US\$|S\$|SGD)?\s*[\d.,]+\s*(?:million|mn|m|billion|bn|b|cr|crore|Cr|Mn|Bn)\b/gi;
const SECTOR_KEYWORDS = [
  'fintech', 'edtech', 'healthtech', 'medtech', 'agritech', 'foodtech',
  'proptech', 'insurtech', 'legaltech', 'hrtech', 'martech', 'adtech',
  'cleantech', 'greentech', 'biotech', 'deeptech', 'spacetech',
  'saas', 'b2b', 'b2c', 'd2c', 'e-commerce', 'ecommerce',
  'logistics', 'mobility', 'ev', 'electric vehicle',
  'ai', 'artificial intelligence', 'machine learning', 'ml',
  'blockchain', 'crypto', 'web3', 'defi', 'nft',
  'gaming', 'social media', 'media', 'entertainment',
  'healthcare', 'pharma', 'wellness', 'fitness',
  'education', 'skill development',
  'real estate', 'construction',
  'agriculture', 'farming',
  'food', 'restaurant', 'cloud kitchen',
  'travel', 'hospitality', 'tourism',
  'fashion', 'beauty', 'lifestyle',
  'energy', 'solar', 'renewable',
  'manufacturing', 'industrial',
  'cybersecurity', 'security',
  'iot', 'robotics', 'automation', 'drone',
  'supply chain', 'procurement',
  'insurance', 'lending', 'payments', 'banking', 'neobank',
  'climate', 'sustainability', 'waste management',
  'content', 'creator economy', 'streaming'
];

const INVESTOR_TYPE_KEYWORDS = {
  'angel investor': 'Angel Investor',
  'angel': 'Angel Investor',
  'venture capital': 'Venture Capital',
  'vc fund': 'Venture Capital',
  'vc firm': 'Venture Capital',
  'family office': 'Family Office',
  'private equity': 'Private Equity',
  'pe firm': 'Private Equity',
  'hedge fund': 'Hedge Fund',
  'accelerator': 'Accelerator',
  'incubator': 'Incubator',
  'micro vc': 'Micro VC',
  'corporate venture': 'Corporate VC',
  'sovereign wealth': 'Sovereign Wealth Fund',
  'fund of funds': 'Fund of Funds'
};

class Inc42Scraper {
  constructor() {
    this.browser = null;
    this.baseUrl = 'https://inc42.com';
    this.results = [];
  }

  async launch() {
    this.browser = await puppeteer.launch({
      headless: 'new',
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--window-size=1920,1080'
      ],
      defaultViewport: { width: 1920, height: 1080 }
    });
  }

  async close() {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }
  }

  async scrapeSection(sectionUrl, sectionName, maxPages = 3) {
    const page = await this.browser.newPage();

    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    );

    // Block images, fonts, stylesheets to speed up
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const resourceType = req.resourceType();
      if (['image', 'font', 'stylesheet', 'media'].includes(resourceType)) {
        req.abort();
      } else {
        req.continue();
      }
    });

    const articleLinks = [];

    for (let pageNum = 1; pageNum <= maxPages; pageNum++) {
      const url = pageNum === 1 ? sectionUrl : `${sectionUrl}/page/${pageNum}`;
      console.log(`[Inc42] Scraping listing page: ${url}`);

      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await page.waitForSelector('article, .post-card, .category-post, a[href*="/buzz/"], a[href*="/startups/"], a[href*="/features/"]', { timeout: 10000 }).catch(() => {});

        // Extract article links from the listing page
        const links = await page.evaluate(() => {
          const anchors = document.querySelectorAll('a[href]');
          const hrefs = new Set();
          anchors.forEach(a => {
            const href = a.href;
            // Filter for article URLs - inc42 articles typically have these patterns
            if (href && (
              href.includes('/buzz/') ||
              href.includes('/startups/') ||
              href.includes('/features/') ||
              href.includes('/resources/')
            ) && !href.includes('/page/') && !href.includes('#')) {
              hrefs.add(href);
            }
          });
          return [...hrefs];
        });

        articleLinks.push(...links);
        console.log(`[Inc42] Found ${links.length} article links on page ${pageNum}`);

        // Wait between page loads
        await delay(2000 + Math.random() * 2000);
      } catch (err) {
        console.error(`[Inc42] Error on listing page ${pageNum}: ${err.message}`);
      }
    }

    await page.close();

    // Deduplicate
    const uniqueLinks = [...new Set(articleLinks)];
    console.log(`[Inc42] Total unique articles to process: ${uniqueLinks.length}`);

    // Process each article
    const fundingArticles = uniqueLinks.filter(link =>
      /fund|rais|invest|back|secur|round|seed|series|angel|valuat|startup/i.test(link)
    );

    console.log(`[Inc42] Funding-related articles: ${fundingArticles.length}`);

    // Process funding-related articles first, then others (limited)
    const toProcess = [
      ...fundingArticles,
      ...uniqueLinks.filter(l => !fundingArticles.includes(l)).slice(0, 10)
    ];

    for (const link of toProcess) {
      await this.scrapeArticle(link, sectionName);
      await delay(3000 + Math.random() * 3000); // Polite delay
    }
  }

  async scrapeArticle(url, sectionName) {
    const page = await this.browser.newPage();

    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    );

    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const resourceType = req.resourceType();
      if (['image', 'font', 'media'].includes(resourceType)) {
        req.abort();
      } else {
        req.continue();
      }
    });

    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });

      const articleData = await page.evaluate(() => {
        const title = document.querySelector('h1')?.textContent?.trim() || '';
        const bodyEl = document.querySelector('.entry-content, .post-content, article, .article-content, main');
        const body = bodyEl?.textContent?.trim() || '';
        const dateEl = document.querySelector('time, .post-date, .entry-date, [datetime]');
        const date = dateEl?.getAttribute('datetime') || dateEl?.textContent?.trim() || '';
        return { title, body, date };
      });

      if (!articleData.body) {
        await page.close();
        return;
      }

      // Determine if this is a funding article
      const text = `${articleData.title} ${articleData.body}`;
      const isFunding = /\b(fund|rais|invest|back|secur|round|seed|series|angel|venture|capital)\b/i.test(text);

      if (isFunding) {
        const extracted = this.extractInvestorInfo(text, articleData.title, url, articleData.date);
        this.results.push(...extracted);
      }

      console.log(`[Inc42] Processed: ${articleData.title.substring(0, 80)}... (${isFunding ? 'FUNDING' : 'non-funding'})`);
    } catch (err) {
      console.error(`[Inc42] Error scraping article ${url}: ${err.message}`);
    }

    await page.close();
  }

  extractInvestorInfo(text, title, sourceUrl, articleDate) {
    const investors = [];

    // Extract the funding amount
    const amounts = text.match(AMOUNT_PATTERN) || [];
    const amount = amounts[0] || null;

    // Extract the round type
    const rounds = text.match(ROUND_PATTERN) || [];
    const roundType = rounds[0] || null;

    // Determine the stage from round type
    const stage = roundType ? mapRoundToStage(roundType) : null;

    // Extract valuation
    const valuationMatches = text.match(VALUATION_PATTERN) || [];
    let valuation = null;
    let valuationMultiple = null;
    if (valuationMatches.length > 0) {
      valuation = valuationMatches[0].replace(/valued?\s+at|valuation\s+(?:of|at|around|near|approximately)?/i, '').trim();
      if (valuation && amount) {
        valuationMultiple = calcMultiple(amount, valuation);
      }
    }

    // Detect country - Inc42 is India-focused
    let country = 'India';
    if (/\b(singapore|singaporean)\b/i.test(text)) country = 'Singapore';
    else if (/\b(indonesia|indonesian|jakarta)\b/i.test(text)) country = 'Indonesia';
    else if (/\b(vietnam|vietnamese)\b/i.test(text)) country = 'Vietnam';

    // Extract sectors
    const detectedSectors = SECTOR_KEYWORDS.filter(keyword =>
      new RegExp(`\\b${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(text)
    );
    const sector = detectedSectors.slice(0, 5).join(', ') || null;

    // Try to extract investor names
    // Common patterns in inc42 articles:
    // "led by [Investor Name]"
    // "[Investor Name] participated"
    // "backed by [Investor Name]"
    // "from [Investor Name]"
    // "investors include [List]"

    const investorPatterns = [
      /(?:led by|backed by|from|funding from|investment from|participated by)\s+([A-Z][A-Za-z\s&.,]+?)(?:\s*(?:and|,|\.|along with|with participation|the round))/gi,
      /(?:investors?\s+(?:include|such as|like|including|are))\s+([A-Z][A-Za-z\s&.,]+?)(?:\s*(?:\.|participated|invested|among))/gi,
      /([A-Z][A-Za-z\s]+(?:Capital|Ventures|Partners|Fund|Investment[s]?|VC|Holdings|Group|Equity|Management|Advisors|Labs|Studio))/g,
      /(?:angel investor[s]?)\s+([A-Z][A-Za-z\s]+?)(?:\s*(?:,|and|\.|who|also|have|has))/gi,
      /([A-Z][a-z]+\s+[A-Z][a-z]+)(?:\s*,\s*(?:founder|CEO|CTO|partner|managing director|GP|angel|investor|MD|VP|head|director|co-founder))/g
    ];

    const foundNames = new Set();

    for (const pattern of investorPatterns) {
      let match;
      while ((match = pattern.exec(text)) !== null) {
        const rawNames = match[1]
          .split(/,\s*|\s+and\s+/)
          .map(n => n.trim())
          .filter(n => n.length > 2 && n.length < 80);

        rawNames.forEach(name => {
          // Clean up
          name = name.replace(/\s+/g, ' ').trim();
          // Filter out common false positives
          if (!isCommonWord(name) && /[A-Z]/.test(name)) {
            foundNames.add(name);
          }
        });
      }
    }

    // Determine geography from content
    const geoPatterns = [
      { pattern: /\b(india|indian|mumbai|delhi|bangalore|bengaluru|hyderabad|chennai|pune|kolkata|gurgaon|gurugram|noida)\b/i, geo: 'India' },
      { pattern: /\b(southeast asia|singapore|indonesia|vietnam|thailand|philippines|malaysia)\b/i, geo: 'Southeast Asia' },
      { pattern: /\b(united states|us-based|silicon valley|san francisco|new york|boston|usa)\b/i, geo: 'United States' },
      { pattern: /\b(europe|london|berlin|paris|amsterdam|uk|united kingdom)\b/i, geo: 'Europe' },
      { pattern: /\b(middle east|dubai|uae|saudi|mena)\b/i, geo: 'Middle East' },
      { pattern: /\b(china|chinese|beijing|shanghai)\b/i, geo: 'China' },
      { pattern: /\b(japan|japanese|tokyo)\b/i, geo: 'Japan' },
      { pattern: /\b(korea|korean|seoul)\b/i, geo: 'South Korea' },
      { pattern: /\b(africa|nigeria|kenya|south africa|lagos|nairobi)\b/i, geo: 'Africa' },
      { pattern: /\b(latin america|brazil|mexico|latam)\b/i, geo: 'Latin America' },
      { pattern: /\b(global|worldwide|international)\b/i, geo: 'Global' }
    ];

    const detectedGeos = geoPatterns
      .filter(gp => gp.pattern.test(text))
      .map(gp => gp.geo);
    const geography = [...new Set(detectedGeos)].join(', ') || null;

    // Create investor records
    for (const name of foundNames) {
      const isInstitution = /capital|ventures|partners|fund|investment|holdings|group|equity|management|advisors|labs|studio|vc|associates/i.test(name);

      investors.push({
        name: isInstitution ? name : name,
        institution: isInstitution ? name : null,
        title: isInstitution ? null : detectTitle(text, name),
        avg_cheque_size: amount || null,
        geographies: geography,
        sectors: sector,
        stage: stage,
        shareholding: null,
        email: null,
        website: null,
        source: 'inc42',
        source_url: sourceUrl,
        notes: `From article: "${title.substring(0, 120)}"`
      });
    }

    // Also log the funding round
    if (foundNames.size > 0 || amount) {
      // Extract startup name from title
      const startupMatch = title.match(/^([A-Z][A-Za-z0-9\s.]+?)(?:\s+(?:raises|secures|gets|bags|closes|lands|nabs|receives|grabs))/i);
      const startupName = startupMatch ? startupMatch[1].trim() : null;

      if (startupName) {
        try {
          insertFundingRound({
            startup_name: startupName,
            amount: amount,
            round_type: roundType,
            investors: [...foundNames].join(', '),
            sector: sector,
            valuation: valuation,
            valuation_multiple: valuationMultiple,
            country: country,
            date_reported: articleDate || null,
            source: 'inc42',
            source_url: sourceUrl
          });
        } catch (e) {
          // ignore duplicate errors
        }
      }
    }

    return investors;
  }

  async run(maxPages = 3) {
    const scrapeId = logScrape('inc42');
    let totalFound = 0;
    let totalNew = 0;

    try {
      await this.launch();
      console.log('[Inc42] Browser launched');

      // Scrape the "buzz" (news) section
      console.log('\n=== Scraping Inc42 News/Buzz Section ===');
      await this.scrapeSection(`${this.baseUrl}/buzz`, 'news', maxPages);

      // Scrape the "startups" section
      console.log('\n=== Scraping Inc42 Startups Section ===');
      await this.scrapeSection(`${this.baseUrl}/industry/startups`, 'startups', maxPages);

      // Save results to database
      console.log(`\n[Inc42] Saving ${this.results.length} investor records...`);

      for (const investor of this.results) {
        try {
          const result = upsertInvestor(investor);
          totalFound++;
          if (result.action === 'inserted') totalNew++;
        } catch (err) {
          console.error(`[Inc42] Error saving investor ${investor.name}: ${err.message}`);
        }
      }

      console.log(`[Inc42] Done. Total processed: ${totalFound}, New records: ${totalNew}`);

      updateScrapeLog(scrapeId, {
        status: 'completed',
        records_found: totalFound,
        new_records: totalNew
      });

    } catch (err) {
      console.error(`[Inc42] Scraper failed: ${err.message}`);
      updateScrapeLog(scrapeId, {
        status: 'failed',
        records_found: totalFound,
        new_records: totalNew,
        error_message: err.message
      });
    } finally {
      await this.close();
    }

    return { totalFound, totalNew };
  }
}

function mapRoundToStage(round) {
  const r = round.toLowerCase().replace(/\s+/g, ' ').trim();
  if (/pre-seed|pre seed/.test(r)) return 'Pre-Seed';
  if (/seed/.test(r)) return 'Seed';
  if (/angel/.test(r)) return 'Angel';
  if (/series\s*a/i.test(r)) return 'Series A';
  if (/series\s*b/i.test(r)) return 'Series B';
  if (/series\s*c/i.test(r)) return 'Series C';
  if (/series\s*[d-f]/i.test(r)) return 'Series D+';
  if (/bridge/.test(r)) return 'Bridge';
  if (/growth|late/i.test(r)) return 'Growth';
  if (/debt/.test(r)) return 'Debt';
  if (/ipo/.test(r)) return 'IPO';
  return round;
}

function detectTitle(text, personName) {
  const titlePatterns = [
    new RegExp(`${escapeRegex(personName)}\\s*,\\s*((?:co-)?(?:founder|CEO|CTO|COO|CFO|partner|managing director|general partner|principal|managing partner|angel investor|investor|MD|VP|director|president|chairman|head))`, 'i'),
    new RegExp(`((?:co-)?(?:founder|CEO|CTO|COO|CFO|partner|managing director|general partner|principal|managing partner|angel investor|investor|MD|VP|director|president|chairman|head))\\s+(?:of\\s+\\w+\\s+)?${escapeRegex(personName)}`, 'i')
  ];

  for (const pattern of titlePatterns) {
    const match = text.match(pattern);
    if (match) return match[1].trim();
  }
  return null;
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isCommonWord(name) {
  const commonWords = new Set([
    'The Company', 'The Startup', 'The Firm', 'The Fund', 'The Round',
    'The Deal', 'This Round', 'The Investment', 'New Delhi', 'San Francisco',
    'Silicon Valley', 'Inc', 'Also Read', 'Read More', 'Press Release',
    'According To', 'In Addition', 'As Per', 'Last Year', 'This Year',
    'Earlier This', 'Said In', 'The Report', 'Going Forward', 'Looking At'
  ]);
  return commonWords.has(name) || name.split(' ').length > 6 || name.length < 3;
}

function parseToNumber(str) {
  if (!str) return null;
  const cleaned = str.replace(/[^\d.,a-zA-Z\s]/g, '').trim();
  const m = cleaned.match(/([\d.,]+)\s*(million|mn|m|billion|bn|b|cr|crore|lakh|k|Cr|Mn|Bn)/i);
  if (!m) return null;
  const num = parseFloat(m[1].replace(/,/g, ''));
  const unit = m[2].toLowerCase();
  const mult = { million: 1e6, mn: 1e6, m: 1e6, billion: 1e9, bn: 1e9, b: 1e9, cr: 1.2e7, crore: 1.2e7, lakh: 1.2e5, k: 1e3 };
  return num * (mult[unit] || 1);
}

function calcMultiple(amountStr, valuationStr) {
  const a = parseToNumber(amountStr);
  const v = parseToNumber(valuationStr);
  if (!a || !v || a === 0) return null;
  return `${(v / a).toFixed(1)}x`;
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

module.exports = Inc42Scraper;
