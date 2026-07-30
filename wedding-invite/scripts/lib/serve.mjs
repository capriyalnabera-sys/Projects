import http from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { join, extname, normalize } from 'node:path';
import { ROOT } from './content.mjs';

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.mp4': 'video/mp4',
};

/** Dependency-free static server for local preview and screenshots. */
export function serve(port = 0, host = '127.0.0.1') {
  const server = http.createServer(async (req, res) => {
    const urlPath = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    // normalize + strip leading separators so '../' can't escape ROOT
    let rel = normalize(urlPath).replace(/^([/\\]|\.\.[/\\])+/, '');
    if (rel === '' || rel.endsWith('/')) rel = join(rel, 'index.html');

    const file = join(ROOT, rel);
    try {
      const info = await stat(file);
      if (info.isDirectory()) throw new Error('directory');
      res.writeHead(200, {
        'Content-Type': TYPES[extname(file).toLowerCase()] || 'application/octet-stream',
        'Content-Length': info.size,
        'Cache-Control': 'no-cache',
      });
      createReadStream(file).pipe(res);
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found: ' + rel);
    }
  });

  return new Promise((resolve) => {
    server.listen(port, host, () => {
      resolve({ server, url: `http://127.0.0.1:${server.address().port}` });
    });
  });
}
