#!/usr/bin/env node
'use strict';
/* TOKEN-FREIER server-waechter. READ-ONLY. Ersetzt den `claude -p`-Lauf durch echte,
   ausschliesslich LESENDE Kommandos (df/free/uptime/nproc/systemctl/…). Regeln aus
   .claude/agents/server-waechter.md: jeder Wert echt; fehlt ein Werkzeug/Pfad -> der
   Check ist `n/a` (nie gruen erfunden); nichts wird veraendert (kein restart/rm/sudo).
   Auf Nicht-Linux (lokale Windows-Entwicklung) sind die meisten Tools nicht da ->
   sauber `n/a` statt Absturz. */
const fs = require('fs');
const path = require('path');
const L = require('./lib');

const A = L.agent('server-waechter');
const CFG = path.join(L.BASE, 'config', 'server.json');
const OUT = path.join(L.BASE, 'server', 'server-status.json');
const ALERTDIR = path.join(L.BASE, 'server', 'alerts');
const CH_LOG = process.env.DISCORD_LOG_CHANNEL || 'agent-logs';
const CH_ALERT = process.env.DISCORD_COMMAND_CHANNEL || 'freigaben';
const SSL_WARN = 21;

const sh = (cmd, args, t = 15000) => L.run(cmd, args, { timeoutMs: t });
const shline = (cmdline, t = 15000) => L.run('sh', ['-c', cmdline], { timeoutMs: t });  // nur LESENDE Pipelines
const num = v => { const n = Number(v); return Number.isFinite(n) ? n : null; };

function fail(msg) {
  A.log('FEHLER: ' + msg);
  A.status('error', 'Abgebrochen', 0, msg.slice(0, 200));
  process.stdout.write(JSON.stringify({ result: 'server-waechter: ' + msg }) + '\n');
  process.exit(1);
}

