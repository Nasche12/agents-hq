#!/usr/bin/env node
'use strict';
/* TOKEN-FREIER backup-auditor. READ-ONLY. Prueft die Backup-Ziele aus config/backups.json:
   existiert das neueste Backup, ist es aktuell genug (max_age_hours), gross genug (min_bytes),
   liegt eine offsite-Kopie vor, und ist das Archiv nicht offensichtlich kaputt (tar/zip-Test)?
   Kein Restore, kein Schreiben in Backup-Ziele. Fehlt ein Pruefwerkzeug -> ehrlich n/a.
   config/backups.json leer -> "nicht konfiguriert" (Status ok), KEIN Alarm. */
const fs = require('fs');
const path = require('path');
const L = require('./lib');

const A = L.agent('backup-auditor');
const CFG = path.join(L.BASE, 'config', 'backups.json');
const OUTDIR = path.join(L.BASE, 'backup', L.nowKW());
const ALERTDIR = path.join(L.BASE, 'backup', 'alerts');
const CH_ALERT = process.env.DISCORD_COMMAND_CHANNEL || 'freigaben';

function fail(msg) {
  A.log('FEHLER: ' + msg);
  A.status('error', 'Abgebrochen', 0, msg.slice(0, 200));
  process.stdout.write(JSON.stringify({ result: 'backup-auditor: ' + msg }) + '\n');
  process.exit(1);
}

const globToRe = g => new RegExp('^' + String(g || '*').replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$', 'i');

/* Neueste Datei in dir, deren Basename glob matcht (READ-ONLY). */
function newestMatch(dir, glob) {
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return { err: 'Ordner nicht lesbar' }; }
  const re = globToRe(glob);
  let best = null;
  for (const e of entries) {
    if (!e.isFile() || !re.test(e.name)) continue;
    let st; try { st = fs.statSync(path.join(dir, e.name)); } catch (e2) { continue; }
    if (!best || st.mtimeMs > best.mtimeMs) best = { name: e.name, path: path.join(dir, e.name), size: st.size, mtimeMs: st.mtimeMs };
  }
  return best ? { file: best } : { err: 'kein passendes Backup gefunden' };
}

/* Leichter Integritaets-Test (nur wenn passendes Werkzeug da; sonst n/a). */
function integrity(file) {
  const low = file.toLowerCase();
  if ((low.endsWith('.tar.gz') || low.endsWith('.tgz') || low.endsWith('.tar')) && L.haveTool('tar')) {
    const flag = low.endsWith('.tar') ? '-tf' : '-tzf';
    const r = L.run('tar', [flag, file], { timeoutMs: 60000 });
    return r.ok ? 'ok' : 'kaputt';
  }
  if (low.endsWith('.zip') && L.haveTool('unzip')) {
    const r = L.run('unzip', ['-t', '-qq', file], { timeoutMs: 60000 });
    return r.ok ? 'ok' : 'kaputt';
  }
  if (low.endsWith('.gz') && L.haveTool('gzip')) {
    const r = L.run('gzip', ['-t', file], { timeoutMs: 60000 });
    return r.ok ? 'ok' : 'kaputt';
  }
  return 'n/a';
}

function auditTarget(t) {
  const name = t.name || t.dir || 'backup';
  const dir = path.isAbsolute(t.dir || '') ? t.dir : path.resolve(L.BASE, t.dir || '');
  const maxAge = Number(t.max_age_hours) || 26;
  const minBytes = Number(t.min_bytes) || 0;
  const res = { name, dir, state: 'ok', problems: [], newest: null, age_hours: null, size: null, integrity: 'n/a', offsite: t.offsite_dir ? 'prüfe…' : 'n/a' };
  const bump = s => { if (s === 'down') res.state = 'down'; else if (s === 'warn' && res.state !== 'down') res.state = 'warn'; };

  const nm = newestMatch(dir, t.glob);
  if (nm.err) { res.problems.push(nm.err); bump('down'); return res; }
  const b = nm.file;
  res.newest = b.name; res.size = b.size;
  res.age_hours = +((Date.now() - b.mtimeMs) / 3600000).toFixed(1);
  if (res.age_hours > maxAge) { res.problems.push(`veraltet: ${res.age_hours} h (max ${maxAge} h)`); bump('warn'); }
  if (minBytes && b.size < minBytes) { res.problems.push(`zu klein: ${b.size} B (min ${minBytes} B)`); bump('warn'); }
  res.integrity = integrity(b.path);
  if (res.integrity === 'kaputt') { res.problems.push('Archiv defekt (Integritäts-Test fehlgeschlagen)'); bump('down'); }

  // offsite-Kopie
  if (t.offsite_dir) {
    const odir = path.isAbsolute(t.offsite_dir) ? t.offsite_dir : path.resolve(L.BASE, t.offsite_dir);
    const onm = newestMatch(odir, t.glob);
    if (onm.err) { res.offsite = 'fehlt'; res.problems.push(`offsite fehlt (${onm.err})`); bump('warn'); }
    else {
      const oAge = +((Date.now() - onm.file.mtimeMs) / 3600000).toFixed(1);
      res.offsite = `${oAge} h alt`;
      if (oAge > maxAge) { res.problems.push(`offsite veraltet: ${oAge} h`); bump('warn'); }
    }
  }
  return res;
}

