#!/usr/bin/env node
'use strict';
/* Agent HQ Server – statisches Dashboard + Mission-Control-API.
   Aufruf:  node dashboard/server.js [port]
   Läuft lokal (Windows, Git-Bash vorhanden) und am Plesk-Server (bash nativ). */
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const BASE = path.resolve(__dirname, '..');
const WEB = __dirname;
const PORT = parseInt(process.env.PORT || process.argv[2] || '8788', 10);
/* Als Service hinter Plesk-Reverse-Proxy nur auf localhost lauschen (nicht welt-offen).
   HOST=0.0.0.0 nur, wenn du bewusst direkt exponierst. */
const HOST = process.env.HOST || '127.0.0.1';

/* ---------- Basic-Auth (schuetzt das Dashboard hinter dem Reverse-Proxy) ----------
   Aktiv, sobald HQ_USER und HQ_PASS in der Umgebung gesetzt sind. Ohne sie ist der
   Server offen (nur fuer lokale Entwicklung gedacht). Der signierte Discord-Endpoint
   ist ausgenommen (verifiziert selbst per ed25519). */
const HQ_USER = process.env.HQ_USER || '';
const HQ_PASS = process.env.HQ_PASS || '';
const HQ_OPEN = process.env.HQ_OPEN === '1';             // NUR lokal: API bewusst ohne Auth erlauben
if ((!HQ_USER || !HQ_PASS) && !HQ_OPEN)
  console.warn('!! HQ_USER/HQ_PASS nicht gesetzt -> /api ist GESPERRT (401). Fuer offenen lokalen Betrieb: HQ_OPEN=1.');
function safeEq(a, b) {
  const A = Buffer.from(String(a)), B = Buffer.from(String(b));
  return A.length === B.length && crypto.timingSafeEqual(A, B);
}
function authOK(req) {
  // Fail-closed: ohne Credentials ist die API ZU (401), ausser HQ_OPEN=1 oeffnet sie
  // absichtlich (lokale Entwicklung). Verhindert versehentlich offene /api hinter dem Proxy.
  if (!HQ_USER || !HQ_PASS) return HQ_OPEN;
  const m = /^Basic\s+(.+)$/i.exec(req.headers['authorization'] || '');
  if (!m) return false;
  let dec = ''; try { dec = Buffer.from(m[1], 'base64').toString('utf8'); } catch (e) { return false; }
  const i = dec.indexOf(':'); if (i < 0) return false;
  return safeEq(dec.slice(0, i), HQ_USER) && safeEq(dec.slice(i + 1), HQ_PASS);
}

const AGENTS = {
  'master': 'Nutze den Subagent kommandant: verschaffe dir den Gesamtüberblick über alle Agents (dashboard/status.json), stimme den Zeitplan (config/schedule.json) ab und stoße fällige Läufe an. Nichts nach außen senden.',
  'wochenreport': 'Nutze den Subagent wochenreport und erstelle den Wochenreport für die abgelaufene Woche.',
  'belege-buchhaltung': 'Nutze den Subagent belege-buchhaltung und verarbeite alle neuen Belege in belege/inbox/.',
  'content-recherche': 'Nutze den Subagent content-recherche und erstelle den Contentplan für die kommende Woche.',
  'uptime-waechter': 'Nutze den Subagent uptime-waechter und prüfe jetzt alle Sites aus config/sites.json.',
  'website-guardian': 'Nutze den Subagent website-guardian und mach den wöchentlichen Tiefen-Check aller Sites aus config/sites.json.',
  'seo-audit': 'Nutze den Subagent seo-audit und auditiere alle Sites aus config/sites.json.',
  'backup-auditor': 'Nutze den Subagent backup-auditor und prüfe die Backups aus config/backups.json (read-only, kein Restore ohne Go).',
  'rechnungssteller': 'Nutze den Subagent rechnungssteller. Falls keine Positionen genannt sind, frage nach, statt zu raten.',
  'server-waechter': 'Nutze den Subagent server-waechter und prüfe jetzt READ-ONLY die Server-Gesundheit (config/server.json). Nichts ändern, nur melden.',
  'mail-assistent': 'Nutze den Subagent mail-assistent und triagiere den Gmail-Posteingang: sortieren, zusammenfassen, Antwort-Entwürfe anlegen. Nichts versenden.',
  'video-producent': 'Nutze den Subagent video-producent und erzeuge EIN Kurzvideo (9:16) aus der obersten offenen Content-Idee und liefere es mit Caption nach #content. Nicht selbst auf Social posten.',
  'ki-influencer': 'Nutze den Subagent ki-influencer und erzeuge EINEN on-brand Tages-Post (Bild + 9:16-Clip + Caption) aus config/influencer.json und liefere ihn nach #content. Nicht selbst auf Social posten.'
};
/* Report-Wurzeln: nur diese Ordner sind über /api lesbar */
const REPORT_ROOTS = ['reports', 'content', 'belege', 'uptime', 'guardian', 'seo', 'rechnungen', 'server', 'backup', 'mail', 'video', 'influencer'];
const REPORT_EXT = new Set(['.md', '.html', '.pdf', '.csv', '.txt', '.json']);
const MIME = {
  '.html': 'text/html; charset=utf-8', '.md': 'text/plain; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8', '.csv': 'text/plain; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.pdf': 'application/pdf',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp',
  '.svg': 'image/svg+xml', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.ico': 'image/x-icon'
};

