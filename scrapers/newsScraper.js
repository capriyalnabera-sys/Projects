const puppeteer = require('puppeteer');
const { upsertInvestor, logScrape, updateScrapeLog, insertFundingRound, insertFundingNews } = require('../database');

const AMOUNT_PATTERN = /(?:INR|Rs\.?|USD|\$|US\$|S\$|SGD)\s*[\d.,]+\s*(?:million|mn|m|billion|bn|b|cr|crore|lakh|k|Cr|Mn|Bn)\b/gi;
const ROUND_PATTERN = /\b(seed|pre-seed|series\s*[a-f]|angel|bridge|pre-series\s*[a-f]|growth|debt|venture|ipo|late[\s-]stage|early[\s-]stage)\b/gi;
const VALUATION_PATTERN = /(?:valued?\s+at|valuation\s+(?:of|at|around|near|approximately)?)\s*(?:INR|Rs\.?|USD|\$|US\$|S\$|SGD)?\s*[\d.,]+\s*(?:million|mn|m|billion|bn|b|cr|crore|Cr|Mn|Bn)\b/gi;
const VALUATION_AMOUNT_PATTERN = /(?:INR|Rs\.?|USD|\$|US\$|S\$|SGD)?\s*([\d.,]+)\s*(million|mn|m|billion|bn|b|cr|crore|Cr|Mn|Bn)/i;

const SECTOR_KEYWORDS = [
  'fintech','edtech','healthtech','medtech','agritech','foodtech','proptech','insurtech',
  'legaltech','hrtech','martech','adtech','cleantech','greentech','biotech','deeptech',
  'spacetech','saas','b2b','b2c','d2c','e-commerce','ecommerce','logistics','mobility',
  'ev','electric vehicle','ai','artificial intelligence','machine learning','blockchain',
  'crypto','web3','gaming','social media','media','entertainment','healthcare','pharma',
  'wellness','fitness','education','real estate','agriculture','food','travel','hospitality',
  'fashion','beauty','lifestyle','energy','solar','renewable','manufacturing','cybersecurity',
  'iot','robotics','automation','supply chain','insurance','lending','payments','banking',
  'neobank','climate','sustainability','content','creator economy','streaming'
];

const GEO_PATTERNS = [
  { pattern: /\b(india|indian|mumbai|delhi|bangalore|bengaluru|hyderabad|chennai|pune|kolkata|gurgaon|gurugram|noida|ahmedabad|jaipur|lucknow|kochi|chandigarh)\b/i, geo: 'India', country: 'India' },
  { pattern: /\b(singapore|singaporean|sg-based)\b/i, geo: 'Singapore', country: 'Singapore' },
  { pattern: /\b(indonesia|indonesian|jakarta)\b/i, geo: 'Indonesia', country: 'Indonesia' },
  { pattern: /\b(vietnam|vietnamese|hanoi|ho chi minh)\b/i, geo: 'Vietnam', country: 'Vietnam' },
  { pattern: /\b(thailand|thai|bangkok)\b/i, geo: 'Thailand', country: 'Thailand' },
  { pattern: /\b(philippines|filipino|manila)\b/i, geo: 'Philippines', country: 'Philippines' },
  { pattern: /\b(malaysia|malaysian|kuala lumpur)\b/i, geo: 'Malaysia', country: 'Malaysia' },
  { pattern: /\b(southeast asia|sea)\b/i, geo: 'Southeast Asia', country: null },
  { pattern: /\b(united states|us-based|silicon valley|san francisco|new york|boston|usa)\b/i, geo: 'United States', country: 'United States' },
  { pattern: /\b(europe|london|berlin|paris|amsterdam|uk|united kingdom)\b/i, geo: 'Europe', country: null },
  { pattern: /\b(middle east|dubai|uae|saudi|mena)\b/i, geo: 'Middle East', country: null },
  { pattern: /\b(china|chinese|beijing|shanghai)\b/i, geo: 'China', country: 'China' },
  { pattern: /\b(japan|japanese|tokyo)\b/i, geo: 'Japan', country: 'Japan' },
  { pattern: /\b(korea|korean|seoul)\b/i, geo: 'South Korea', country: 'South Korea' },
  { pattern: /\b(australia|australian|sydney|melbourne)\b/i, geo: 'Australia', country: 'Australia' },
  { pattern: /\b(global|worldwide|international)\b/i, geo: 'Global', country: null }
];