function writeReport(results, worst) {
  fs.mkdirSync(OUTDIR, { recursive: true });
  const file = path.join(OUTDIR, 'backup-audit.md');
  const ampel = worst === 'down' ? '🔴 rot' : worst === 'warn' ? '🟡 gelb' : '🟢 grün';
  const lines = [`# Backup-Audit`, '', `**Ampel:** ${ampel}  ·  ${results.length} Ziel(e)  ·  Stand ${L.localIso()}`, ''];
  for (const r of results) {
    const ic = r.state === 'down' ? '🔴' : r.state === 'warn' ? '🟡' : '🟢';
    lines.push(`## ${ic} ${r.name}`, '',
      `- Ordner: ${r.dir}`,
      `- Neuestes: ${r.newest ?? '—'}${r.size != null ? ` (${(r.size / 1048576).toFixed(1)} MB)` : ''}`,
      `- Alter: ${r.age_hours ?? '—'} h  ·  Integrität: ${r.integrity}  ·  Offsite: ${r.offsite}`);
    if (r.problems.length) lines.push(`- **Probleme:** ${r.problems.join('; ')}`);
    lines.push('');
  }
  lines.push('_Automatischer Backup-Audit (token-frei, read-only). Kein Restore, nichts verändert._', '');
  fs.writeFileSync(file, lines.join('\n'));
  return path.relative(L.BASE, file).split(path.sep).join('/');
}

function main() {
  const cfg = L.readJson(CFG, null);
  if (!cfg || typeof cfg !== 'object') fail('config/backups.json fehlt oder unlesbar');
  const targets = Array.isArray(cfg.backups) ? cfg.backups : [];

  if (!targets.length) {                                  // ehrlich: nicht konfiguriert, KEIN Alarm
    A.log('config/backups.json leer -> nicht konfiguriert');
    A.status('ok', 'Nicht konfiguriert', 100, 'Keine Backup-Ziele in config/backups.json — nichts zu prüfen.');
    process.stdout.write(JSON.stringify({ result: 'backup-auditor: nicht konfiguriert (config/backups.json leer)', engine: 'script' }) + '\n');
    process.exit(0);
  }

  A.status('running', 'Backup-Audit', 10, `${targets.length} Ziel(e)…`);
  const prevState = ((L.readJson(path.join(L.BASE, 'backup', '.state.json'), {}) || {}).state) || 'ok';
  const results = [];
  targets.forEach((t, i) => {
    results.push(auditTarget(t));
    A.status('running', 'Backup-Audit', 10 + Math.round(80 * (i + 1) / targets.length), `${t.name || t.dir} geprüft`);
  });

  let worst = 'ok';
  for (const r of results) { if (r.state === 'down') worst = 'down'; else if (r.state === 'warn' && worst !== 'down') worst = 'warn'; }

  const outputs = [writeReport(results, worst)];
  const bad = results.filter(r => r.state !== 'ok');
  if (bad.length) {
    fs.mkdirSync(ALERTDIR, { recursive: true });
    const af = path.join(ALERTDIR, `${L.isoDate()}_backup.md`);
    const al = [`# Backup-Alert · ${worst.toUpperCase()}`, '', `- **Zeit:** ${L.localIso()}`, '', '**Probleme:**',
      ...bad.map(r => `- ${r.name}: ${r.problems.join('; ')}`), '', '_Automatischer Entwurf. Kein Restore, kein Versand._', ''];
    try { fs.writeFileSync(af, al.join('\n')); outputs.push(path.relative(L.BASE, af).split(path.sep).join('/')); } catch (e) {}
  }

  try { L.atomicWrite(path.join(L.BASE, 'backup', '.state.json'), { state: worst, stand: L.localIso() }, 0); } catch (e) {}

  const details = results.map(r => `${r.name}: ${r.state === 'ok' ? 'ok' : r.state.toUpperCase()}${r.age_hours != null ? `, ${r.age_hours}h` : ''}${r.problems.length ? ` — ${r.problems[0]}` : ''}`);
  const summary = worst === 'ok' ? `Backups ok — ${results.length} Ziel(e)` : `Backups ${worst}: ${bad.map(r => r.name).join(', ')}`;
  A.status('ok', 'Fertig', 100, summary, details, outputs);

  const sev = { ok: 0, warn: 1, down: 2 };
  A.routine(worst === 'ok' ? `💾 **Backups** ok · ${results.length} Ziel(e)` : `${worst === 'down' ? '❌' : '⚠️'} **Backups** ${worst}: ${bad.map(r => r.name).join(', ')}`);
  if (sev[worst] > sev[prevState]) A.discord(CH_ALERT, `💾 **Backup ${worst}**: ${bad.map(r => r.name + ' (' + r.problems[0] + ')').join(' · ')}`);
  process.stdout.write(JSON.stringify({ result: summary, engine: 'script' }) + '\n');
  process.exit(0);
}

try { main(); } catch (e) { fail(String(e && e.stack || e)); }
