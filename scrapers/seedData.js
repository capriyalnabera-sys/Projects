// Seed data: Global investors active in India and APAC
// Run: node scrapers/seedData.js

const { getDb, upsertInvestor } = require('../database');

const GLOBAL_INVESTORS = [
  // --- Top Global VCs investing in India/APAC ---
  { name: 'Sequoia Capital India', institution: 'Sequoia Capital India (Peak XV Partners)', avg_cheque_size: '$5M - $100M', geographies: 'India, Southeast Asia', sectors: 'fintech, saas, consumer, healthtech, edtech, deeptech', stage: 'Seed, Series A, Series B, Series C', website: 'https://www.peakxv.com', source: 'curated' },
  { name: 'Accel', institution: 'Accel', avg_cheque_size: '$1M - $100M', geographies: 'India, United States, Global', sectors: 'saas, fintech, consumer, enterprise, deeptech', stage: 'Seed, Series A, Series B', website: 'https://www.accel.com', source: 'curated' },
  { name: 'Tiger Global Management', institution: 'Tiger Global Management', avg_cheque_size: '$10M - $500M', geographies: 'India, United States, Global', sectors: 'fintech, e-commerce, saas, consumer', stage: 'Series A, Series B, Series C, Growth', website: 'https://www.tigerglobal.com', source: 'curated' },
  { name: 'SoftBank Vision Fund', institution: 'SoftBank Group', avg_cheque_size: '$50M - $1B+', geographies: 'India, Japan, Southeast Asia, Global', sectors: 'e-commerce, fintech, mobility, logistics, ai', stage: 'Series C, Series D+, Growth', website: 'https://visionfund.com', source: 'curated' },
  { name: 'Lightspeed Venture Partners', institution: 'Lightspeed Venture Partners', avg_cheque_size: '$2M - $50M', geographies: 'India, United States, Southeast Asia', sectors: 'saas, fintech, consumer, enterprise, healthtech', stage: 'Seed, Series A, Series B', website: 'https://lsvp.com', source: 'curated' },
  { name: 'Matrix Partners India (Z47)', institution: 'Matrix Partners India', avg_cheque_size: '$1M - $20M', geographies: 'India', sectors: 'consumer, fintech, healthcare, saas, edtech', stage: 'Seed, Series A', website: 'https://www.matrixpartners.in', source: 'curated' },
  { name: 'Elevation Capital', institution: 'Elevation Capital', avg_cheque_size: '$1M - $25M', geographies: 'India', sectors: 'consumer, fintech, saas, healthtech, edtech', stage: 'Seed, Series A, Series B', website: 'https://www.elevationcapital.com', source: 'curated' },
  { name: 'Blume Ventures', institution: 'Blume Ventures', avg_cheque_size: '$500K - $5M', geographies: 'India', sectors: 'saas, deeptech, fintech, healthcare', stage: 'Pre-Seed, Seed', website: 'https://blume.vc', source: 'curated' },
  { name: 'Nexus Venture Partners', institution: 'Nexus Venture Partners', avg_cheque_size: '$2M - $30M', geographies: 'India, United States', sectors: 'saas, fintech, deeptech, enterprise, agritech', stage: 'Seed, Series A, Series B', website: 'https://nexusvp.com', source: 'curated' },
  { name: 'Bessemer Venture Partners', institution: 'Bessemer Venture Partners', avg_cheque_size: '$5M - $50M', geographies: 'India, United States, Global', sectors: 'saas, fintech, consumer, healthtech', stage: 'Series A, Series B, Series C', website: 'https://www.bvp.com', source: 'curated' },
  { name: 'Kalaari Capital', institution: 'Kalaari Capital', avg_cheque_size: '$1M - $10M', geographies: 'India', sectors: 'consumer, fintech, healthtech, edtech, gaming', stage: 'Seed, Series A', website: 'https://www.kalaari.com', source: 'curated' },
  { name: 'Chiratae Ventures', institution: 'Chiratae Ventures (IDG Ventures India)', avg_cheque_size: '$1M - $15M', geographies: 'India', sectors: 'saas, fintech, healthtech, ai, consumer', stage: 'Seed, Series A, Series B', website: 'https://www.chiratae.com', source: 'curated' },
  { name: 'Norwest Venture Partners', institution: 'Norwest Venture Partners', avg_cheque_size: '$5M - $50M', geographies: 'India, United States, Global', sectors: 'saas, fintech, consumer, enterprise', stage: 'Series A, Series B, Series C', website: 'https://www.nvp.com', source: 'curated' },
  { name: 'Steadview Capital', institution: 'Steadview Capital', avg_cheque_size: '$10M - $100M', geographies: 'India, Global', sectors: 'fintech, e-commerce, consumer, saas', stage: 'Series B, Series C, Growth', website: null, source: 'curated' },
  { name: 'General Atlantic', institution: 'General Atlantic', avg_cheque_size: '$50M - $500M', geographies: 'India, United States, Global', sectors: 'fintech, consumer, healthtech, saas', stage: 'Growth, Series D+', website: 'https://www.generalatlantic.com', source: 'curated' },
  { name: 'Temasek', institution: 'Temasek Holdings', avg_cheque_size: '$50M - $500M', geographies: 'India, Singapore, Southeast Asia, Global', sectors: 'fintech, consumer, healthcare, logistics', stage: 'Series C, Growth, Series D+', website: 'https://www.temasek.com.sg', source: 'curated' },
  { name: 'GIC', institution: 'GIC Private Limited', avg_cheque_size: '$50M - $1B', geographies: 'India, Singapore, Global', sectors: 'fintech, e-commerce, real estate, logistics', stage: 'Growth, Series D+', website: 'https://www.gic.com.sg', source: 'curated' },
  { name: 'Prosus Ventures', institution: 'Prosus (Naspers)', avg_cheque_size: '$20M - $200M', geographies: 'India, Global', sectors: 'fintech, e-commerce, edtech, foodtech, payments', stage: 'Series B, Series C, Growth', website: 'https://www.prosus.com', source: 'curated' },
  { name: 'DST Global', institution: 'DST Global', avg_cheque_size: '$20M - $300M', geographies: 'India, Global', sectors: 'e-commerce, fintech, consumer, saas', stage: 'Series B, Series C, Growth', website: 'https://dst.global', source: 'curated' },
  { name: 'Founders Fund', institution: 'Founders Fund', avg_cheque_size: '$5M - $100M', geographies: 'India, United States, Global', sectors: 'deeptech, ai, saas, biotech, spacetech', stage: 'Seed, Series A, Series B', website: 'https://foundersfund.com', source: 'curated' },
  { name: 'Andreessen Horowitz (a16z)', institution: 'a16z', avg_cheque_size: '$5M - $100M', geographies: 'India, United States, Global', sectors: 'crypto, web3, ai, fintech, saas, consumer', stage: 'Seed, Series A, Series B, Series C', website: 'https://a16z.com', source: 'curated' },
  { name: 'B Capital Group', institution: 'B Capital Group', avg_cheque_size: '$10M - $60M', geographies: 'India, Southeast Asia, United States', sectors: 'fintech, healthtech, enterprise, logistics', stage: 'Series B, Series C', website: 'https://www.bcapgroup.com', source: 'curated' },
  { name: 'Jungle Ventures', institution: 'Jungle Ventures', avg_cheque_size: '$5M - $30M', geographies: 'India, Southeast Asia, Singapore', sectors: 'saas, fintech, consumer, enterprise', stage: 'Series A, Series B', website: 'https://www.jungle.vc', source: 'curated' },
  { name: 'East Ventures', institution: 'East Ventures', avg_cheque_size: '$500K - $5M', geographies: 'Indonesia, Southeast Asia, India', sectors: 'e-commerce, fintech, logistics, saas', stage: 'Seed, Series A', website: 'https://east.vc', source: 'curated' },
  { name: 'Vertex Ventures SEA', institution: 'Vertex Ventures Southeast Asia & India', avg_cheque_size: '$2M - $20M', geographies: 'India, Southeast Asia, Singapore', sectors: 'fintech, healthtech, enterprise, consumer', stage: 'Seed, Series A, Series B', website: 'https://www.vertexventures.com', source: 'curated' },
  { name: 'Warburg Pincus', institution: 'Warburg Pincus', avg_cheque_size: '$50M - $500M', geographies: 'India, Global', sectors: 'financial services, healthcare, consumer, real estate', stage: 'Growth, Series D+', website: 'https://warburgpincus.com', source: 'curated' },
  { name: 'KKR', institution: 'Kohlberg Kravis Roberts', avg_cheque_size: '$50M - $1B', geographies: 'India, Global', sectors: 'fintech, healthcare, infrastructure, consumer', stage: 'Growth, Series D+', website: 'https://www.kkr.com', source: 'curated' },
  { name: 'Carlyle Group', institution: 'The Carlyle Group', avg_cheque_size: '$50M - $300M', geographies: 'India, Global', sectors: 'financial services, consumer, healthcare, saas', stage: 'Growth, Series D+', website: 'https://www.carlyle.com', source: 'curated' },
  { name: 'Ribbit Capital', institution: 'Ribbit Capital', avg_cheque_size: '$5M - $50M', geographies: 'India, United States, Global', sectors: 'fintech, payments, lending, insurtech, neobank', stage: 'Seed, Series A, Series B', website: 'https://ribbitcap.com', source: 'curated' },
  { name: 'Coatue Management', institution: 'Coatue Management', avg_cheque_size: '$10M - $200M', geographies: 'India, United States, Global', sectors: 'saas, fintech, consumer, ai, deeptech', stage: 'Series B, Series C, Growth', website: 'https://www.coatue.com', source: 'curated' },

  // --- India-focused Angel Investors ---
  { name: 'Kunal Shah', institution: 'CRED', title: 'Founder & CEO, CRED', avg_cheque_size: '$100K - $500K', geographies: 'India', sectors: 'fintech, d2c, saas, consumer', stage: 'Angel, Pre-Seed', source: 'curated' },
  { name: 'Rajan Anandan', institution: 'Peak XV Partners', title: 'MD, Peak XV Partners', avg_cheque_size: '$50K - $500K', geographies: 'India, Southeast Asia', sectors: 'saas, ai, deeptech, consumer', stage: 'Angel, Seed', source: 'curated' },
  { name: 'Anupam Mittal', institution: 'Shaadi.com / People Group', title: 'Founder, People Group', avg_cheque_size: '$50K - $300K', geographies: 'India', sectors: 'consumer, d2c, edtech, healthtech', stage: 'Angel, Seed', source: 'curated' },
  { name: 'Aman Gupta', institution: 'boAt Lifestyle', title: 'Co-founder, boAt', avg_cheque_size: '$50K - $250K', geographies: 'India', sectors: 'd2c, consumer, e-commerce', stage: 'Angel', source: 'curated' },
  { name: 'Vineeta Singh', institution: 'SUGAR Cosmetics', title: 'CEO, SUGAR Cosmetics', avg_cheque_size: '$50K - $200K', geographies: 'India', sectors: 'd2c, beauty, consumer, fashion', stage: 'Angel', source: 'curated' },
  { name: 'Peyush Bansal', institution: 'Lenskart', title: 'Founder & CEO, Lenskart', avg_cheque_size: '$50K - $500K', geographies: 'India', sectors: 'consumer, d2c, healthtech, e-commerce', stage: 'Angel, Seed', source: 'curated' },
  { name: 'Nithin Kamath', institution: 'Zerodha / Rainmatter', title: 'Founder, Zerodha', avg_cheque_size: '$100K - $1M', geographies: 'India', sectors: 'fintech, climate, sustainability, saas', stage: 'Angel, Seed', source: 'curated' },
  { name: 'Sanjay Mehta', institution: '100X.VC', title: 'Founder, 100X.VC', avg_cheque_size: '$25K - $250K', geographies: 'India', sectors: 'saas, fintech, healthtech, edtech, deeptech', stage: 'Pre-Seed, Seed', source: 'curated' },
  { name: 'Amit Somani', institution: 'Prime Venture Partners', title: 'MP, Prime VP', avg_cheque_size: '$500K - $5M', geographies: 'India', sectors: 'saas, fintech, healthtech, edtech, ai', stage: 'Seed, Series A', source: 'curated' },

  // --- APAC VCs ---
  { name: 'Sequoia Capital Southeast Asia', institution: 'Sequoia Capital SEA', avg_cheque_size: '$1M - $50M', geographies: 'Southeast Asia, India, Singapore', sectors: 'fintech, e-commerce, saas, consumer', stage: 'Seed, Series A, Series B', website: 'https://www.sequoiacap.com', source: 'curated' },
  { name: 'Golden Gate Ventures', institution: 'Golden Gate Ventures', avg_cheque_size: '$500K - $5M', geographies: 'Southeast Asia, India, Singapore', sectors: 'fintech, logistics, saas, consumer', stage: 'Seed, Series A', website: 'https://goldengate.vc', source: 'curated' },
  { name: 'Monk\'s Hill Ventures', institution: 'Monk\'s Hill Ventures', avg_cheque_size: '$1M - $10M', geographies: 'Southeast Asia, Singapore', sectors: 'saas, fintech, deeptech, enterprise', stage: 'Seed, Series A', website: 'https://www.monkshill.com', source: 'curated' },
  { name: 'Wavemaker Partners', institution: 'Wavemaker Partners', avg_cheque_size: '$500K - $5M', geographies: 'Southeast Asia, India', sectors: 'deeptech, saas, healthtech, sustainability', stage: 'Seed, Series A', website: 'https://wavemaker.vc', source: 'curated' },
  { name: 'Openspace Ventures', institution: 'Openspace Ventures', avg_cheque_size: '$2M - $15M', geographies: 'Southeast Asia, India, Singapore', sectors: 'consumer, fintech, logistics, saas', stage: 'Series A, Series B', website: 'https://www.openspace.vc', source: 'curated' },
  { name: 'Antler', institution: 'Antler', avg_cheque_size: '$100K - $1M', geographies: 'India, Southeast Asia, Global', sectors: 'saas, fintech, deeptech, ai, consumer', stage: 'Pre-Seed, Seed', website: 'https://www.antler.co', source: 'curated' },
  { name: 'Y Combinator', institution: 'Y Combinator', avg_cheque_size: '$500K', geographies: 'India, Global', sectors: 'saas, fintech, ai, consumer, b2b, deeptech', stage: 'Pre-Seed, Seed', website: 'https://www.ycombinator.com', source: 'curated' },
  { name: 'Techstars', institution: 'Techstars', avg_cheque_size: '$120K', geographies: 'India, Global', sectors: 'saas, fintech, healthtech, ai, consumer', stage: 'Pre-Seed, Seed', website: 'https://www.techstars.com', source: 'curated' },
  { name: '500 Global', institution: '500 Global (500 Startups)', avg_cheque_size: '$150K - $2M', geographies: 'India, Southeast Asia, Global', sectors: 'fintech, saas, consumer, edtech, healthtech', stage: 'Pre-Seed, Seed', website: 'https://500.co', source: 'curated' },

  // --- Family Offices & Impact Investors ---
  { name: 'Catamaran Ventures', institution: 'Catamaran Ventures', title: null, avg_cheque_size: '$5M - $30M', geographies: 'India', sectors: 'consumer, fintech, saas, healthcare', stage: 'Series A, Series B', source: 'curated', notes: 'NR Narayana Murthy family office' },
  { name: 'Azim Premji Foundation', institution: 'Premji Invest', avg_cheque_size: '$10M - $100M', geographies: 'India', sectors: 'consumer, healthcare, fintech, saas', stage: 'Series B, Growth', source: 'curated' },
  { name: 'Aavishkaar Group', institution: 'Aavishkaar Capital', avg_cheque_size: '$1M - $10M', geographies: 'India, Southeast Asia', sectors: 'agritech, financial inclusion, sustainability, climate', stage: 'Seed, Series A, Series B', website: 'https://www.aavishkaar.org', source: 'curated' },
  { name: 'Omidyar Network India', institution: 'Omidyar Network India', avg_cheque_size: '$1M - $15M', geographies: 'India', sectors: 'fintech, edtech, digital identity, financial inclusion', stage: 'Seed, Series A, Series B', website: 'https://www.omidyarnetwork.in', source: 'curated' },
  { name: 'Ratan Tata (RNT Associates)', institution: 'RNT Associates', title: 'Chairman Emeritus, Tata Sons', avg_cheque_size: '$100K - $2M', geographies: 'India', sectors: 'consumer, healthcare, e-commerce, mobility', stage: 'Angel, Seed', source: 'curated' },
  { name: 'Titan Capital', institution: 'Titan Capital', avg_cheque_size: '$50K - $500K', geographies: 'India', sectors: 'saas, fintech, consumer, d2c, edtech', stage: 'Angel, Seed', source: 'curated', notes: 'Run by Snapdeal founders Kunal Bahl & Rohit Bansal' },
  { name: 'India Quotient', institution: 'India Quotient', avg_cheque_size: '$200K - $2M', geographies: 'India', sectors: 'consumer, fintech, saas, vernacular, Bharat-focused', stage: 'Pre-Seed, Seed', website: 'https://www.indiaquotient.in', source: 'curated' },
  { name: 'Stellaris Venture Partners', institution: 'Stellaris Venture Partners', avg_cheque_size: '$1M - $8M', geographies: 'India', sectors: 'saas, fintech, consumer, enterprise', stage: 'Seed, Series A', website: 'https://www.stellarisvp.com', source: 'curated' },
  { name: 'Fireside Ventures', institution: 'Fireside Ventures', avg_cheque_size: '$1M - $10M', geographies: 'India', sectors: 'consumer, d2c, food, beauty, fashion, lifestyle', stage: 'Seed, Series A', website: 'https://firesideventures.com', source: 'curated' },
  { name: 'Axilor Ventures', institution: 'Axilor Ventures', avg_cheque_size: '$200K - $2M', geographies: 'India', sectors: 'saas, fintech, healthtech, agritech, enterprise', stage: 'Pre-Seed, Seed', website: 'https://www.axilor.com', source: 'curated' },
  { name: 'WaterBridge Ventures', institution: 'WaterBridge Ventures', avg_cheque_size: '$500K - $3M', geographies: 'India', sectors: 'saas, fintech, consumer, b2b', stage: 'Pre-Seed, Seed', website: 'https://www.waterbridge.in', source: 'curated' },
  { name: '3one4 Capital', institution: '3one4 Capital', avg_cheque_size: '$1M - $10M', geographies: 'India', sectors: 'saas, fintech, deeptech, ai, consumer', stage: 'Seed, Series A', website: 'https://3one4.com', source: 'curated' },
  { name: 'Surge (Peak XV)', institution: 'Surge by Peak XV Partners', avg_cheque_size: '$1M - $3M', geographies: 'India, Southeast Asia', sectors: 'saas, fintech, healthtech, consumer, enterprise', stage: 'Seed', website: 'https://www.surgeahead.com', source: 'curated' },
  { name: 'Omnivore', institution: 'Omnivore', avg_cheque_size: '$500K - $5M', geographies: 'India', sectors: 'agritech, foodtech, sustainability, climate', stage: 'Seed, Series A', website: 'https://www.omnivore.vc', source: 'curated' },
  { name: 'pi Ventures', institution: 'pi Ventures', avg_cheque_size: '$500K - $3M', geographies: 'India', sectors: 'ai, deeptech, healthtech, robotics', stage: 'Seed, Series A', website: 'https://www.piventures.in', source: 'curated' },
  { name: 'Iron Pillar', institution: 'Iron Pillar', avg_cheque_size: '$5M - $20M', geographies: 'India', sectors: 'saas, fintech, consumer, enterprise', stage: 'Series A, Series B', website: 'https://www.ironpillar.com', source: 'curated' },
  { name: 'Z3Partners', institution: 'Z3Partners', avg_cheque_size: '$5M - $30M', geographies: 'India', sectors: 'consumer, e-commerce, d2c, retail', stage: 'Series A, Series B, Growth', source: 'curated' },
  { name: 'Fundamentum Partnership', institution: 'Fundamentum Partnership', avg_cheque_size: '$5M - $25M', geographies: 'India', sectors: 'fintech, saas, consumer, enterprise', stage: 'Series A, Series B', source: 'curated', notes: 'Founded by Nandan Nilekani' },
];

async function seed() {
  await getDb();
  let inserted = 0, updated = 0;

  for (const inv of GLOBAL_INVESTORS) {
    try {
      const result = upsertInvestor(inv);
      if (result.action === 'inserted') inserted++;
      else updated++;
      console.log(`  ${result.action}: ${inv.name}`);
    } catch (e) {
      console.error(`  Error: ${inv.name} - ${e.message}`);
    }
  }

  console.log(`\nSeed complete: ${inserted} new, ${updated} updated (${GLOBAL_INVESTORS.length} total)`);
}

if (require.main === module) {
  seed().then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });
}

module.exports = { seed, GLOBAL_INVESTORS };
