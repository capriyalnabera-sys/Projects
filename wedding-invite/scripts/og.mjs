/**
 * Renders assets/img/og.png — the 1200×630 card WhatsApp, iMessage and
 * everything else shows before anyone taps the link.
 *
 * Built from content.js so it can never drift from the invite itself.
 */
import { readFile, writeFile, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT, loadContent, esc } from './lib/content.mjs';
import { getChromium } from './lib/browser.mjs';

const D = await loadContent();
const t = D.theme || {};
const c = D.couple || {};
const h = D.hero || {};
const s = D.share || {};

/* Inline the hero artwork so the screenshot never races an image load. */
let art = '';
if (h.art) {
  try {
    const raw = await readFile(join(ROOT, h.art), 'utf8');
    art = h.art.endsWith('.svg') ? raw : '';
  } catch { /* missing art is not fatal — the card still works */ }
}
if (!art && h.art) {
  art = `<img src="${esc(pathToFileURL(join(ROOT, h.art)).href)}" alt="">`;
}

const card = `<!doctype html><meta charset="utf-8">
<style>
  * { margin: 0; box-sizing: border-box; }
  body {
    width: 1200px; height: 630px; display: flex; align-items: center;
    gap: 56px; padding: 64px 72px;
    background: ${t.paper || '#FAF4EA'};
    color: ${t.ink || '#211A16'};
    font-family: "Georgia", "Liberation Serif", "DejaVu Serif", serif;
  }
  body::after {
    content: ""; position: fixed; inset: 26px;
    border: 1px solid ${t.rule || '#E2D6C4'}; pointer-events: none;
  }
  .text { flex: 1 1 auto; min-width: 0; }
  .eyebrow {
    font-family: "Helvetica", "Liberation Sans", "DejaVu Sans", sans-serif;
    font-size: 21px; letter-spacing: 5px; text-transform: uppercase;
    font-weight: 700; color: ${t.accent || '#C2452D'};
  }
  .names { font-size: 96px; line-height: 1.02; letter-spacing: -2px; margin-top: 26px; }
  .amp { display: block; font-size: 42px; font-style: italic; color: ${t.accent || '#C2452D'}; margin: 6px 0; }
  .rule { width: 92px; height: 2px; background: ${t.accent2 || '#D9922F'}; margin: 34px 0 26px; }
  .meta {
    font-family: "Helvetica", "Liberation Sans", "DejaVu Sans", sans-serif;
    font-size: 25px; letter-spacing: 3px; text-transform: uppercase;
    color: ${t.muted || '#6F6257'}; line-height: 1.7;
  }
  .meta strong { color: ${t.ink || '#211A16'}; font-weight: 700; }
  .art { flex: 0 0 400px; height: 400px; display: grid; place-items: center; }
  .art svg, .art img { width: 100%; height: 100%; object-fit: contain; }
</style>
<div class="text">
  <p class="eyebrow">${esc(h.eyebrow || 'You’re invited')}</p>
  <h1 class="names">${esc(c.one?.name || '')}<span class="amp">&amp;</span>${esc(c.two?.name || '')}</h1>
  <div class="rule"></div>
  <p class="meta"><strong>${esc(h.dateLine || '')}</strong><br>${esc(h.placeLine || '')}</p>
</div>
<div class="art">${art}</div>
`;

const tmp = join(ROOT, '.og-tmp.html');
await writeFile(tmp, card);

const chromium = await getChromium();
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
  await page.goto(pathToFileURL(tmp).href, { waitUntil: 'networkidle' });
  await page.screenshot({ path: join(ROOT, 'assets', 'img', 'og.png'), type: 'png' });
} finally {
  await browser.close();
  await unlink(tmp).catch(() => {});
}

console.log('✓ og image      assets/img/og.png (1200×630)');
console.log(`  preview text  ${s.title || ''}`);