const INVESTOR_PATTERNS = [
  /(?:led by|backed by|from|funding from|investment from|participated by)\s+([A-Z][A-Za-z\s&.,]+?)(?:\s*(?:and|,|\.|along with|with participation|the round))/gi,
  /(?:investors?\s+(?:include|such as|like|including|are))\s+([A-Z][A-Za-z\s&.,]+?)(?:\s*(?:\.|participated|invested|among))/gi,
  /([A-Z][A-Za-z\s]+(?:Capital|Ventures|Partners|Fund|Investment[s]?|VC|Holdings|Group|Equity|Management|Advisors|Labs|Studio|Associates))/g,
  /(?:angel investor[s]?)\s+([A-Z][A-Za-z\s]+?)(?:\s*(?:,|and|\.|who|also|have|has))/gi,
  /([A-Z][a-z]+\s+[A-Z][a-z]+)(?:\s*,\s*(?:founder|CEO|CTO|partner|managing director|GP|angel|investor|MD|VP|head|director|co-founder))/g
];

const COMMON_FALSE_POSITIVES = new Set([
  'The Company','The Startup','The Firm','The Fund','The Round','The Deal','This Round',
  'The Investment','New Delhi','San Francisco','Silicon Valley','Inc','Also Read','Read More',
  'Press Release','According To','In Addition','As Per','Last Year','This Year','Earlier This',
  'Said In','The Report','Going Forward','Looking At','Featured Image','Image Credit',
  'Related Articles','Subscribe Now','Follow Us','Share This','Read Also','Latest News',
  'Breaking News','Exclusive','Updated On','Published On','Written By','Edited By'
]);

