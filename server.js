/**
 * Wedding_AP - server
 *
 * Two surfaces:
 *   1. The planning tracker  (/, /api/*)      -> password protected
 *   2. The guest invite site (/i/:token, /public/*) -> open to invited guests
 */
const express = require('express');
const cors = require('cors');
const path = require('path');
const crypto = require('crypto');
const db = require('./db');

const app = express();
const PORT = process.env.PORT || 3000;

// Password to open the planner. Set ADMIN_PASSWORD in the environment for real use.
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'wedding';
const SECRET = process.env.SESSION_SECRET || `wap-secret-${ADMIN_PASSWORD}`;
const AUTH_COOKIE = crypto.createHmac('sha256', SECRET).update('authenticated').digest('hex');

app.use(cors());
app.use(express.json());

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
  if (cookies.wap_auth === AUTH_COOKIE) return next();
  if (req.path.startsWith('/api')) return res.status(401).json({ error: 'Authentication required' });
  return res.redirect('/login');
}

// ---------------------------------------------------------------------------
// OPEN routes (no auth)
// ---------------------------------------------------------------------------

// Login page + auth
app.get('/login', (req, res) => res.sendFile(path.join(__dirname, 'public', 'login.html')));

app.post('/api/login', (req, res) => {
  if ((req.body.password || '') === ADMIN_PASSWORD) {
    res.setHeader('Set-Cookie',
      `wap_auth=${AUTH_COOKIE}; HttpOnly; Path=/; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`);
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
