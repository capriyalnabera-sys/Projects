import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/** Evaluate assets/js/content.js and hand back the INVITE object. */
export async function loadContent() {
  const src = await readFile(join(ROOT, 'assets', 'js', 'content.js'), 'utf8');
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: 'content.js' });

  const invite = sandbox.window.INVITE;
  if (!invite) throw new Error('content.js did not set window.INVITE');
  return invite;
}

/** Minimal HTML-attribute escaping for values we inject into <meta>. */
export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Join the site URL and a relative asset path into an absolute URL. */
export function absolute(baseUrl, path) {
  const base = String(baseUrl || '').replace(/\/+$/, '');
  const rel = String(path || '').replace(/^\/+/, '');
  if (/^https?:\/\//i.test(path)) return path;
  return base + '/' + rel;
}

/** Swap the text between two HTML comment markers. */
export function replaceBlock(html, name, replacement) {
  const start = `<!-- INVITE:${name}:START`;
  const end = `<!-- INVITE:${name}:END -->`;

  const startIdx = html.indexOf(start);
  const endIdx = html.indexOf(end);
  if (startIdx === -1 || endIdx === -1) {
    throw new Error(`Could not find the INVITE:${name} markers in index.html`);
  }

  const startTagEnd = html.indexOf('-->', startIdx) + 3;
  return html.slice(0, startTagEnd) + '\n' + replacement + '\n' + html.slice(endIdx);
}
