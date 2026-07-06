#!/usr/bin/env node
'use strict';
/* Agent HQ Server – statisches Dashboard + Mission-Control-API.
   Aufruf:  node dashboard/server.js [port]
   Läuft lokal (Windows, Git-Bash vorhanden) und am Plesk-Server (bash nativ). */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const BASE = path.resolve(__dirname, '..');
const WEB = __dirname;
const PORT = parseInt(process.argv[2] || '8788', 10);

const AGENTS = {
  'wochenreport': 'Nutze den Subagent wochenreport und erstelle die Wochenreports für die abgelaufene Woche.',
  'belege-buchhaltung': 'Nutze den Subagent belege-buchhaltung und verarbeite alle neuen Belege in belege/inbox/.',
  'content-recherche': 'Nutze den Subagent content-recherche und erstelle den Contentplan für die kommende Woche.'
};
/* Report-Wurzeln: nur diese Ordner sind über /api lesbar */
const REPORT_ROOTS = ['reports', 'content', 'belege'];
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

function runAgent(id) {
  const script = path.join(BASE, 'bin', 'run-agent.sh');
  const log = fs.openSync(path.join(BASE, 'logs', id + '.server.log'), 'a');
  const child = spawn(findBash(), [script, id, AGENTS[id]], {
    cwd: BASE, detached: true, stdio: ['ignore', log, log]
  });
  child.unref();
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

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = u.pathname;

  /* ---------- API ---------- */
  if (p === '/api/ping') return send(res, 200, { api: true, agents: Object.keys(AGENTS) });

  if (p.startsWith('/api/run/') && req.method === 'POST') {
    const id = p.slice(9);
    if (!AGENTS[id]) return send(res, 404, { error: 'unbekannter agent' });
    const st = readStatus();
    if (st.agents && st.agents[id] && st.agents[id].status === 'running')
      return send(res, 409, { error: 'läuft bereits' });
    try {
      const pid = runAgent(id);
      return send(res, 200, { ok: true, pid });
    } catch (e) { return send(res, 500, { error: String(e.message || e) }); }
  }

  if (p.startsWith('/api/log/')) {
    const id = p.slice(9);
    if (!AGENTS[id]) return send(res, 404, { error: 'unbekannter agent' });
    return send(res, 200, tailLog(id));
  }

  if (p === '/api/reports') return send(res, 200, listReports());

  if (p === '/api/file') {
    const abs = safeFile(u.searchParams.get('p'));
    if (!abs) return send(res, 404, { error: 'nicht gefunden' });
    const type = MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream';
    return send(res, 200, fs.readFileSync(abs), type);
  }

  /* ---------- statisch ---------- */
  let rel = p === '/' ? '/index.html' : p;
  if (rel === '/status.json') return send(res, 200, fs.readFileSync(statusPath()), MIME['.json']);
  const abs = path.resolve(WEB, '.' + rel);
  if (!abs.startsWith(WEB) || !fs.existsSync(abs) || !fs.statSync(abs).isFile())
    return send(res, 404, 'not found', 'text/plain');
  send(res, 200, fs.readFileSync(abs), MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream');
});

fs.mkdirSync(path.join(BASE, 'logs'), { recursive: true });
server.listen(PORT, () => console.log(`Agent HQ: http://localhost:${PORT}  (Basis: ${BASE})`));