// Site-specific configs
const SITE_CONFIGS = {
  yourstory: {
    name: 'yourstory',
    baseUrl: 'https://yourstory.com',
    defaultCountry: 'India',
    listingUrls: [
      'https://yourstory.com/category/funding-alert',
      'https://yourstory.com/category/startups'
    ],
    articleSelector: 'a[href*="/funding-alert/"], a[href*="/2025/"], a[href*="/2026/"]',
    articleFilter: (href) => {
      return (href.includes('/funding-alert/') || href.includes('/2026/') || href.includes('/2025/')) &&
        !href.includes('/page/') && !href.includes('#') && !href.endsWith('/category/');
    },
    contentSelector: '.post-content, .article-content, article .content, .blogContent, main article',
    titleSelector: 'h1',
    dateSelector: 'time, [datetime], .post-date'
  },
  livemint: {
    name: 'livemint',
    baseUrl: 'https://www.livemint.com',
    defaultCountry: 'India',
    listingUrls: [
      'https://www.livemint.com/companies/start-ups',
      'https://www.livemint.com/companies/news'
    ],
    articleSelector: 'a[href*="/companies/"]',
    articleFilter: (href) => {
      return href.includes('/companies/') &&
        (href.includes('-1') || href.match(/\/\d{11,}/)) &&
        !href.includes('/page/') && !href.includes('#');
    },
    contentSelector: '.contentSec, .mainArea, article, .story-element, .paywall',
    titleSelector: 'h1',
    dateSelector: 'time, [datetime], .articleInfo span'
  },
  vccircle: {
    name: 'vccircle',
    baseUrl: 'https://www.vccircle.com',
    defaultCountry: 'India',
    listingUrls: [
      'https://www.vccircle.com/deals'
    ],
    articleSelector: 'a[href*="/deals/"], a[href*="/news/"]',
    articleFilter: (href) => {
      return (href.includes('/deals/') || href.includes('/news/')) &&
        !href.includes('/page/') && !href.includes('#');
    },
    contentSelector: '.article-body, .story-content, article, main',
    titleSelector: 'h1',
    dateSelector: 'time, [datetime], .date'
  },
  entrackr: {
    name: 'entrackr',
    baseUrl: 'https://entrackr.com',
    defaultCountry: 'India',
    listingUrls: [
      'https://entrackr.com/category/funding/'
    ],
    articleSelector: 'a[href*="/funding/"], a[href*="/2026/"], a[href*="/2025/"]',
    articleFilter: (href) => {
      return !href.includes('/page/') && !href.includes('#') && !href.endsWith('/category/funding/');
    },
    contentSelector: '.entry-content, .post-content, article',
    titleSelector: 'h1',
    dateSelector: 'time, [datetime], .entry-date'
  },
  e27: {
    name: 'e27',
    baseUrl: 'https://e27.co',
    listingUrls: [
      'https://e27.co/category/newsfeed',
      'https://e27.co/category/funding'
    ],
    articleSelector: 'a[href*="/startups/"], a[href*="/news/"], a[href*="/funding/"]',
    articleFilter: (href) => {
      return (href.includes('e27.co/') || href.includes('e27.co/startups/') || href.includes('e27.co/news/')) &&
        !href.includes('/page/') && !href.includes('#') && !href.endsWith('/category/') &&
        href !== 'https://e27.co/' && href.split('/').length > 4;
    },
    contentSelector: '.post-content, .article-content, article .content, main article, .entry-content',
    titleSelector: 'h1',
    dateSelector: 'time, [datetime], .post-date, .date',
    defaultCountry: 'Singapore'
  },
  techinasia: {
    name: 'techinasia',
    baseUrl: 'https://www.techinasia.com',
    listingUrls: [
      'https://www.techinasia.com/news',
      'https://www.techinasia.com/tag/funding'
    ],
    articleSelector: 'a[href*="/news/"], a[href*="/2026/"], a[href*="/2025/"]',
    articleFilter: (href) => {
      return href.includes('techinasia.com/') &&
        !href.includes('/page/') && !href.includes('#') && !href.includes('/tag/') &&
        href !== 'https://www.techinasia.com/' && href.split('/').length > 3;
    },
    contentSelector: '.post-content, .article-content, article, main, .content-body',
    titleSelector: 'h1',
    dateSelector: 'time, [datetime], .date, .post-date',
    defaultCountry: 'Singapore'
  },
  dealstreetasia: {
    name: 'dealstreetasia',
    baseUrl: 'https://www.dealstreetasia.com',
    listingUrls: [
      'https://www.dealstreetasia.com/partner-content',
      'https://www.dealstreetasia.com/stories'
    ],
    articleSelector: 'a[href*="/stories/"], a[href*="/partner-content/"]',
    articleFilter: (href) => {
      return href.includes('dealstreetasia.com/') &&
        (href.includes('/stories/') || href.includes('/partner-content/')) &&
        !href.includes('/page/') && !href.includes('#');
    },
    contentSelector: '.article-content, .post-content, article, main, .story-content',
    titleSelector: 'h1',
    dateSelector: 'time, [datetime], .date, .post-date',
    defaultCountry: 'Singapore'
  }
};

class NewsScraper {
  constructor(siteKey) {
    this.config = SITE_CONFIGS[siteKey];
    if (!this.config) throw new Error(`Unknown site: ${siteKey}. Available: ${Object.keys(SITE_CONFIGS).join(', ')}`);
    this.browser = null;
    this.investorResults = [];
    this.newsResults = [];
  }

  async launch() {
    this.browser = await puppeteer.launch({
      headless: 'new',
      args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080'],
      defaultViewport: { width: 1920, height: 1080 }
    });
  }

  async close() {
    if (this.browser) { await this.browser.close(); this.browser = null; }
  }

  async scrapeListingPage(url, maxPages = 2) {
    const page = await this.browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setRequestInterception(true);
    page.on('request', req => {
      if (['image','font','stylesheet','media'].includes(req.resourceType())) req.abort();
      else req.continue();
    });

    const articleLinks = [];

    for (let p = 1; p <= maxPages; p++) {
      const pageUrl = p === 1 ? url : `${url}/page/${p}`;
      console.log(`[${this.config.name}] Listing: ${pageUrl}`);
      try {
        await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await delay(2000);

        const links = await page.evaluate(() => {
          return [...new Set([...document.querySelectorAll('a[href]')].map(a => a.href))];
        });

        const filtered = links.filter(this.config.articleFilter);
        articleLinks.push(...filtered);
        console.log(`[${this.config.name}] Found ${filtered.length} links on page ${p}`);
        await delay(2000 + Math.random() * 2000);
      } catch (err) {
        console.error(`[${this.config.name}] Listing error: ${err.message}`);
      }
    }

    await page.close();
    return [...new Set(articleLinks)];
  }