function send(res, code, body, type) {
  res.writeHead(code, { 'Content-Type': type || 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

/* Atomar + eindeutiger Tmp-Name (parallele Schreiber kollidieren sonst auf *.tmp). */
function writeJsonAtomic(f, obj, spaces) {
  const tmp = f + '.tmp.' + process.pid + '.' + Math.floor(Math.random() * 1e9);
  try { fs.writeFileSync(tmp, JSON.stringify(obj, null, spaces || 0)); fs.renameSync(tmp, f); }
  catch (e) { try { fs.unlinkSync(tmp); } catch (_) {} throw e; }
}
/* Prozessübergreifender Lock – IDENTISCH zu bin/hq.js, damit Scheduler + Agent-CLIs
   sich denselben "<datei>.lock" teilen und der Read-Modify-Write auf status.json
   gegenseitig ausschließt (behebt den Lost-Update-Race). */
function sleepSync(ms) {
  try { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }
  catch (_) { const t = Date.now() + ms; while (Date.now() < t) {} }
}
function withFileLock(target, fn) {
  const lock = target + '.lock', start = Date.now();
  let held = false;
  while (!held) {
    try { fs.closeSync(fs.openSync(lock, 'wx')); held = true; break; }
    catch (e) {
      if (e.code !== 'EEXIST') break;
      try { if (Date.now() - fs.statSync(lock).mtimeMs > 15000) { fs.unlinkSync(lock); continue; } } catch (_) {}
      if (Date.now() - start > 5000) break;
      sleepSync(15 + Math.floor(Math.random() * 40));
    }
  }
  try { return fn(); }
  finally { if (held) { try { fs.unlinkSync(lock); } catch (_) {} } }
}
function statusPath() {
  const h = path.join(BASE, 'httpdocs', 'status.json');
  return fs.existsSync(h) ? h : path.join(WEB, 'status.json');
}
function readStatus() {
  try { return JSON.parse(fs.readFileSync(statusPath(), 'utf8')); } catch (e) { return { agents: {} }; }
}

function findBash() {
  if (process.platform !== 'win32') return 'bash';
  for (const p of ['C:\\Program Files\\Git\\bin\\bash.exe', 'C:\\Program Files (x86)\\Git\\bin\\bash.exe']) {
    if (fs.existsSync(p)) return p;
  }
  return 'bash'; // PATH-Versuch
}

function runAgent(id, prompt) {
  const script = path.join(BASE, 'bin', 'run-agent.sh');
  const log = fs.openSync(path.join(BASE, 'logs', id + '.server.log'), 'a');
  const child = spawn(findBash(), [script, id, prompt || AGENTS[id]], {
    cwd: BASE, detached: true, stdio: ['ignore', log, log],
    // Node-Pfad mitgeben, damit run-agent.sh die Kern-Logik ohne Python fahren kann
    env: Object.assign({}, process.env, { HQ_NODE: process.execPath })
  });
  child.unref();
  try { fs.closeSync(log); } catch (e) {}   // Kind hat eigene FD-Kopie -> FD-Leak im Server vermeiden
  return child.pid;
}

/* rel-Pfad gegen erlaubte Wurzeln prüfen; gibt absoluten Pfad oder null */
function safeFile(rel) {
  if (!rel) return null;
  const abs = path.resolve(BASE, rel);
  for (const root of REPORT_ROOTS) {
    const r = path.resolve(BASE, root) + path.sep;
    if (abs.startsWith(r) && fs.existsSync(abs) && fs.statSync(abs).isFile()) return abs;
  }
  return null;
}

function listReports() {
  const out = [];
  const walk = (dir, root, depth) => {
    if (depth > 4) return;
    let entries; try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return; }
    for (const e of entries) {
      if (e.name.startsWith('.')) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== 'inbox') walk(p, root, depth + 1); continue; }
      if (!REPORT_EXT.has(path.extname(e.name).toLowerCase())) continue;
      const st = fs.statSync(p);
      out.push({ name: e.name, rel: path.relative(BASE, p).split(path.sep).join('/'), root, mtime: st.mtimeMs, size: st.size });
    }
  };
  for (const root of REPORT_ROOTS) walk(path.join(BASE, root), root, 0);
  out.sort((a, b) => b.mtime - a.mtime);
  return out.slice(0, 200);
}

function tailLog(id) {
  const f = path.join(BASE, 'logs', id + '.log');
  try {
    const st = fs.statSync(f);
    const size = Math.min(st.size, 32 * 1024);
    const fd = fs.openSync(f, 'r');
    const buf = Buffer.alloc(size);
    fs.readSync(fd, buf, 0, size, st.size - size);
    fs.closeSync(fd);
    return { exists: true, mtime: st.mtimeMs, text: buf.toString('utf8') };
  } catch (e) { return { exists: false, text: '(noch kein Log vorhanden)' }; }
}

/* Body einer POST-Anfrage als JSON lesen (Limit 1 MB); cb(obj|null) */
function readJson(req, cb) {
  let data = '', too = false;
  req.on('data', c => { data += c; if (data.length > 1e6) { too = true; req.destroy(); } });
  req.on('end', () => { if (too) return cb(null); if (!data) return cb({}); try { cb(JSON.parse(data)); } catch (e) { cb(null); } });
  req.on('error', () => cb(null));
}

const SCHEDULE_FILE = path.join(BASE, 'config', 'schedule.json');
let _schedWarned = false;
function readSchedule() {
  try { const s = JSON.parse(fs.readFileSync(SCHEDULE_FILE, 'utf8')); _schedWarned = false; return s; }
  catch (e) {
    // Korruptes schedule.json wuerde SONST lautlos ALLE Agents deaktivieren -> laut warnen (einmal).
    if (!_schedWarned) { _schedWarned = true; console.error('!! config/schedule.json unlesbar/korrupt (' + (e.message || e) + ') -> Scheduler pausiert alle Termine bis behoben.'); }
    return { agents: {} };
  }
}

/* ---------- Analytics-Proxy (Umami, server-seitig) ----------
   Login mit UMAMI_*-Credentials aus der Umgebung; Kennzahlen der letzten 7 Tage
   je Website + Vorwochenvergleich. Token (55 min) und Ergebnis (5 min) werden
   gecacht, damit der 30-Sekunden-Refresh des Dashboards Umami nicht flutet.
   Credentials verlassen den Server nie – der Browser sieht nur aggregierte Zahlen. */
const UMAMI = {
  base: (process.env.UMAMI_BASE_URL || '').replace(/\/+$/, ''),
  user: process.env.UMAMI_USERNAME || '',
  pass: process.env.UMAMI_PASSWORD || ''
};
let _umamiCache = {};                 // pro Zeitspanne gecacht: { <rangeKey>: { t, data } }
let _umamiTok = { t: 0, token: '' };
const RANGES = {
  '24h': { ms: 864e5, label: 'Last 24 hours' },
  '7d':  { ms: 7 * 864e5, label: 'Last 7 days' },
  '30d': { ms: 30 * 864e5, label: 'Last 30 days' }
};

