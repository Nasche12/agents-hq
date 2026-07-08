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
const PORT = parseInt(process.env.PORT || process.argv[2] || '8788', 10);
/* Als Service hinter Plesk-Reverse-Proxy nur auf localhost lauschen (nicht welt-offen).
   HOST=0.0.0.0 nur, wenn du bewusst direkt exponierst. */
const HOST = process.env.HOST || '127.0.0.1';

const AGENTS = {
  'master': 'Nutze den Subagent kommandant: verschaffe dir den Gesamtüberblick über alle Agents (dashboard/status.json), stimme den Zeitplan (config/schedule.json) ab und stoße fällige Läufe an. Nichts nach außen senden.',
  'wochenreport': 'Nutze den Subagent wochenreport und erstelle den Wochenreport für die abgelaufene Woche.',
  'belege-buchhaltung': 'Nutze den Subagent belege-buchhaltung und verarbeite alle neuen Belege in belege/inbox/.',
  'content-recherche': 'Nutze den Subagent content-recherche und erstelle den Contentplan für die kommende Woche.',
  'uptime-waechter': 'Nutze den Subagent uptime-waechter und prüfe jetzt alle Sites aus config/sites.json.',
  'seo-audit': 'Nutze den Subagent seo-audit und auditiere alle Sites aus config/sites.json.',
  'rechnungssteller': 'Nutze den Subagent rechnungssteller. Falls keine Positionen genannt sind, frage nach, statt zu raten.'
};
/* Report-Wurzeln: nur diese Ordner sind über /api lesbar */
const REPORT_ROOTS = ['reports', 'content', 'belege', 'uptime', 'seo', 'rechnungen'];
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

function runAgent(id, prompt) {
  const script = path.join(BASE, 'bin', 'run-agent.sh');
  const log = fs.openSync(path.join(BASE, 'logs', id + '.server.log'), 'a');
  const child = spawn(findBash(), [script, id, prompt || AGENTS[id]], {
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

/* Body einer POST-Anfrage als JSON lesen (Limit 1 MB); cb(obj|null) */
function readJson(req, cb) {
  let data = '', too = false;
  req.on('data', c => { data += c; if (data.length > 1e6) { too = true; req.destroy(); } });
  req.on('end', () => { if (too) return cb(null); if (!data) return cb({}); try { cb(JSON.parse(data)); } catch (e) { cb(null); } });
  req.on('error', () => cb(null));
}

const SCHEDULE_FILE = path.join(BASE, 'config', 'schedule.json');
function readSchedule() { try { return JSON.parse(fs.readFileSync(SCHEDULE_FILE, 'utf8')); } catch (e) { return { agents: {} }; } }

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
        cur.agents[id] = Object.assign({}, cur.agents[id], {
          enabled: patch.enabled !== false,
          cadence: typeof patch.cadence === 'string' ? patch.cadence.slice(0, 40) : (cur.agents[id] || {}).cadence
        });
      }
      try {
        const tmp = SCHEDULE_FILE + '.tmp';
        fs.writeFileSync(tmp, JSON.stringify(cur, null, 2)); fs.renameSync(tmp, SCHEDULE_FILE);
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
  if (rel === '/uptime.json') {
    const f = path.join(BASE, 'uptime', 'uptime.json');
    try { return send(res, 200, fs.readFileSync(f), MIME['.json']); } catch (e) { return send(res, 200, { sites: [], history: [] }); }
  }
  const abs = path.resolve(WEB, '.' + rel);
  if (!abs.startsWith(WEB) || !fs.existsSync(abs) || !fs.statSync(abs).isFile())
    return send(res, 404, 'not found', 'text/plain');
  send(res, 200, fs.readFileSync(abs), MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream');
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
  '🤖 **HQ-Kommandos** (schreib sie einfach hier rein):',
  '• `status` – Lage aller Agents',
  '• `run <agent>` oder nur `<agent>` – Lauf starten',
  '• `<agent>: <auftrag>` – Lauf mit eigenem Auftrag',
  '• `go [agent]` – Freigabe: wartenden Agent seine Aktion ausführen lassen',
  '• `agents` – bekannte Agents auflisten',
  '• `help` – diese Hilfe'
].join('\n');

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
function dHandle(text) {
  text = (text || '').trim();
  if (!text) return;
  const low = text.toLowerCase();
  let m;
  if (low === 'help' || low === 'hilfe' || low === '?') return dpost(D.cmd, D_HELP);
  if (low === 'status') return dpost(D.cmd, dStatusText());
  if (low === 'agents' || low === 'agent') return dpost(D.cmd, 'Agents: ' + Object.keys(AGENTS).join(', '));
  if (m = low.match(/^(?:run|start|starte)\s+([a-z-]+)$/)) return dRun(m[1]);
  if (m = low.match(/^go(?:\s+([a-z-]+))?$/)) return dGo(m[1]);
  if (m = text.match(/^([a-z-]+)\s*:\s*([\s\S]+)/i)) { const id = m[1].toLowerCase(); if (AGENTS[id]) return dRun(id, m[2].trim()); }
  if (AGENTS[low]) return dRun(low);
  dpost(D.cmd, `❓ Verstehe "${text}" nicht. Tippe \`help\`.`);
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

server.listen(PORT, HOST, () => console.log(`Agent HQ läuft auf http://${HOST}:${PORT}  (Basis: ${BASE})`));