  async scrapeArticle(url) {
    const page = await this.browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setRequestInterception(true);
    page.on('request', req => {
      if (['image','font','media'].includes(req.resourceType())) req.abort();
      else req.continue();
    });

    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      const config = this.config;

      const data = await page.evaluate((cfg) => {
        const title = document.querySelector(cfg.titleSelector)?.textContent?.trim() || '';
        const bodyEl = document.querySelector(cfg.contentSelector);
        const body = bodyEl?.textContent?.trim() || '';
        const dateEl = document.querySelector(cfg.dateSelector);
        const date = dateEl?.getAttribute('datetime') || dateEl?.textContent?.trim() || '';
        // Get first 300 chars as summary
        const summary = body.substring(0, 300).replace(/\s+/g, ' ').trim();
        return { title, body, date, summary };
      }, config);

      await page.close();

      if (!data.body || data.body.length < 100) return null;
      return { ...data, url };
    } catch (err) {
      console.error(`[${this.config.name}] Article error ${url}: ${err.message}`);
      await page.close();
      return null;
    }
  }

  extractData(articleData) {
    const text = `${articleData.title} ${articleData.body}`;
    const isFunding = /\b(fund|rais|invest|back|secur|round|seed|series|angel|venture|capital|million|crore|billion)\b/i.test(text);

    if (!isFunding) return;

    const amounts = text.match(AMOUNT_PATTERN) || [];
    const amount = amounts[0] || null;
    const rounds = text.match(ROUND_PATTERN) || [];
    const roundType = rounds[0] || null;
    const stage = roundType ? mapRoundToStage(roundType) : null;

    // Extract valuation
    const valuationMatches = text.match(VALUATION_PATTERN) || [];
    let valuation = null;
    let valuationMultiple = null;
    if (valuationMatches.length > 0) {
      valuation = valuationMatches[0].replace(/valued?\s+at|valuation\s+(?:of|at|around|near|approximately)?/i, '').trim();
      // Try to calculate valuation multiple if we have both valuation and amount
      if (valuation && amount) {
        valuationMultiple = calculateValuationMultiple(amount, valuation);
      }
    }

    const detectedSectors = SECTOR_KEYWORDS.filter(kw =>
      new RegExp(`\\b${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(text)
    );
    const sector = detectedSectors.slice(0, 5).join(', ') || null;

    const matchedGeos = GEO_PATTERNS.filter(gp => gp.pattern.test(text));
    const detectedGeos = matchedGeos.map(gp => gp.geo);
    const geography = [...new Set(detectedGeos)].join(', ') || null;

    // Determine country - prioritize India/Singapore, then first detected country
    let country = this.config.defaultCountry || null;
    const detectedCountries = matchedGeos.filter(gp => gp.country).map(gp => gp.country);
    if (detectedCountries.includes('India')) country = 'India';
    else if (detectedCountries.includes('Singapore')) country = 'Singapore';
    else if (detectedCountries.length > 0) country = detectedCountries[0];

    // Extract investor names
    const foundNames = new Set();
    for (const pattern of INVESTOR_PATTERNS) {
      let match;
      const p = new RegExp(pattern.source, pattern.flags); // fresh regex
      while ((match = p.exec(text)) !== null) {
        match[1].split(/,\s*|\s+and\s+/).map(n => n.trim()).filter(n => n.length > 2 && n.length < 80).forEach(name => {
          name = name.replace(/\s+/g, ' ').trim();
          if (!COMMON_FALSE_POSITIVES.has(name) && /[A-Z]/.test(name) && name.split(' ').length <= 6) {
            foundNames.add(name);
          }
        });
      }
    }

    // Insert funding news
    const startupMatch = articleData.title.match(/^([A-Z][A-Za-z0-9\s.]+?)(?:\s+(?:raises|secures|gets|bags|closes|lands|nabs|receives|grabs))/i);
    const startupName = startupMatch ? startupMatch[1].trim() : null;

    this.newsResults.push({
      headline: articleData.title,
      summary: articleData.summary || null,
      startup_name: startupName,
      amount,
      round_type: roundType,
      investors: [...foundNames].join(', '),
      sector,
      valuation,
      valuation_multiple: valuationMultiple,
      country,
      source: this.config.name,
      source_url: articleData.url,
      published_date: articleData.date || null
    });

    // Create investor records
    for (const name of foundNames) {
      const isInstitution = /capital|ventures|partners|fund|investment|holdings|group|equity|management|advisors|labs|studio|vc|associates/i.test(name);
      this.investorResults.push({
        name,
        institution: isInstitution ? name : null,
        title: isInstitution ? null : null,
        avg_cheque_size: amount || null,
        geographies: geography,
        sectors: sector,
        stage,
        source: this.config.name,
        source_url: articleData.url,
        notes: `From: "${articleData.title.substring(0, 120)}"`
      });
    }

    // Log funding round
    if (startupName) {
      try {
        insertFundingRound({
          startup_name: startupName, amount, round_type: roundType,
          investors: [...foundNames].join(', '), sector,
          valuation, valuation_multiple: valuationMultiple, country,
          date_reported: articleData.date || null,
          source: this.config.name, source_url: articleData.url
        });
      } catch (e) { /* ignore */ }
    }
  }

  async run(maxPages = 2) {
    const scrapeId = logScrape(this.config.name);
    let totalFound = 0, totalNew = 0;

    try {
      await this.launch();
      console.log(`[${this.config.name}] Browser launched`);

      let allLinks = [];
      for (const listUrl of this.config.listingUrls) {
        const links = await this.scrapeListingPage(listUrl, maxPages);
        allLinks.push(...links);
      }

      allLinks = [...new Set(allLinks)];
      // Prioritize funding articles
      const fundingLinks = allLinks.filter(l => /fund|rais|invest|round|seed|series|secur|million|crore/i.test(l));
      const others = allLinks.filter(l => !fundingLinks.includes(l)).slice(0, 5);
      const toProcess = [...fundingLinks, ...others];

      console.log(`[${this.config.name}] Processing ${toProcess.length} articles (${fundingLinks.length} funding)`);

      for (const link of toProcess) {
        const data = await this.scrapeArticle(link);
        if (data) this.extractData(data);
        await delay(3000 + Math.random() * 3000);
      }

      // Save investors
      for (const inv of this.investorResults) {
        try {
          const res = upsertInvestor(inv);
          totalFound++;
          if (res.action === 'inserted') totalNew++;
        } catch (e) { console.error(`[${this.config.name}] Save error: ${e.message}`); }
      }

      // Save news
      for (const news of this.newsResults) {
        try { insertFundingNews(news); } catch (e) { /* skip */ }
      }

      console.log(`[${this.config.name}] Done: ${totalFound} investors (${totalNew} new), ${this.newsResults.length} news`);
      updateScrapeLog(scrapeId, { status: 'completed', records_found: totalFound, new_records: totalNew });
    } catch (err) {
      console.error(`[${this.config.name}] Failed: ${err.message}`);
      updateScrapeLog(scrapeId, { status: 'failed', records_found: totalFound, new_records: totalNew, error_message: err.message });
    } finally {
      await this.close();
    }

    return { totalFound, totalNew, newsCount: this.newsResults.length };
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

function parseAmountToNumber(amountStr) {
  if (!amountStr) return null;
  const cleaned = amountStr.replace(/[^\d.,a-zA-Z\s]/g, '').trim();
  const numMatch = cleaned.match(/([\d.,]+)\s*(million|mn|m|billion|bn|b|cr|crore|Cr|Mn|Bn|lakh|k)/i);
  if (!numMatch) return null;
  const num = parseFloat(numMatch[1].replace(/,/g, ''));
  const unit = numMatch[2].toLowerCase();
  const multipliers = { 'million': 1e6, 'mn': 1e6, 'm': 1e6, 'billion': 1e9, 'bn': 1e9, 'b': 1e9, 'cr': 1.2e7, 'crore': 1.2e7, 'lakh': 1.2e5, 'k': 1e3 };
  return num * (multipliers[unit] || 1);
}

function calculateValuationMultiple(amountStr, valuationStr) {
  const amount = parseAmountToNumber(amountStr);
  const valuation = parseAmountToNumber(valuationStr);
  if (!amount || !valuation || amount === 0) return null;
  const multiple = valuation / amount;
  return `${multiple.toFixed(1)}x`;
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

module.exports = { NewsScraper, SITE_CONFIGS };
