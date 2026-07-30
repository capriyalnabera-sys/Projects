/**
 * Screenshots the invite at real phone sizes and reports its weight.
 *
 * "Test on a phone, immediately and constantly" is the step everyone skips.
 * This makes it one command. It does not replace opening it on your actual
 * phone — nothing does — but it catches the obvious breakage between times.
 *
 *   npm run shots
 *   → screenshots/*.png  and a weight report in the terminal
 */
import { mkdir, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { ROOT } from './lib/content.mjs';
import { serve } from './lib/serve.mjs';
import { getChromium } from './lib/browser.mjs';

const DEVICES = [
  { name: 'phone-small',  width: 375, height: 667, scale: 2, mobile: true },   // iPhone SE
  { name: 'phone-large',  width: 393, height: 852, scale: 3, mobile: true },   // iPhone 15 Pro
  { name: 'phone-android',width: 412, height: 915, scale: 2.6, mobile: true }, // Pixel 8
  { name: 'desktop',      width: 1280, height: 900, scale: 1, mobile: false },
];

// Anything above this and you are gambling on the venue's signal.
const BUDGET_KB = 400;

const outDir = join(ROOT, 'screenshots');
await rm(outDir, { recursive: true, force: true });
await mkdir(outDir, { recursive: true });

const { server, url } = await serve();
const chromium = await getChromium();
const browser = await chromium.launch();

const weights = new Map();

try {
  for (const d of DEVICES) {
    const context = await browser.newContext({
      viewport: { width: d.width, height: d.height },
      deviceScaleFactor: d.scale,
      isMobile: d.mobile,
      hasTouch: d.mobile,
      // Screenshots should show the page, not the envelope intro.
      reducedMotion: 'reduce',
    });
    const page = await context.newPage();

    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('response', async (res) => {
      if (weights.has(res.url())) return;
      try {
        const body = await res.body();
        weights.set(res.url(), body.length);
      } catch { /* redirects and the like have no body */ }
    });

    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForSelector('#events .event');

    await page.screenshot({ path: join(outDir, `${d.name}.png`), fullPage: true });

    // Above the fold matters most — it is what decides whether people scroll.
    await page.screenshot({ path: join(outDir, `${d.name}-fold.png`) });

    if (errors.length) {
      console.error(`  ✗ ${d.name}: JavaScript errors\n    ${errors.join('\n    ')}`);
      process.exitCode = 1;
    } else {
      console.log(`  ✓ ${d.name.padEnd(14)} ${d.width}×${d.height}`);
    }

    await context.close();
  }
} finally {
  await browser.close();
  server.close();
}

const total = [...weights.values()].reduce((a, b) => a + b, 0);
const kb = total / 1024;

console.log(`\n  Page weight: ${kb.toFixed(1)} KB across ${weights.size} requests`);
if (kb > BUDGET_KB) {
  console.log(`  ! Over the ${BUDGET_KB} KB budget. On 3G at a banquet hall this will crawl.`);
  console.log('    Usual culprit: uncompressed caricature files. See README → Load speed.');
  process.exitCode = 1;
} else {
  console.log(`  Within the ${BUDGET_KB} KB budget. A fast plain invite beats a slow gorgeous one.`);
}
console.log(`\n  Screenshots: ${outDir}\n`);