function httpsJson(urlStr, { method = 'GET', headers = {}, body = null } = {}) {
  return new Promise((resolve, reject) => {
    let u; try { u = new URL(urlStr); } catch (e) { return reject(e); }
    const data = body ? JSON.stringify(body) : null;
    const opt = {
      method, hostname: u.hostname, port: u.port || 443, path: u.pathname + u.search,
      headers: Object.assign({ 'Accept': 'application/json' }, headers)
    };
    if (data) { opt.headers['Content-Type'] = 'application/json'; opt.headers['Content-Length'] = Buffer.byteLength(data); }
    const req = https.request(opt, r => {
      const chunks = [];
      r.on('data', c => chunks.push(c));
      r.on('end', () => {
        const txt = Buffer.concat(chunks).toString('utf8');
        if (r.statusCode >= 400) return reject(new Error('HTTP ' + r.statusCode + ': ' + txt.slice(0, 160)));
        try { resolve(txt ? JSON.parse(txt) : {}); } catch (e) { reject(new Error('kein JSON von ' + u.pathname)); }
      });
    });
    req.on('error', reject);
    req.setTimeout(9000, () => req.destroy(new Error('timeout')));
    if (data) req.write(data);
    req.end();
  });
}
const numv = x => (x && typeof x === 'object') ? (+x.value || 0) : (+x || 0);
const UMAMI_TZ = process.env.UMAMI_TIMEZONE || 'Europe/Berlin';
const BREAKDOWNS = [
  { key: 'pages',     type: 'url' },
  { key: 'referrers', type: 'referrer' },
  { key: 'browsers',  type: 'browser' },
  { key: 'os',        type: 'os' },
  { key: 'devices',   type: 'device' },
  { key: 'countries', type: 'country' }
];
async function umamiToken() {
  if (_umamiTok.token && Date.now() - _umamiTok.t < 55 * 60 * 1000) return _umamiTok.token;
  const j = await httpsJson(UMAMI.base + '/api/auth/login', { method: 'POST', body: { username: UMAMI.user, password: UMAMI.pass } });
  const tok = j.token || (j.data && j.data.token);
  if (!tok) throw new Error('Login ohne Token');
  _umamiTok = { t: Date.now(), token: tok };
  return tok;
}
// tolerant gegenueber v1/v2-Antwortformen ([{x,y}] oder {data:[...]})
const asRows = r => Array.isArray(r) ? r : (r && Array.isArray(r.data) ? r.data : []);
// summiert value->count in eine Map (verschmilzt gleiche Labels ueber mehrere Sites)
function mergeInto(map, rows) {
  for (const row of asRows(rows)) {
    const x = row.x, y = +row.y || 0;
    if (x == null) continue;
    map.set(x, (map.get(x) || 0) + y);
  }
}
const topN = (map, n) => [...map.entries()]
  .map(([x, y]) => ({ x, y })).filter(r => r.y > 0)
  .sort((a, b) => b.y - a.y).slice(0, n);

