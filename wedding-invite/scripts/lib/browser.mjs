import { execSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

/**
 * Load Playwright from the project, or fall back to a global install.
 * Keeps `npm run og` working on a machine where playwright is installed
 * globally rather than as a devDependency.
 */
export async function getChromium() {
  try {
    const pw = await import('playwright');
    return pw.chromium;
  } catch { /* fall through */ }

  try {
    const globalRoot = execSync('npm root -g', { encoding: 'utf8' }).trim();
    const pw = await import(pathToFileURL(join(globalRoot, 'playwright', 'index.js')).href);
    return (pw.default ?? pw).chromium;
  } catch { /* fall through */ }

  throw new Error(
    'Playwright is not installed.\n' +
    'Run:  npm install\n' +
    '(Chromium itself is usually already present; if not: npx playwright install chromium)'
  );
}
