/**
 * Writes the <head> meta block and the favicon from content.js.
 *
 * This is the "grey box in the family WhatsApp group" fix: link previews are
 * read by a crawler that does not run JavaScript, so these tags have to exist
 * in the HTML file itself rather than being set at runtime.
 */
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { ROOT, loadContent, esc, absolute, replaceBlock } from './lib/content.mjs';

const D = await loadContent();
const share = D.share || {};
const couple = D.couple || {};
const theme = D.theme || {};

if (!share.url || /example\.com/.test(share.url)) {
  console.warn(
    '\n  ! share.url in content.js is still the placeholder.\n' +
    '    WhatsApp previews need the real, final, absolute URL.\n'
  );
}

const title = share.title || couple.joined || 'Our invitation';
const description = share.description || '';
const url = String(share.url || '').replace(/\/+$/, '');
const image = absolute(url, share.image || 'assets/img/og.png');

const meta = `<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="canonical" href="${esc(url)}">
<meta name="theme-color" content="${esc(theme.paper || '#FAF4EA')}">

<meta property="og:type" content="website">
<meta property="og:site_name" content="${esc(couple.joined || title)}">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:url" content="${esc(url)}">
<meta property="og:image" content="${esc(image)}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="${esc(title)}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(title)}">
<meta name="twitter:description" content="${esc(description)}">
<meta name="twitter:image" content="${esc(image)}">`;

const indexPath = join(ROOT, 'index.html');
const html = await readFile(indexPath, 'utf8');
await writeFile(indexPath, replaceBlock(html, 'META', meta));

/* Favicon: the two initials, so the browser tab reads as yours. */
const initials = `${couple.one?.initial || ''}${couple.two?.initial || ''}`;
const favicon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" rx="10" fill="${theme.paper || '#FAF4EA'}"/>
  <text x="32" y="43" text-anchor="middle" font-family="Georgia, serif" font-size="30"
        fill="${theme.accent || '#C2452D'}">${esc(initials)}</text>
</svg>
`;
await writeFile(join(ROOT, 'assets', 'img', 'favicon.svg'), favicon);

console.log(`✓ meta synced   ${title}`);
console.log(`  canonical     ${url || '(not set)'}`);
console.log(`  og:image      ${image}`);
