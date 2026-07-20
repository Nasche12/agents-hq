'use strict';
/* Geteilte Helfer fuer die TOKEN-FREIEN Skript-Agents (bin/agents/*.js).
   Diese Agents ersetzen `claude -p` fuer rein deterministische Arbeit (messen,
   klassifizieren, Reports schreiben) – 0 Tokens. Sie laufen ueber bin/run-agent.sh
   (engine=script) und teilen sich dessen Drumherum: Live-/Run-Log, status.json,
   logs/<agent>.jsonl-Historie, Discord-Alarm, Dashboard-Spiegelung, Rotation.

   Bewusst NUR Node + Systemwerkzeuge (curl/df/…): laeuft ueberall, wo der Dashboard-
   Server laeuft – auch auf Windows ohne Python. Kernprinzip aus den Agent-Prompts:
   JEDER Wert aus echtem Kommando-Output. Fehlt ein Werkzeug -> ehrlich `n/a`/error,
   NIE schaetzen, NIE aus einem frueheren Lauf uebernehmen. */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const BASE = path.resolve(__dirname, '..', '..');
const WEBDIR = fs.existsSync(path.join(BASE, 'httpdocs')) ? path.join(BASE, 'httpdocs') : path.join(BASE, 'dashboard');
const STATUS = path.join(WEBDIR, 'status.json');
const HQ = path.join(BASE, 'bin', 'hq.js');
const DPY = path.join(BASE, 'bin', 'discord.py');
const SCHED = path.join(BASE, 'config', 'schedule.json');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

