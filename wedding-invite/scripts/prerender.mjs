/**
 * Bakes the rendered invite back into index.html.
 *
 * Two reasons, both from the playbook's list of what actually breaks:
 *   - Load speed. The page shows finished content on first paint instead of
 *     waiting for JavaScript — which matters on hotel wifi and 3G.
 *   - It still reads with JavaScript off or broken.
 *
 * app.js empties each section and re-renders on load, so the baked HTML can
 * never disagree with content.js at runtime — worst case it is one build
 * stale for a no-JS visitor. Run this before every deploy.
 */
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, replaceBlock } from './lib/content.mjs';
import { getChromium } from './lib/browser.mjs';

const indexPath = join(ROOT, 'index.html');

const chromium = await getChromium();
const browser = await chromium.launch();

try {
  // reducedMotion keeps the snapshot free of intro/reveal states — otherwise
  // we would bake in elements that are styled invisible until observed.
  const page = await browser.newPage({ reducedMotion: 'reduce' });

  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(pathToFileURL(indexPath).href, { waitUntil: 'networkidle' });
  await page.waitForSelector('#hero .hero__names', { timeout: 10000 });

  if (errors.length) throw new Error('The page threw while rendering:\n' + errors.join('\n'));

  const { main, footer } = await page.evaluate(() => {
    // The countdown is live; baking numbers would ship a stale clock.
    document.querySelectorAll('.countdown').forEach((n) => n.replaceChildren());
    // Belt and braces: never bake a hidden-until-revealed element.
    document.querySelectorAll('.reveal').forEach((n) => {
      n.classList.remove('reveal', 'is-in');
      n.style.transitionDelay = '';
      if (!n.getAttribute('style')) n.removeAttribute('style');
    });
    return {
      main: document.querySelector('main').outerHTML,
      footer: document.getElementById('footer').outerHTML,
    };
  });

  const html = await readFile(indexPath, 'utf8');
  await writeFile(indexPath, replaceBlock(html, 'BODY', `${main}\n\n${footer}`));

  const kb = (Buffer.byteLength(main + footer) / 1024).toFixed(1);
  console.log(`✓ prerendered   index.html (+${kb} KB of static markup)`);
} finally {
  await browser.close();
}