/* ---------- Einzel-Checks (jeder gibt Wert ODER null=n/a) ---------- */
function checkDisk(warnPct) {                            // belegtester Nicht-tmpfs-Mount
  if (!L.haveTool('df')) return null;
  const r = shline("df -P -k -x tmpfs -x devtmpfs 2>/dev/null | tail -n +2");
  if (!r.ok || !r.out.trim()) return null;
  let worst = null;
  for (const line of r.out.trim().split('\n')) {
    // Am 'NN%'-Token verankern statt an Spaltenindizes: Filesystem-/Mount-Namen duerfen
    // Leerzeichen enthalten (df -P haelt Capacity als einziges Feld mit '%').
    const m = line.match(/\s(\d+)%\s+(.+)$/);
    if (!m) continue;
    const used = parseInt(m[1], 10);
    if (!Number.isFinite(used) || used < 0 || used > 100) continue;   // Parse-Fehler -> ueberspringen, nie Muell melden
    const before = line.slice(0, m.index).trim().split(/\s+/);
    const availKb = parseInt(before[before.length - 1], 10);          // Available = Zahl direkt vor dem %
    const freeGb = Number.isFinite(availKb) ? +(availKb / 1048576).toFixed(1) : null;
    if (!worst || used > worst.used_percent) worst = { used_percent: used, warn: warnPct, free_gb: freeGb, mount: m[2].trim() };
  }
  return worst;
}
function checkMem() {
  if (!L.haveTool('free')) return null;
  const r = sh('free', ['-m']);
  if (!r.ok) return null;
  const line = r.out.split('\n').find(l => /^Mem:/.test(l));
  if (!line) return null;
  const c = line.trim().split(/\s+/);
  const total = parseInt(c[1], 10), used = parseInt(c[2], 10);
  const avail = parseInt(c[6], 10);                       // "available" (Spalte 7), falls vorhanden
  const realUsed = Number.isFinite(avail) ? total - avail : used;
  if (!Number.isFinite(total) || !total) return null;
  return { used_percent: Math.round(realUsed / total * 100), used_gb: +(realUsed / 1024).toFixed(1), total_gb: +(total / 1024).toFixed(1) };
}
function checkLoad(warnPerCore) {
  if (!L.haveTool('uptime')) return null;
  const r = sh('uptime', []);
  const m = r.out.match(/load average[s]?:\s*([\d.,]+)/i);
  if (!m) return null;
  const load1 = parseFloat(m[1].replace(',', '.'));
  let cores = 1;
  if (L.haveTool('nproc')) { const n = parseInt(sh('nproc', []).out.trim(), 10); if (Number.isFinite(n) && n > 0) cores = n; }
  return { per_core: +(load1 / cores).toFixed(2), warn: warnPerCore, cores };
}
function checkServices(units) {
  if (!Array.isArray(units) || !units.length) return null;
  if (!L.haveTool('systemctl')) return units.map(u => ({ name: u, active: null, note: 'systemctl n/a' }));
  return units.map(u => {
    const r = sh('systemctl', ['is-active', u]);
    return { name: u, active: r.out.trim() === 'active' };
  });
}
// "Konnte nicht pruefen" (Werkzeug/Rechte/Wrapper kaputt) vs. "DB wirklich tot".
// Solche Fehler duerfen NIEMALS als down zaehlen -> ehrlich n/a (active=null).
function accessErr(txt) {
  return /permission denied|cannot connect to the docker|docker api|is the docker daemon running|no such container|no such file|command not found|not found|executable file not found|operation not permitted|access denied|must be root|got permission denied/i.test(txt || '');
}
// active: true = lebt | false = geprueft und tot (Alarm) | null = nicht pruefbar (n/a, KEIN Alarm)
function checkDatabases(dbs) {
  if (!Array.isArray(dbs) || !dbs.length) return null;
  return dbs.map(db => {
    const rec = { name: db.name || db.type || 'db', type: db.type || '', active: null, latency_ms: null, note: '' };
    const t0 = Date.now();
    let done = false;
    if (db.check) {                                       // eigenes READ-ONLY-Kommando
      const r = shline(db.check, 12000);
      const errtxt = (r.err || r.out || '').trim();
      if (r.ok) rec.active = true;
      else if (accessErr(errtxt)) { rec.active = null; rec.note = 'nicht pruefbar: ' + errtxt.slice(0, 90); }
      else { rec.active = false; rec.note = errtxt.slice(0, 90); }   // Kommando lief, DB antwortet nicht -> down
      done = true;
    } else if (db.type === 'sqlite' && db.file) {
      rec.active = fs.existsSync(db.file); if (!rec.active) rec.note = 'Datei fehlt/nicht lesbar'; done = true;
    } else if (db.type === 'postgres' && L.haveTool('pg_isready')) {
      const r = sh('pg_isready', ['-h', String(db.host || '127.0.0.1'), '-p', String(db.port || 5432)]);
      rec.active = r.ok ? true : (accessErr(r.err) ? null : false); done = true;
    } else if (db.type === 'redis' && L.haveTool('redis-cli')) {
      const r = sh('redis-cli', ['-h', String(db.host || '127.0.0.1'), '-p', String(db.port || 6379), 'ping']);
      const o = r.out + r.err;
      rec.active = /PONG|NOAUTH|WRONGPASS/i.test(o) ? true : (/refused|timed out|no route|cannot connect/i.test(o) ? false : null);
      done = true;
    } else if ((db.type === 'mysql' || db.type === 'mariadb') && L.haveTool('mysqladmin')) {
      const r = sh('mysqladmin', ['ping', '-h', String(db.host || '127.0.0.1'), '-P', String(db.port || 3306)]);
      const o = r.out + r.err;
      // "mysqld is alive" ODER "Access denied" => Server erreichbar (lebt). Nur echtes
      // "connect failed/refused" => down. Sonst nicht eindeutig -> n/a.
      rec.active = /alive|access denied/i.test(o) ? true : (/refused|can'?t connect|cannot connect|timed out/i.test(o) ? false : null);
      if (rec.active == null) rec.note = (o.trim().slice(0, 90) || 'unklar');
      done = true;
    }
    if (!done && db.port && L.haveTool('ss')) {           // Fallback: lauscht der Port?
      rec.active = shline(`ss -ltn 2>/dev/null | grep -q ':${parseInt(db.port, 10)}\\b'`).ok ? true : false; done = true;
    }
    if (!done) { rec.active = null; rec.note = rec.note || 'kein passendes Pruefwerkzeug -> nicht pruefbar'; }
    else if (rec.active === true) rec.latency_ms = Date.now() - t0;
    return rec;
  });
}
function checkSsl() {                                     // Renew-Sicht der Box via certbot
  if (!L.haveTool('certbot')) return null;
  const r = shline('certbot certificates 2>/dev/null');
  if (!r.ok) return null;
  const days = [];
  const re = /VALID:\s*(\d+)\s*day/gi; let m;
  while ((m = re.exec(r.out))) days.push(parseInt(m[1], 10));
  return days.length ? Math.min(...days) : null;
}
function checkBackups(dirs, maxHours) {
  if (!Array.isArray(dirs) || !dirs.length) return null;
  return dirs.map(d => {
    let newest = 0;
    try {
      for (const f of fs.readdirSync(d)) { try { const st = fs.statSync(path.join(d, f)); if (st.isFile() && st.mtimeMs > newest) newest = st.mtimeMs; } catch (e) {} }
    } catch (e) { return { name: d, age_hours: null, max_hours: maxHours, ok: false, note: 'Pfad nicht lesbar' }; }
    if (!newest) return { name: d, age_hours: null, max_hours: maxHours, ok: false, note: 'kein Backup-File' };
    const ageH = +((Date.now() - newest) / 3600000).toFixed(1);
    return { name: d, age_hours: ageH, max_hours: maxHours, ok: ageH <= maxHours };
  });
}
function checkLogins(authLog) {
  const out = { failed_ssh: null, note: '' };
  if (authLog && fs.existsSync(authLog)) {
    const r = shline(`grep -c 'Failed password' '${authLog}' 2>/dev/null`);
    const n = parseInt(r.out.trim(), 10); if (Number.isFinite(n)) out.failed_ssh = n;
  }
  if (L.haveTool('fail2ban-client')) {
    const r = shline('fail2ban-client status sshd 2>/dev/null');
    const m = r.out.match(/Currently banned:\s*(\d+)/i); if (m) out.note = `fail2ban banned: ${m[1]}`;
  }
  return (out.failed_ssh == null && !out.note) ? null : out;
}
function checkLogDir() {                                  // Wachstum von logs/ (dieses Repos)
  const dir = path.join(L.BASE, 'logs');
  try {
    let bytes = 0;
    const walk = d => { for (const f of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, f.name); if (f.isDirectory()) walk(p); else { try { bytes += fs.statSync(p).size; } catch (e) {} } } };
    walk(dir);
    return Math.round(bytes / 1048576);
  } catch (e) { return null; }
}