/* ---------- kleine Bausteine ---------- */
function localIso(d = new Date()) {
  const off = -d.getTimezoneOffset(), s = off >= 0 ? '+' : '-';
  const two = n => String(Math.floor(Math.abs(n))).padStart(2, '0');
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${s}${two(off / 60)}:${two(Math.abs(off) % 60)}`;
}
const readJson = (f, fb) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return fb; } };
function atomicWrite(f, obj, spaces) {
  fs.mkdirSync(path.dirname(f), { recursive: true });
  const tmp = f + '.tmp.' + process.pid + '.' + Math.floor(Math.random() * 1e9);
  try { fs.writeFileSync(tmp, JSON.stringify(obj, null, spaces == null ? 1 : spaces)); fs.renameSync(tmp, f); }
  catch (e) { try { fs.unlinkSync(tmp); } catch (_) {} throw e; }
}
function nowKW(d = new Date()) {                       // ISO-Kalenderwoche "JJJJ-KW" fuer seo/
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day);
  const ys = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  const wk = Math.ceil(((t - ys) / 86400000 + 1) / 7);
  return `${t.getUTCFullYear()}-KW${String(wk).padStart(2, '0')}`;
}
const isoDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const slug = s => String(s || '').toLowerCase().replace(/^https?:\/\//, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'x';

/* ---------- Shell (synchron, ohne Shell-Interpolation) ---------- */
function run(cmd, args, { timeoutMs = 25000, input } = {}) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024, input });
  return {
    code: r.status == null ? -1 : r.status,
    out: r.stdout || '',
    err: (r.stderr || '') + (r.error ? String(r.error.message || r.error) : ''),
    ok: r.status === 0
  };
}
function haveTool(cmd) {                                // existiert das Werkzeug? (n/a-Entscheidung)
  const probe = process.platform === 'win32'
    ? run('where', [cmd], { timeoutMs: 4000 })
    : run('sh', ['-c', 'command -v ' + cmd], { timeoutMs: 4000 });
  return probe.ok && probe.out.trim().length > 0;
}

/* ---------- curl-Messungen (nur GET/HEAD, jeder Wert echt) ---------- */
const CURL = 'curl';
function curlMetric(url, timeout = 20) {               // http_code, time_total, effektive URL
  const r = run(CURL, ['-sS', '-o', process.platform === 'win32' ? 'NUL' : '/dev/null',
    '-w', '%{http_code} %{time_total} %{url_effective}', '-L', '--max-time', String(timeout), url],
    { timeoutMs: (timeout + 6) * 1000 });
  const parts = r.out.trim().split(/\s+/);
  if (parts.length >= 2 && /^\d+$/.test(parts[0])) {
    return { http: parseInt(parts[0], 10), ms: Math.round(parseFloat(parts[1]) * 1000), url_eff: parts[2] || url, ok: true };
  }
  return { http: null, ms: null, url_eff: url, ok: false, err: (r.err || r.out || 'curl fehlgeschlagen').trim().slice(0, 200) };
}
function curlBody(url, timeout = 20) {                  // HTML-Body (fuer expect/img/links/seo)
  const r = run(CURL, ['-sS', '-L', '--max-time', String(timeout), url], { timeoutMs: (timeout + 6) * 1000 });
  return { body: r.out, ok: r.ok, err: r.err.trim().slice(0, 200) };
}
function curlStatus(url, { head = true, timeout = 20 } = {}) {  // reiner Statuscode (Link-Check/Health)
  const args = ['-sS', '-o', process.platform === 'win32' ? 'NUL' : '/dev/null', '-w', '%{http_code}', '-L', '--max-time', String(timeout)];
  if (head) args.push('-I');
  args.push(url);
  const r = run(CURL, args, { timeoutMs: (timeout + 6) * 1000 });
  const code = parseInt(r.out.trim(), 10);
  return Number.isFinite(code) && code > 0 ? code : null;
}
function curlAsset(url, timeout = 20) {                 // Bildcheck: 200 + image/* + >0 Byte
  const r = run(CURL, ['-sS', '-o', process.platform === 'win32' ? 'NUL' : '/dev/null',
    '-w', '%{http_code} %{content_type} %{size_download}', '-L', '--max-time', String(timeout), url],
    { timeoutMs: (timeout + 6) * 1000 });
  const p = r.out.trim().split(/\s+/);
  const http = parseInt(p[0], 10), ct = (p[1] || '').toLowerCase(), size = parseInt(p[2], 10) || 0;
  return { http: Number.isFinite(http) ? http : null, ct, size, ok: http === 200 && ct.startsWith('image/') && size > 0 };
}
function sslDaysLeft(url, timeout = 20) {               // TLS-Restlaufzeit, portabel (Linux + Windows)
  let host, port;
  try { const u = new URL(url); host = u.hostname; port = u.port || '443'; } catch (e) { return null; }
  if (!/^[a-zA-Z0-9.-]+$/.test(host)) return null;      // Hostname sauber -> keine Shell-Injection im Fallback
  // 1) curl -v: Linux/OpenSSL-curl (Prod) druckt "* expire date: …"
  const r = run(CURL, ['-sSv', '-o', process.platform === 'win32' ? 'NUL' : '/dev/null', '--max-time', String(timeout), url],
    { timeoutMs: (timeout + 6) * 1000 });
  let m = (r.err + '\n' + r.out).match(/expire date:\s*(.+)/i);
  // 2) Fallback: Windows-curl nutzt Schannel (kein Datum) -> openssl s_client
  if (!m && haveTool('openssl')) {
    const o = run('sh', ['-c', `echo | openssl s_client -connect ${host}:${port} -servername ${host} 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null`],
      { timeoutMs: (timeout + 6) * 1000 });
    m = o.out.match(/notAfter=(.+)/i);
  }
  if (!m) return null;                                  // nicht lesbar -> n/a, NICHT raten
  const exp = Date.parse(m[1].trim());
  if (!Number.isFinite(exp)) return null;
  return Math.floor((exp - Date.now()) / 86400000);
}

/* Agent-Konfig aus schedule.json (Themen-Kanal + quiet – wie beim LLM-Agenten,
   ueber das Dashboard-quiet-Flag steuerbar). */
function schedCfg(name) { const s = readJson(SCHED, {}); return (s.agents && s.agents[name]) || {}; }
function channelOf(name) { return schedCfg(name).channel || process.env.DISCORD_LOG_CHANNEL || 'agent-logs'; }
function isQuiet(name) { return schedCfg(name).quiet === true; }

/* ---------- Agent-Kontext (Log/Status/Discord, an einen Agent gebunden) ---------- */
function agent(name) {
  const liveLog = path.join(BASE, 'logs', name + '.log');
  fs.mkdirSync(path.dirname(liveLog), { recursive: true });
  const chan = channelOf(name);
  const quiet = isQuiet(name);

  const log = (line) => {                               // Fortschritt ins Live-Log (Dashboard-Drawer liest es)
    try { fs.appendFileSync(liveLog, line.replace(/\r?\n/g, ' ').trim() + '\n'); } catch (e) {}
    process.stdout.write('· ' + line + '\n');
  };
  const status = (st, phase, prog, msg, details, outputs) => {
    const args = ['status', STATUS, name, st, phase, String(prog), msg,
      details ? JSON.stringify(details) : '', outputs ? JSON.stringify(outputs) : ''];
    run(process.execPath, [HQ, ...args], { timeoutMs: 8000 });
  };
  const discord = (channel, text, attach) => {         // knapper Einzeiler; nur wenn Bot konfiguriert
    if (!process.env.DISCORD_BOT_TOKEN) return;
    const args = ['post', channel, text];
    if (attach) args.push('--attach', attach);
    run(PY, [DPY, ...args], { timeoutMs: 15000 });
  };
  // Routine-Zeile in den Themen-Kanal. Respektiert quiet. Optional throttlebar:
  // opts.minMinutes = frueheste Wiederholung (Ruhefenster), opts.force = Fenster ignorieren
  // (z. B. bei echtem Zustandswechsel). So kann man alle 15 min MESSEN, aber nur 1×/h POSTEN,
  // waehrend ein Ausfall sofort durchkommt. Zeitstempel je Agent in logs/<name>.lastpost.
  const routine = (text, opts = {}) => {
    if (quiet) return;
    const { minMinutes, force, attach } = opts;
    const stampFile = path.join(BASE, 'logs', name + '.lastpost');
    if (minMinutes && !force) {
      let last = 0; try { last = parseInt(fs.readFileSync(stampFile, 'utf8'), 10) || 0; } catch (e) {}
      if (Date.now() - last < minMinutes * 60000) return;   // noch im Ruhefenster -> still
    }
    discord(chan, text, attach);
    try { fs.writeFileSync(stampFile, String(Date.now())); } catch (e) {}
  };
  return { name, BASE, log, status, discord, routine, chan, quiet, liveLog };
}

module.exports = {
  BASE, WEBDIR, STATUS,
  localIso, readJson, atomicWrite, nowKW, isoDate, slug,
  run, haveTool, curlMetric, curlBody, curlStatus, curlAsset, sslDaysLeft,
  schedCfg, channelOf, isQuiet, agent
};