async function umamiSummary(cacheKey, fromMs, toMs, label) {
  const cached = _umamiCache[cacheKey];
  if (cached && Date.now() - cached.t < 5 * 60 * 1000) return cached.data;
  const token = await umamiToken();
  const H = { Authorization: 'Bearer ' + token };
  const raw = await httpsJson(UMAMI.base + '/api/websites', { headers: H });
  const list = Array.isArray(raw) ? raw : (raw.data || raw.websites || []);
  const win = toMs - fromMs;
  const unit = win <= 2 * 864e5 ? 'hour' : (win <= 90 * 864e5 ? 'day' : 'month');
  const get = url => httpsJson(url, { headers: H }).catch(() => null);
  const B = UMAMI.base;

  // Zeitreihe (pageviews/sessions) ueber alle Sites nach Zeit-Bucket verschmelzen
  const tsMap = new Map();  // bucket -> { pageviews, sessions }
  const brk = {};           // key -> Map(label -> count)
  BREAKDOWNS.forEach(b => brk[b.key] = new Map());

  const perSite = await Promise.all(list.map(async w => {
    const id = w.id || w.websiteId; if (!id) return null;
    const stats = (a, b) => `${B}/api/websites/${id}/stats?startAt=${a}&endAt=${b}`;
    const pvUrl = `${B}/api/websites/${id}/pageviews?startAt=${fromMs}&endAt=${toMs}&unit=${unit}&timezone=${encodeURIComponent(UMAMI_TZ)}`;
    const mUrl = t => `${B}/api/websites/${id}/metrics?startAt=${fromMs}&endAt=${toMs}&type=${t}&limit=20`;
    const [cur, prev, pvSeries, ...mets] = await Promise.all([
      get(stats(fromMs, toMs)), get(stats(fromMs - win, fromMs)), get(pvUrl),
      ...BREAKDOWNS.map(b => get(mUrl(b.type)))
    ]);
    // Zeitreihe einmischen
    if (pvSeries) {
      const pvArr = asRows(pvSeries.pageviews), seArr = asRows(pvSeries.sessions);
      for (const r of pvArr) { const k = r.x; if (k == null) continue; const e = tsMap.get(k) || { pageviews: 0, sessions: 0 }; e.pageviews += +r.y || 0; tsMap.set(k, e); }
      for (const r of seArr) { const k = r.x; if (k == null) continue; const e = tsMap.get(k) || { pageviews: 0, sessions: 0 }; e.sessions += +r.y || 0; tsMap.set(k, e); }
    }
    // Breakdowns einmischen
    BREAKDOWNS.forEach((b, i) => mergeInto(brk[b.key], mets[i]));
    const c = cur || {}, p = prev || {};
    const pv = numv(c.pageviews), vs = numv(c.visitors);
    const pvp = numv(p.pageviews) || numv(c.pageviews && c.pageviews.prev);
    const vsp = numv(p.visitors) || numv(c.visitors && c.visitors.prev);
    const visits = numv(c.visits), bounces = numv(c.bounces), totaltime = numv(c.totaltime);
    const pct = (a, b) => b ? Math.round((a - b) / b * 100) : null;
    return {
      name: w.name || w.domain || String(id), domain: w.domain || '',
      pageviews: pv, visitors: vs, visits, bounces, totaltime,
      avg_seconds: visits ? Math.round(totaltime / visits) : 0,
      bounce_rate: visits ? Math.round(bounces / visits * 100) : 0,
      prev: { pageviews: pvp, visitors: vsp },
      change: { pageviews: pct(pv, pvp), visitors: pct(vs, vsp) }
    };
  }));
  const out = perSite.filter(Boolean).sort((a, b) => b.pageviews - a.pageviews);

  const series = [...tsMap.entries()]
    .map(([date, v]) => ({ date, pageviews: v.pageviews, sessions: v.sessions }))
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const breakdowns = {};
  BREAKDOWNS.forEach(b => breakdowns[b.key] = topN(brk[b.key], 10));

  const sum = f => out.reduce((s, x) => s + f(x), 0);
  const totVisits = sum(x => x.visits), totTime = sum(x => x.totaltime), totBounce = sum(x => x.bounces);
  const data = {
    configured: true, generated: new Date().toISOString(), range: label, unit,
    from: fromMs, to: toMs,
    total: {
      pageviews: sum(x => x.pageviews), visitors: sum(x => x.visitors), visits: totVisits,
      avg_seconds: totVisits ? Math.round(totTime / totVisits) : 0,
      bounce_rate: totVisits ? Math.round(totBounce / totVisits * 100) : 0,
      views_per_visit: totVisits ? +(sum(x => x.pageviews) / totVisits).toFixed(1) : 0
    },
    series, breakdowns, sites: out
  };
  _umamiCache[cacheKey] = { t: Date.now(), data };
  return data;
}

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = u.pathname;

  /* Basic-Auth-Gate (der signierte Discord-Endpoint ist ausgenommen) */
  if (p !== '/discord/interactions' && !authOK(req)) {
    res.writeHead(401, { 'WWW-Authenticate': 'Basic realm="Agent HQ", charset="UTF-8"', 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' });
    return res.end('Authentication required');
  }

  /* ---------- API ---------- */
  if (p === '/api/ping') return send(res, 200, { api: true, agents: Object.keys(AGENTS) });

  /* Discord Slash-Commands: signierter Interactions-Endpoint (Roh-Body noetig fuer ed25519) */
  if (p === '/discord/interactions' && req.method === 'POST') {
    let raw = '', too = false;
    req.on('data', c => { raw += c; if (raw.length > 1e6) { too = true; req.destroy(); } });
    req.on('end', () => { if (!too) handleInteraction(req, res, raw); });
    req.on('error', () => { try { res.writeHead(400); res.end(); } catch (e) {} });
    return;
  }

  if (p.startsWith('/api/run/') && req.method === 'POST') {
    const id = p.slice(9);
    if (!AGENTS[id]) return send(res, 404, { error: 'unbekannter agent' });
    const st = readStatus();
    if (st.agents && st.agents[id] && st.agents[id].status === 'running')
      return send(res, 409, { error: 'läuft bereits' });
    return readJson(req, body => {
      const prompt = body && typeof body.prompt === 'string' && body.prompt.trim() ? body.prompt.slice(0, 4000) : null;
      try {
        const pid = runAgent(id, prompt);
        return send(res, 200, { ok: true, pid });
      } catch (e) { return send(res, 500, { error: String(e.message || e) }); }
    });
  }

  /* Zeitplan lesen / speichern (config/schedule.json) */
  if (p === '/api/schedule') {
    if (req.method === 'GET') return send(res, 200, readSchedule());
    if (req.method === 'POST') return readJson(req, body => {
      if (!body || typeof body !== 'object' || !body.agents) return send(res, 400, { error: 'agents fehlt' });
      const cur = readSchedule(); cur.agents = cur.agents || {};
      for (const [id, patch] of Object.entries(body.agents)) {
        if (!AGENTS[id] || id === 'master' || !patch || typeof patch !== 'object') continue;
        const next = Object.assign({}, cur.agents[id]);
        next.enabled = patch.enabled !== false;
        if (typeof patch.cadence === 'string') next.cadence = patch.cadence.slice(0, 40);
        if (typeof patch.schwer === 'boolean') next.schwer = patch.schwer;
        if (typeof patch.quiet === 'boolean') next.quiet = patch.quiet;
        if (typeof patch.channel === 'string') {
          const ch = patch.channel.trim().slice(0, 40);
          if (ch) next.channel = ch; else delete next.channel;
        }
        cur.agents[id] = next;
      }
      try {
        writeJsonAtomic(SCHEDULE_FILE, cur, 2);
        return send(res, 200, { ok: true, schedule: cur });
      } catch (e) { return send(res, 500, { error: String(e.message || e) }); }
    });
    return send(res, 405, { error: 'methode nicht erlaubt' });
  }

  if (p.startsWith('/api/log/')) {
    const id = p.slice(9);
    if (!AGENTS[id]) return send(res, 404, { error: 'unbekannter agent' });
    return send(res, 200, tailLog(id));
  }

  /* Lauf-Historie (Report-Datensätze) eines Agents – neueste zuerst */
  if (p.startsWith('/api/runs/')) {
    const id = p.slice(10);
    if (!AGENTS[id]) return send(res, 404, { error: 'unbekannter agent' });
    const f = path.join(BASE, 'logs', id + '.jsonl');
    let runs = [];
    try {
      runs = fs.readFileSync(f, 'utf8').split('\n').filter(Boolean)
        .slice(-100).map(l => { try { return JSON.parse(l); } catch (e) { return null; } })
        .filter(Boolean).reverse();
    } catch (e) {}
    return send(res, 200, runs);
  }

  /* Volltext-Log eines EINZELNEN Laufs (logs/<id>/<run>.log) */
  if (p === '/api/runlog') {
    const id = u.searchParams.get('id'), run = u.searchParams.get('run') || '';
    if (!AGENTS[id] || !/^[0-9T]{8,20}$/.test(run)) return send(res, 404, { error: 'nicht gefunden' });
    const f = path.join(BASE, 'logs', id, run + '.log');
    try { return send(res, 200, { text: fs.readFileSync(f, 'utf8') }); }
    catch (e) { return send(res, 404, { error: 'nicht gefunden' }); }
  }

  if (p === '/api/reports') return send(res, 200, listReports());

  /* Website-Analytics (Umami) – server-seitig aggregiert, Credentials bleiben hier */
  if (p === '/api/analytics') {
    if (!UMAMI.base || !UMAMI.user || !UMAMI.pass)
      return send(res, 200, { configured: false, sites: [], reason: 'UMAMI_BASE_URL/USERNAME/PASSWORD nicht gesetzt' });
    const from = +u.searchParams.get('from'), to = +u.searchParams.get('to');
    let key, f, t, label;
    const fmtD = ms => new Date(ms).toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    if (from && to && to > from) {
      f = from; t = to; key = 'c' + from + '-' + to; label = fmtD(from) + ' – ' + fmtD(to);
    } else {
      const rk = RANGES[u.searchParams.get('range')] ? u.searchParams.get('range') : '7d';
      t = Date.now(); f = t - RANGES[rk].ms; key = rk; label = RANGES[rk].label;
    }
    return umamiSummary(key, f, t, label)
      .then(d => send(res, 200, d))
      .catch(e => send(res, 200, { configured: false, sites: [], error: String(e.message || e) }));
  }

  if (p === '/api/file') {
    const abs = safeFile(u.searchParams.get('p'));
    if (!abs) return send(res, 404, { error: 'nicht gefunden' });
    const type = MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream';
    return send(res, 200, fs.readFileSync(abs), type);
  }

  /* ---------- statisch ---------- */
  let rel = p === '/' ? '/index.html' : p;
  if (rel === '/status.json') return send(res, 200, fs.readFileSync(statusPath()), MIME['.json']);
  if (rel === '/uptime.json') {
    const f = path.join(BASE, 'uptime', 'uptime.json');
    try { return send(res, 200, fs.readFileSync(f), MIME['.json']); } catch (e) { return send(res, 200, { sites: [], history: [] }); }
  }
  if (rel === '/server.json') {
    const f = path.join(BASE, 'server', 'server-status.json');
    try { return send(res, 200, fs.readFileSync(f), MIME['.json']); } catch (e) { return send(res, 200, {}); }
  }
  if (rel === '/server-history.json') {
    const f = path.join(BASE, 'server', 'server-history.json');
    try { return send(res, 200, fs.readFileSync(f), MIME['.json']); } catch (e) { return send(res, 200, []); }
  }
  const abs = path.resolve(WEB, '.' + rel);
  if (abs.startsWith(WEB) && fs.existsSync(abs) && fs.statSync(abs).isFile())
    return send(res, 200, fs.readFileSync(abs), MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream');
  /* SPA-Fallback: unbekannte GET-Route ohne Dateiendung (z. B. /agents, /systems) -> index.html */
  if (req.method === 'GET' && !path.extname(p))
    return send(res, 200, fs.readFileSync(path.join(WEB, 'index.html')), MIME['.html']);
  return send(res, 404, 'not found', 'text/plain');
});

fs.mkdirSync(path.join(BASE, 'logs'), { recursive: true });

/* ---------- Discord-Bridge (Discord -> HQ) ----------
   Pollt den Kommando-Kanal, mappt deine Nachrichten auf Agent-Läufe und antwortet.
   Reine Wiederverwendung von bin/discord.py (stdlib) – kein Websocket, keine Deps. */
const DPY = path.join(BASE, 'bin', 'discord.py');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const D = {
  token: process.env.DISCORD_BOT_TOKEN || '',
  guild: process.env.DISCORD_GUILD_ID || '',
  cmd: process.env.DISCORD_COMMAND_CHANNEL || 'freigaben',
  log: process.env.DISCORD_LOG_CHANNEL || 'agent-logs',
  poll: Math.max(5, parseInt(process.env.DISCORD_POLL_SECONDS || '12', 10)),
  on: (process.env.DISCORD_BRIDGE || 'on') !== 'off'
};
const DSTATE = path.join(WEB, '.discord-last.json');
function dLastId() { try { return JSON.parse(fs.readFileSync(DSTATE, 'utf8')).id || null; } catch (e) { return null; } }
function dSetLast(id) { try { fs.writeFileSync(DSTATE, JSON.stringify({ id })); } catch (e) {} }
function dpy(args, cb) {
  const out = [], err = [];
  const c = spawn(PY, [DPY, ...args], { cwd: BASE, env: process.env });
  c.stdout.on('data', d => out.push(d));
  c.stderr.on('data', d => err.push(d));
  c.on('close', code => cb(code, Buffer.concat(out).toString('utf8'), Buffer.concat(err).toString('utf8')));
  c.on('error', e => cb(-1, '', String(e)));
}
function dpost(chan, text) { dpy(['post', chan, text], () => {}); }

const D_HELP = [
  '🤖 **HQ** – am besten die **Slash-Commands**: `/status` `/offen` `/run` `/ja` `/nein` `/go` `/master`.',
  'Hier als Text geht auch: `status`, `offen`, `<agent>` starten, `go [agent]`, `<agent>: <auftrag>`,',
  'und eine **Frage mit `?`** bzw. `master …` (nur das kostet Tokens).'
].join('\n');

/* Aliase -> Agent-ID, damit lockere Formulierungen ohne LLM erkannt werden */
const ALIAS = {
  report: 'wochenreport', reports: 'wochenreport', wochenbericht: 'wochenreport', bericht: 'wochenreport',
  beleg: 'belege-buchhaltung', belege: 'belege-buchhaltung', buchhaltung: 'belege-buchhaltung',
  content: 'content-recherche', contentplan: 'content-recherche', recherche: 'content-recherche',
  uptime: 'uptime-waechter', erreichbarkeit: 'uptime-waechter', monitoring: 'uptime-waechter',
  guardian: 'website-guardian', website: 'website-guardian',
  backup: 'backup-auditor', backups: 'backup-auditor', sicherung: 'backup-auditor',
  seo: 'seo-audit', audit: 'seo-audit', rechnung: 'rechnungssteller', rechnungen: 'rechnungssteller',
  influencer: 'ki-influencer', persona: 'ki-influencer'
};
function matchAgent(s) {
  s = (s || '').toLowerCase().trim();
  if (AGENTS[s]) return s;
  if (ALIAS[s]) return ALIAS[s];
  for (const id of Object.keys(AGENTS)) { if (id !== 'master' && s === id.split('-')[0]) return id; }
  for (const [w, id] of Object.entries(ALIAS)) { if (new RegExp('\\b' + w + '\\b').test(s)) return id; }
  return null;
}
function dOpenText() {
  const a = readStatus().agents || {};
  const open = Object.keys(a).filter(k => a[k].status === 'waiting' || a[k].status === 'error');
  if (!open.length) return '✅ Nichts offen – keine Waits, keine Fehler.';
  const ic = { waiting: '🟡', error: '🔴' };
  return 'Offen:\n' + open.map(k => `${ic[a[k].status]} **${k}** – ${a[k].status}${a[k].message ? ': ' + a[k].message : ''}`).join('\n');
}

function dStatusText() {
  const a = readStatus().agents || {};
  const ic = { running: '🔵', ok: '🟢', done: '🟢', waiting: '🟡', error: '🔴' };
  const ks = Object.keys(a);
  if (!ks.length) return 'Noch keine Läufe verzeichnet.';
  return ks.map(k => `${ic[a[k].status] || '⚪'} **${k}** – ${a[k].status || '?'}${a[k].message ? ': ' + a[k].message : ''}`).join('\n');
}
function dRun(id, prompt) {
  if (!AGENTS[id]) return dpost(D.cmd, `❓ Kein Agent "${id}". Bekannt: ${Object.keys(AGENTS).join(', ')}`);
  const st = readStatus();
  if (st.agents && st.agents[id] && st.agents[id].status === 'running') return dpost(D.cmd, `⏳ **${id}** läuft schon.`);
  try { runAgent(id, prompt || null); dpost(D.cmd, `▶️ **${id}** gestartet${prompt ? ' (eigener Auftrag)' : ''}. Ich melde mich, wenn fertig.`); }
  catch (e) { dpost(D.cmd, `❌ Start fehlgeschlagen: ${e.message || e}`); }
}
function dGo(id) {
  const a = readStatus().agents || {};
  if (!id) id = Object.keys(a).find(k => a[k].status === 'waiting');
  if (!id) return dpost(D.cmd, 'Kein Agent wartet gerade auf Go. Nenne einen, z. B. `go wochenreport`.');
  dRun(id, 'Sebastian hat GO gegeben. Führe die freigegebene Aktion des letzten Laufs jetzt aus (z. B. die abgelegten Entwürfe versenden). Liegt nichts zum Versenden bereit, sag das kurz.');
}
/* Filter-Kaskade: erst alles Deterministische (kostenlos), Master (LLM) nur als letzte Stufe
   und nur bei echter Frage/Ansprache – so bleiben die Token-Kosten minimal. */
function dHandle(text) {
  text = (text || '').trim();
  if (!text) return;
  const low = text.toLowerCase();
  let m, id;

  // 1) Exakte Kommandos – kein LLM
  if (low === 'help' || low === 'hilfe' || low === '?') return dpost(D.cmd, D_HELP);
  if (low === 'agents' || low === 'agent') return dpost(D.cmd, 'Agents: ' + Object.keys(AGENTS).join(', '));
  if (m = low.match(/^(?:run|start|starte)\s+(.+)$/)) { id = matchAgent(m[1]); return id ? dRun(id) : dpost(D.cmd, `❓ Kein Agent zu "${m[1].trim()}".`); }
  if (m = low.match(/^go(?:\s+([a-z-]+))?$/)) return dGo(m[1] ? (matchAgent(m[1]) || m[1]) : null);
  if (m = text.match(/^([a-zäöü-]+)\s*:\s*([\s\S]+)/i)) { id = matchAgent(m[1]); if (id) return dRun(id, m[2].trim()); }
  if (id = (AGENTS[low] ? low : ALIAS[low])) return dRun(id);   // ganze Nachricht = Agentname/Alias

  // 2) Explizite Master-Ansprache -> LLM (höchste Priorität, schlägt Keyword-Intents)
  if (/^(master|hey master|kommandant)\b/i.test(low)) return dRunMaster(text);

  // 3) Deterministische Intents – kein LLM
  if (/^(danke|thx|thanks|merci|ok(ay)?|passt|super|top|läuft|👍|👌|🙏)[.! ]*$/i.test(low)) return;         // Bestätigung -> still
  if (/\b(status|lage|stand|überblick|uebersicht)\b/.test(low) || /^was\s+(läuft|geht|los)/.test(low)) return dpost(D.cmd, dStatusText());
  if (/\b(offen|wartet|warten|waits?|freigaben?|blockiert|hängt|fehler|errors?)\b/.test(low)) return dpost(D.cmd, dOpenText());
  if (/\b(start|starte|lauf|laufen|mach|run|feuer|los|erstell|erstelle|prüf|pruef|check)\b/.test(low)) { id = matchAgent(low); if (id) return dRun(id); }

  // 4) Offene Frage -> Master (LLM); alles andere -> billiger Hinweis, kein Token
  if (/\?\s*$/.test(text)) return dRunMaster(text);
  return dpost(D.cmd, 'Nicht als Kommando erkannt. `help`, `status` oder `offen` – oder stell dem Master eine **Frage mit `?`** bzw. beginne mit `master …`.');
}
function dRunMaster(text) {
  const st = readStatus();
  if (st.agents && st.agents.master && st.agents.master.status === 'running')
    return dpost(D.cmd, '⏳ Der Master arbeitet noch – ich melde mich gleich.');
  const prompt = `Nutze den Subagent kommandant. Sebastian schreibt dir via Discord (#${D.cmd}): "${text}". `
    + `Erledige es als Koordinator: lies dashboard/status.json und config/schedule.json, stoße bei Bedarf Läufe via bin/run-agent.sh an, `
    + `und antworte Sebastian knapp per bin/discord.py post ${D.cmd} "<antwort>". Nichts an Kunden senden.`;
  try { runAgent('master', prompt); dpost(D.cmd, '🧠 Verstanden – der Master schaut sich das an…'); }
  catch (e) { dpost(D.cmd, '❌ ' + (e.message || e)); }
}
let dBusy = false;
function dPoll() {
  if (dBusy) return; dBusy = true;
  const after = dLastId();
  const args = ['read', D.cmd, '--json', '--limit', '20'];
  if (after) args.push('--after', after);
  dpy(args, (code, out) => {
    dBusy = false;
    if (code !== 0) return;
    let msgs; try { msgs = JSON.parse(out || '[]'); } catch (e) { return; }
    if (!Array.isArray(msgs) || !msgs.length) return;
    let newest = after;
    for (const msg of msgs) {
      newest = msg.id;
      if (msg.bot) continue;      // eigene/andere Bot-Posts ignorieren
      if (!after) continue;       // Erststart: nur Basislinie setzen, History nicht abarbeiten
      dHandle(msg.content);
    }
    if (newest) dSetLast(newest);
  });
}
if (D.on && D.token && D.guild) {
  console.log(`Discord-Bridge aktiv: #${D.cmd} (Poll ${D.poll}s), Logs -> #${D.log}`);
  setInterval(dPoll, D.poll * 1000);
  dPoll();
} else {
  console.log('Discord-Bridge aus (DISCORD_BOT_TOKEN/GUILD_ID fehlt oder DISCORD_BRIDGE=off).');
}

/* ---------- Discord Slash-Commands (Interactions-Endpoint) ----------
   Native /-Kommandos. Discord POSTet signierte Interactions an /discord/interactions.
   Wir verifizieren die ed25519-Signatur mit DISCORD_PUBLIC_KEY (Dev-Portal) und antworten
   sofort (ephemeral, nur Sebastian sieht es). Registrierung: bin/discord-register.py. */
function verifyDiscord(raw, sig, ts, pubHex) {
  try {
    const der = Buffer.concat([Buffer.from('302a300506032b6570032100', 'hex'), Buffer.from(pubHex, 'hex')]);
    const key = crypto.createPublicKey({ key: der, format: 'der', type: 'spki' });
    return crypto.verify(null, Buffer.from(ts + raw), key, Buffer.from(sig, 'hex'));
  } catch (e) { return false; }
}
/* Agent-ID -> kurzer Slash-Wert (Auswahl im /-Menue, siehe discord-register.py) */
const CHOICE = {
  wochenreport: 'report', 'belege-buchhaltung': 'belege', 'content-recherche': 'content',
  'uptime-waechter': 'uptime', 'seo-audit': 'seo', rechnungssteller: 'rechnung',
  'server-waechter': 'server', 'mail-assistent': 'mail', 'video-producent': 'video',
  'ki-influencer': 'influencer'
};
const SLASH_HELP = [
  '🤖 **HQ-Slash-Commands**',
  '`/status` Ampel · `/offen` Waits/Fehler · `/agents` Liste',
  '`/run <agent>` starten · `/ja <agent>` fälligen Lauf freigeben · `/nein <agent>` überspringen',
  '`/go [agent]` Versand/Aktion freigeben · `/master <frage>` den Master fragen'
].join('\n');

/* Startet einen Agent, wenn er nicht schon läuft. Ergebnis-Meldung ist kurz. */
function startAgent(id, prompt) {
  if (!AGENTS[id]) return { ok: false, msg: `❓ Kein Agent "${id}".` };
  const st = readStatus();
  if (st.agents && st.agents[id] && st.agents[id].status === 'running') return { ok: false, msg: `⏳ ${id} läuft schon.` };
  try { runAgent(id, prompt || null); return { ok: true, msg: `▶️ ${id} gestartet.` }; }
  catch (e) { return { ok: false, msg: '❌ ' + (e.message || e) }; }
}
function startGo(id) {
  const a = readStatus().agents || {};
  if (!id) id = Object.keys(a).find(k => a[k].status === 'waiting');
  if (!id) return 'Kein Agent wartet gerade auf Go.';
  const r = startAgent(id, 'Sebastian hat GO gegeben. Führe die freigegebene Aktion des letzten Laufs jetzt aus (z. B. abgelegte Entwürfe versenden). Liegt nichts bereit, sag das kurz.');
  return r.ok ? `✅ Go für ${id} – führe die freigegebene Aktion aus.` : r.msg;
}
function startMaster(frage) {
  const st = readStatus();
  if (st.agents && st.agents.master && st.agents.master.status === 'running') return '⏳ Der Master arbeitet noch.';
  const prompt = `Nutze den Subagent kommandant. Sebastian fragt via Discord-Slash: "${frage}". `
    + `Antworte KNAPP (wenige Zeilen, kein Roman) per bin/discord.py post ${D.cmd} "<antwort>". `
    + `Bei Bedarf lies dashboard/status.json und config/schedule.json und stoße Läufe via bin/run-agent.sh an. Nichts an Kunden senden.`;
  try { runAgent('master', prompt); return '🧠 Master schaut sich das an – Antwort kommt in #' + D.cmd + '.'; }
  catch (e) { return '❌ ' + (e.message || e); }
}
function optVal(opts, name) { const o = (opts || []).find(o => o.name === name); return o ? o.value : null; }
function routeSlash(name, opts) {
  const eph = t => ({ content: t, ephemeral: true });
  const wantId = () => matchAgent(optVal(opts, 'agent') || '');
  switch (name) {
    case 'status': return eph(dStatusText());
    case 'offen':  return eph(dOpenText());
    case 'agents': return eph('Agents: ' + Object.keys(AGENTS).filter(k => k !== 'master').join(', '));
    case 'help':   return eph(SLASH_HELP);
    case 'run':
    case 'ja': { const id = wantId(); return eph(id ? startAgent(id).msg : '❓ Kein passender Agent.'); }
    case 'nein': { const id = wantId(); return eph(id ? `⏭️ ${id} diesmal übersprungen – ich frage wieder zum nächsten Termin.` : '❓ Kein passender Agent.'); }
    case 'go':     return eph(startGo(optVal(opts, 'agent') ? wantId() : null));
    case 'master': return eph(startMaster(optVal(opts, 'frage') || ''));
    default:       return eph('Unbekanntes Kommando.');
  }
}
function handleInteraction(req, res, raw) {
  const pub = process.env.DISCORD_PUBLIC_KEY || '';
  const sig = req.headers['x-signature-ed25519'], ts = req.headers['x-signature-timestamp'];
  if (!pub || !sig || !ts || !verifyDiscord(raw, sig, ts, pub))
    return send(res, 401, 'invalid request signature', 'text/plain');
  let body; try { body = JSON.parse(raw); } catch (e) { return send(res, 400, { error: 'bad json' }); }
  if (body.type === 1) return send(res, 200, { type: 1 });                 // PING -> PONG
  if (body.type === 2) {                                                   // APPLICATION_COMMAND
    const r = routeSlash(body.data && body.data.name, (body.data && body.data.options) || []);
    return send(res, 200, { type: 4, data: { content: r.content, flags: r.ephemeral ? 64 : 0 } });
  }
  return send(res, 200, { type: 4, data: { content: 'Nicht unterstützt.', flags: 64 } });
}

/* ---------- Scheduler (deterministisch, zeitzonen-fest) ----------
   Feuert fällige Agents aus config/schedule.json. Zeitbasis = 'zeitzone' aus schedule.json
   (via Intl, UNABHÄNGIG von der Server-TZ). Intervalle sind an der Uhr ausgerichtet;
   Wochentag/Uhrzeit-Läufe feuern nur im Nachhol-Fenster (catchup_minuten) – kein „wahllos". */
const SCHED_ON = (process.env.DISCORD_SCHEDULER || 'on') !== 'off';
const MASTER_DAILY = (process.env.DISCORD_MASTER_DAILY ?? '07:30').trim();          // '' = aus
const STUCK_MIN = Math.max(10, parseInt(process.env.HQ_STUCK_MINUTES, 10) || 45);   // Watchdog-Schwelle
const BACKUP_DAILY = (process.env.HQ_BACKUP_DAILY ?? '').trim();                    // z.B. '03:30'; '' = aus
/* Watchdog: haengende Laeufe (Status 'running', aber lange kein Lebenszeichen) freigeben.
   Faengt harte Abbrueche (Reboot/OOM/Kill), bei denen run-agent.sh nie den Endstatus setzt –
   sonst bliebe der Agent fuer immer 'running' und der Scheduler wuerde ihn nie wieder starten. */
function reapStuck(sched) {
  const f = statusPath();
  const alarms = [];
  withFileLock(f, () => {                        // Status-Reset im kritischen Abschnitt
    let d; try { d = JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return; }
    if (!d || !d.agents) return;
    const now = Date.now(); let dirty = false;
    for (const [id, ag] of Object.entries(d.agents)) {
      if (!ag || ag.status !== 'running' || id === 'master') continue;
      const t = Date.parse(ag.last_run || ag.updated || d.updated || '');
      if (!t || now - t < STUCK_MIN * 60000) continue;               // noch am Leben (oder kein Zeitstempel)
      const mins = Math.round((now - t) / 60000);
      ag.status = 'error'; ag.phase = 'Abgebrochen (Watchdog)';
      ag.message = `Seit ${mins} min kein Lebenszeichen – als tot markiert (Reboot/OOM/Kill?).`;
      dirty = true;
      alarms.push({ id, msg: `❌ **${id}** hing (>${STUCK_MIN} min ohne Lebenszeichen) – Watchdog hat ihn freigegeben.` });
    }
    if (dirty) { try { writeJsonAtomic(f, d, 1); } catch (e) {} }
  });
  for (const a of alarms) { try { dpost(chanOf(a.id, sched), a.msg); } catch (e) {} }  // Discord AUSSERHALB des Locks
}
const HEARTBEAT = (process.env.DISCORD_HEARTBEAT ?? '').split(',').map(s => s.trim()).filter(Boolean); // Default: aus
function heartbeatText() {
  let d; try { d = JSON.parse(fs.readFileSync(path.join(BASE, 'uptime', 'uptime.json'), 'utf8')); } catch (e) { return '💓 HQ aktiv.'; }
  const sites = d.sites || [];
  const down = sites.filter(s => !['ok', 'slow'].includes(s.state));
  const stand = (d.stand || '').slice(11, 16);
  if (!sites.length) return '💓 HQ aktiv.';
  if (!down.length) return `💓 ${sites.length}/${sites.length} Seiten oben (${stand}).`;
  return `⚠️ ${sites.length - down.length}/${sites.length} oben – DOWN: ${down.map(s => s.name).join(', ')} (${stand}).`;
}
const FIRES = path.join(WEB, '.sched-fires.json');
let fires = {}; try { fires = JSON.parse(fs.readFileSync(FIRES, 'utf8')); } catch (e) { fires = {}; }
function saveFires() { try { fs.writeFileSync(FIRES, JSON.stringify(fires)); } catch (e) {} }

const WDAYS = { mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6, sun: 0 };          // Intl en-Kürzel
const CAD_WD = { mo: 1, di: 2, mi: 3, do: 4, fr: 5, sa: 6, so: 0 };                // cadence-Kürzel (de)
function zoneNow(tz) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz || 'Europe/Vienna', weekday: 'short', hour12: false,
    hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric'
  }).formatToParts(new Date());
  const g = t => (parts.find(p => p.type === t) || {}).value || '';
  return {
    wd: WDAYS[g('weekday').toLowerCase().slice(0, 3)],
    min: (parseInt(g('hour'), 10) % 24) * 60 + parseInt(g('minute'), 10),
    date: `${g('year')}-${g('month')}-${g('day')}`
  };
}
function chanOf(id, sched) { return (sched[id] && sched[id].channel) || D.log; }