function main() {
  const cfg = L.readJson(CFG, null);
  if (!cfg || typeof cfg !== 'object') fail('config/server.json fehlt oder unlesbar');
  A.status('running', 'Pruefe Server', 10, 'READ-ONLY Checks…');

  const warnDisk = num(cfg.disk_warn_percent) || 85;
  const warnLoad = num(cfg.load_warn_per_core) || 1.5;
  const maxBackupH = num(cfg.backup_max_age_hours) || 26;
  const logWarnMb = num(cfg.log_dir_warn_mb) || 500;

  A.log('Disk/Speicher/Last…'); A.status('running', 'Pruefe Server', 25, 'Disk/Speicher/Last');
  const disk = checkDisk(warnDisk), memory = checkMem(), load = checkLoad(warnLoad);
  A.log('Dienste/Datenbanken…'); A.status('running', 'Pruefe Server', 50, 'Dienste/DBs');
  const services = checkServices(cfg.systemd_units);
  const databases = checkDatabases(cfg.databases);
  A.log('SSL/Backups/Logins/Logs…'); A.status('running', 'Pruefe Server', 75, 'SSL/Backups/Logins');
  const ssl_min_days = checkSsl();
  const backups = checkBackups(cfg.backup_dirs, maxBackupH);
  const logins = checkLogins(cfg.auth_log);
  const log_dir_mb = checkLogDir();

  // Host-Info
  const host = (L.haveTool('hostname') ? sh('hostname', []).out.trim() : '') || require('os').hostname();
  let osName = `${require('os').type()} (${require('os').release()})`;
  if (fs.existsSync('/etc/os-release')) { const m = fs.readFileSync('/etc/os-release', 'utf8').match(/PRETTY_NAME="?([^"\n]+)/); if (m) osName = m[1]; }
  let uptimeStr = '';
  if (L.haveTool('uptime')) { const m = sh('uptime', []).out.match(/up\s+(.+?),\s+\d+\s+user/); if (m) uptimeStr = m[1].trim(); }

  // Zustand + Alerts sammeln (worst = schlechtestes Einzelergebnis)
  const alerts = [];
  let worst = 'ok';
  const bump = lvl => { if (lvl === 'down') worst = 'down'; else if (lvl === 'warn' && worst !== 'down') worst = 'warn'; };

  if (disk && disk.used_percent >= warnDisk) { alerts.push(`Disk ${disk.mount}: ${disk.used_percent}% (>= ${warnDisk}%)`); bump('warn'); }
  if (load && load.per_core >= warnLoad) { alerts.push(`Last ${load.per_core}/Kern (>= ${warnLoad})`); bump('warn'); }
  if (Array.isArray(services)) for (const s of services) if (s.active === false) { alerts.push(`Dienst down: ${s.name}`); bump('down'); }
  if (Array.isArray(databases)) for (const d of databases) if (d.active === false) { alerts.push(`DB nicht erreichbar: ${d.name}${d.note ? ' (' + d.note + ')' : ''}`); bump('down'); }
  // n/a-DBs (nicht pruefbar) NICHT alarmieren, aber sichtbar vermerken (kein Fehlalarm).
  const dbNa = Array.isArray(databases) ? databases.filter(d => d.active == null) : [];
  if (ssl_min_days != null && ssl_min_days < SSL_WARN) { alerts.push(`SSL-Renew kritisch: ${ssl_min_days} Tage`); bump('warn'); }
  if (Array.isArray(backups)) for (const b of backups) if (!b.ok) { alerts.push(`Backup veraltet/fehlt: ${b.name}${b.note ? ' (' + b.note + ')' : ''}`); bump('warn'); }
  if (log_dir_mb != null && log_dir_mb >= logWarnMb) { alerts.push(`logs/ ${log_dir_mb} MB (>= ${logWarnMb})`); bump('warn'); }

  const prevState = (L.readJson(OUT, {}) || {}).state || 'ok';
  const now = L.localIso();
  const snap = { stand: now, state: worst, host, os: osName };
  if (uptimeStr) snap.uptime = uptimeStr;
  if (disk) snap.disk = { used_percent: disk.used_percent, warn: disk.warn, free_gb: disk.free_gb };
  if (memory) snap.memory = memory;
  if (load) snap.load = load;
  if (services) snap.services = services;
  if (databases) snap.databases = databases;
  if (backups) snap.backups = backups;
  if (ssl_min_days != null) snap.ssl_min_days = ssl_min_days;
  if (logins) snap.logins = logins;
  if (log_dir_mb != null) snap.log_dir_mb = log_dir_mb;
  snap.alerts = alerts;
  L.atomicWrite(OUT, snap, 1);
  A.log(`server-status.json geschrieben (state=${worst}, ${alerts.length} Alert(s))`);

  // Alert-Entwurf bei warn/down (ein File pro Lauf), NUR Vorschlag – nie ausgefuehrt
  const outputs = [];
  if (worst !== 'ok') {
    fs.mkdirSync(ALERTDIR, { recursive: true });
    const f = path.join(ALERTDIR, `${L.isoDate()}_server.md`);
    const suggest = [];
    if (Array.isArray(services)) for (const s of services) if (s.active === false) suggest.push(`Vorschlag: \`systemctl restart ${s.name}\` – bitte pruefen und selbst ausfuehren.`);
    if (disk && disk.used_percent >= warnDisk) suggest.push('Vorschlag: alte Logs/Backups pruefen und aufraeumen (manuell).');
    const lines = [`# server-Alert · ${worst.toUpperCase()}`, '', `- **Zeit:** ${now}`, `- **Host:** ${host}`, '',
      '**Befunde:**', ...alerts.map(a => '- ' + a), '', '**Fix-Vorschlaege (NICHT ausgefuehrt):**',
      ...(suggest.length ? suggest.map(s => '- ' + s) : ['- (kein Standard-Fix – manuell pruefen)']),
      '', '_Automatischer Entwurf (server-waechter, token-frei, read-only). Kein Eingriff._', ''];
    try { fs.writeFileSync(f, lines.join('\n')); outputs.push(path.relative(L.BASE, f).split(path.sep).join('/')); } catch (e) {}
  }
  // Discord nur bei ZUSTANDSWECHSEL (kein Stunden-Spam bei anhaltendem warn/down)
  const sev = { ok: 0, warn: 1, down: 2 };
  if (sev[worst] > sev[prevState]) A.discord(worst === 'down' ? CH_ALERT : CH_LOG, `${worst === 'down' ? '❌' : '⚠️'} **Server ${worst}**: ${alerts.slice(0, 3).join(' · ')}`);
  else if (sev[worst] < sev[prevState]) A.discord(CH_LOG, `✅ **Server** wieder ${worst} (war ${prevState}).`);

  const details = [];
  if (disk) details.push(`Disk ${disk.mount}: ${disk.used_percent}% ${disk.used_percent >= warnDisk ? 'WARN' : 'ok'}`);
  if (memory) details.push(`RAM: ${memory.used_percent}%`);
  if (load) details.push(`Last: ${load.per_core}/Kern`);
  if (Array.isArray(services)) for (const s of services) details.push(`${s.name}: ${s.active === false ? 'DOWN' : s.active ? 'active' : 'n/a'}`);
  if (Array.isArray(databases)) for (const d of databases) details.push(`${d.name}: ${d.active === true ? 'ok' : d.active === false ? 'DOWN' : 'n/a'}`);
  if (ssl_min_days != null) details.push(`SSL min: ${ssl_min_days} T`);
  if (log_dir_mb != null) details.push(`logs/: ${log_dir_mb} MB`);

  const summary = worst === 'ok' ? `Server ok — ${details.slice(0, 3).join(', ')}` : `Server ${worst}: ${alerts.slice(0, 2).join('; ')}`;
  // Lauf-Status = ok (die Messung lief). Der Server-Zustand (warn/down) steckt in server.json
  // + Alert + eigener Discord-Meldung – analog uptime-waechter. 'error' bleibt echten Tool-Fehlern.
  A.status('ok', 'Fertig', 100, summary, details, outputs);

  // Routine-Zeile in den Themen-Kanal – höchstens 1×/Stunde (Cadence ist eh 60 min),
  // Zustandswechsel (ok<->warn<->down) kommt sofort durch (force).
  const naSuffix = dbNa.length ? ` · ${dbNa.length} DB n/a` : '';
  A.routine(worst === 'ok'
    ? `✅ **server** ok${disk ? ` · Disk ${disk.used_percent}%` : ''}${memory ? ` · RAM ${memory.used_percent}%` : ''}${load ? ` · Last ${load.per_core}/K` : ''}${naSuffix}`
    : `${worst === 'down' ? '❌' : '⚠️'} **server** ${worst}: ${alerts.slice(0, 2).join(' · ')}${naSuffix}`,
    { minMinutes: 55, force: worst !== prevState });
  process.stdout.write(JSON.stringify({ result: summary, engine: 'script' }) + '\n');
  process.exit(0);
}

try { main(); } catch (e) { fail(String(e && e.stack || e)); }
