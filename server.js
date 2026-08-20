/**
 * Wedding_AP - server
 *
 * Two surfaces:
 *   1. The planning tracker  (/, /api/*)      -> password protected
 *   2. The guest invite site (/i/:token, /public/*) -> open to invited guests
 */
const express = require('express');
const path = require('path');
const crypto = require('crypto');
const db = require('./db');

const app = express();
const PORT = process.env.PORT || 3000;

// Password to open the planner. Set ADMIN_PASSWORD in the environment for real use.
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'wedding';
// A random secret when none is set makes the login cookie unforgeable out of the box
// (logins reset on restart until you set a stable SESSION_SECRET).
const SECRET = process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex');
const AUTH_COOKIE = crypto.createHmac('sha256', SECRET).update('authenticated').digest('hex');
if (!process.env.ADMIN_PASSWORD) console.warn('  ⚠  ADMIN_PASSWORD not set — using default "wedding". Set it before sharing.');
if (!process.env.SESSION_SECRET) console.warn('  ⚠  SESSION_SECRET not set — using a random per-boot secret (logins reset on restart).');

function safeEqual(a, b) {
  const ba = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ba.length === bb.length && crypto.timingSafeEqual(ba, bb);
}

app.use(express.json());
app.use((req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'SAMEORIGIN');
  res.setHeader('Referrer-Policy', 'no-referrer');
  next();
});

function parseCookies(req) {
  const out = {};
  (req.headers.cookie || '').split(';').forEach(pair => {
    const idx = pair.indexOf('=');
    if (idx > -1) out[pair.slice(0, idx).trim()] = decodeURIComponent(pair.slice(idx + 1).trim());
  });
  return out;
}

function requireAuth(req, res, next) {
  const cookies = parseCookies(req);
  if (cookies.wap_auth && safeEqual(cookies.wap_auth, AUTH_COOKIE)) return next();
  if (req.path.startsWith('/api')) return res.status(401).json({ error: 'Authentication required' });
  return res.redirect('/login');
}

// ---------------------------------------------------------------------------
// OPEN routes (no auth)
// ---------------------------------------------------------------------------

// Login page + auth
app.get('/login', (req, res) => res.sendFile(path.join(__dirname, 'public', 'login.html')));
// The login page needs its stylesheet, which is otherwise behind auth.
app.get('/styles.css', (req, res) => res.sendFile(path.join(__dirname, 'public', 'styles.css')));

app.post('/api/login', (req, res) => {
  if (safeEqual(req.body.password || '', ADMIN_PASSWORD)) {
    const secure = (req.headers['x-forwarded-proto'] || req.protocol) === 'https' ? ' Secure;' : '';
    res.setHeader('Set-Cookie',
      `wap_auth=${AUTH_COOKIE}; HttpOnly;${secure} Path=/; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`);
    return res.json({ ok: true });
  }
  res.status(401).json({ ok: false, error: 'Incorrect password' });
});

app.post('/api/logout', (req, res) => {
  res.setHeader('Set-Cookie', 'wap_auth=; HttpOnly; Path=/; Max-Age=0');
  res.json({ ok: true });
});

// Guest invite site
app.get('/i/:token', (req, res) => res.sendFile(path.join(__dirname, 'invite', 'invite.html')));

app.get('/public/invite/:token', (req, res) => {
  const data = db.getInviteData(req.params.token);
  if (!data) return res.status(404).json({ error: 'Invite not found' });
  res.json(data);
});

app.post('/public/rsvp/:token', (req, res) => {
  const data = db.submitRsvp(req.params.token, req.body || {});
  if (!data) return res.status(404).json({ error: 'Invite not found' });
  res.json({ ok: true, data });
});

// ---------------------------------------------------------------------------
// PROTECTED routes (planner)
// ---------------------------------------------------------------------------
app.use(requireAuth);
app.use('/api', require('./routes/api'));
app.use(express.static(path.join(__dirname, 'public')));
app.get('*', (req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));

db.getDb().then(() => {
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`\n  💍  Wedding_AP planner running at http://localhost:${PORT}`);
    console.log(`  🔐  Planner password: "${ADMIN_PASSWORD}" (set ADMIN_PASSWORD to change)`);
    console.log(`  💌  Guest invites:    http://localhost:${PORT}/i/<token>\n`);
  });
}).catch(err => { console.error('Failed to start:', err); process.exit(1); });