/* true, wenn cadence jetzt fällig ist; belegt fires[id] selbst (Fensterlogik) */
function due(id, cad, z, catchup) {
  cad = (cad || '').toLowerCase().trim();
  if (!cad || cad.includes('abruf')) return false;
  let m;
  if (m = cad.match(/alle\s+(\d+)\s*(min|minuten|h|std|stunde|stunden)/)) {        // Intervall, an der Uhr ausgerichtet
    const ivMin = (+m[1]) * (m[2][0] === 'h' || m[2][0] === 's' ? 60 : 1);
    const slot = Math.floor(Date.now() / (ivMin * 60000));
    if (fires[id] === slot) return false;
    fires[id] = slot; saveFires(); return true;
  }
  if (m = cad.match(/^(mo|di|mi|do|fr|sa|so)\s+(\d{1,2}):(\d{2})/)) {               // Wochentag + Uhrzeit
    if (z.wd !== CAD_WD[m[1]]) return false;
    const sched = (+m[2]) * 60 + (+m[3]);
    if (z.min < sched || z.min >= sched + catchup) return false;                    // nur im Nachhol-Fenster
    if (fires[id] === z.date) return false;                                         // heute schon gefeuert
    fires[id] = z.date; saveFires(); return true;
  }
  if (m = cad.match(/(\d{1,2}):(\d{2})/)) {                                         // reine Uhrzeit -> täglich
    const sched = (+m[1]) * 60 + (+m[2]);
    if (z.min < sched || z.min >= sched + catchup) return false;
    if (fires[id] === z.date) return false;
    fires[id] = z.date; saveFires(); return true;
  }
  return false;
}
/* täglicher Termin (Heartbeat/Master) im Nachhol-Fenster, einmal pro Tag */
function dailyDue(key, hhmm, z, catchup) {
  const m = (hhmm || '').match(/(\d{1,2}):(\d{2})/); if (!m) return false;
  const sched = (+m[1]) * 60 + (+m[2]);
  if (z.min < sched || z.min >= sched + catchup) return false;
  if (fires[key] === z.date) return false;
  fires[key] = z.date; saveFires(); return true;
}
/* next_run in status.json = Wahrheit aus schedule.json (behebt die Log/Report-Drift) */
function humanNext(cfg) {
  if (!cfg || cfg.enabled === false) return 'kein Termin';
  const c = (cfg.cadence || '').trim();
  return (!c || /abruf/i.test(c)) ? 'auf Abruf' : c;
}
function syncNextRuns(sched) {
  const f = statusPath();
  withFileLock(f, () => {
    let d; try { d = JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return; }
    if (!d.agents) return;
    let dirty = false;
    for (const [id, a] of Object.entries(d.agents)) {
      if (id === 'master') continue;
      const nr = humanNext(sched[id]);
      if (a.next_run !== nr) { a.next_run = nr; dirty = true; }
    }
    if (dirty) { try { writeJsonAtomic(f, d, 1); } catch (e) {} }
  });
}
function schedTick() {
  const cfgAll = readSchedule();
  const sched = cfgAll.agents || {};
  const tz = cfgAll.zeitzone || 'Europe/Vienna';
  const catchup = Math.max(5, parseInt(cfgAll.catchup_minuten, 10) || 120);
  const z = zoneNow(tz);
  reapStuck(sched);                                          // tote 'running'-Laeufe zuerst freigeben
  const st = readStatus().agents || {};
  syncNextRuns(sched);
  for (const [id, cfg] of Object.entries(sched)) {
    if (!AGENTS[id] || !cfg || cfg.enabled === false) continue;
    if (!due(id, cfg.cadence, z, catchup)) continue;           // due() belegt das Fenster bereits
    if (st[id] && st[id].status === 'running') continue;       // läuft schon
    if (cfg.schwer) {                                          // schwer -> nachfragen (/ja /nein)
      const short = CHOICE[id] || id;
      dpost(D.cmd, `⏳ **${id}** fällig (${cfg.cadence}) — \`/ja ${short}\` starten · \`/nein ${short}\` überspringen.`);
    } else {
      try { runAgent(id); if (!cfg.quiet) dpost(chanOf(id, sched), `⏰ **${id}** gestartet (Plan: ${cfg.cadence}).`); } catch (e) {}
    }
  }
  for (const hb of HEARTBEAT) { if (dailyDue('__hb_' + hb, hb, z, catchup)) dpost(D.log, heartbeatText()); }
  if (BACKUP_DAILY && dailyDue('__backup__', BACKUP_DAILY, z, catchup)) {
    try {
      const blog = fs.openSync(path.join(BASE, 'logs', 'backup.log'), 'a');
      const c = spawn(findBash(), [path.join(BASE, 'bin', 'backup.sh')], { cwd: BASE, detached: true, stdio: ['ignore', blog, blog], env: process.env });
      c.unref(); try { fs.closeSync(blog); } catch (e) {}
    } catch (e) {}
  }
  if (MASTER_DAILY && dailyDue('__master__', MASTER_DAILY, z, catchup) && !(st.master && st.master.status === 'running')) {
    try {
      runAgent('master', 'Nutze den Subagent kommandant: verschaffe dir den Gesamtüberblick (dashboard/status.json), '
        + 'stimme config/schedule.json ab und stoße fällige Läufe an. Poste danach GENAU EINE knappe Lage-Zeile '
        + '(Ampel je Agent, offene Waits/Fehler zuerst, kein Roman) nach Discord: bin/discord.py post ' + D.log + ' "<Lage>". Nichts an Kunden senden.');
    } catch (e) {}
  }
}
if (SCHED_ON) {
  console.log(`Scheduler aktiv (Tick 30s, TZ aus schedule.json)${MASTER_DAILY ? `, Master-Lage ${MASTER_DAILY}` : ''}${HEARTBEAT.length ? `, Heartbeat ${HEARTBEAT.join('/')}` : ''}.`);
  setInterval(schedTick, 30000);
  schedTick();
} else {
  console.log('Scheduler aus (DISCORD_SCHEDULER=off).');
}

server.listen(PORT, HOST, () => console.log(`Agent HQ läuft auf http://${HOST}:${PORT}  (Basis: ${BASE})`));
