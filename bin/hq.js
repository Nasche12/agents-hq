#!/usr/bin/env node
'use strict';
/* Agent-HQ Kern-Helfer (Node statt Python, damit es überall läuft, wo der
   Dashboard-Server läuft – auch auf Windows ohne Python).
   Aufrufe:
     node hq.js status  <status.json> <agent> <st> <phase> <prog> <msg> [details_json] [outputs_json]
     node hq.js model   <schedule.json> <agent>
     node hq.js cfg     <schedule.json> <agent> <key>
     node hq.js final   <status.json> <agent>          -> "status\tmessage"
     node hq.js record  <status.json> <jsonl> <agent> <t0> <t1> <rc> <model> <run> [claude.json]
     node hq.js resulttext <claude.json>                -> lesbarer Ergebnistext (fuers Live-Log)
     node hq.js srvhist <server-status.json> <history.jsonl> <history.json>
*/
const fs = require('fs');
const path = require('path');
const [cmd, ...a] = process.argv.slice(2);

/* Lokale ISO-Zeit mit Offset (wie Pythons datetime.astimezone().isoformat) */
function localIso(d = new Date()) {
  const off = -d.getTimezoneOffset(), s = off >= 0 ? '+' : '-';
  const two = n => String(Math.floor(Math.abs(n))).padStart(2, '0');
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` +
    `${s}${two(off / 60)}:${two(Math.abs(off) % 60)}`;
}
const readJson = (f, fb) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return fb; } };
function writeAtomic(f, obj) {
  // Eindeutiger Tmp-Name je Schreiber: sonst kollidieren parallele Agents + Scheduler
  // auf demselben "*.tmp" und die renameSync interleaven -> Korruption/ENOENT.
  const tmp = f + '.tmp.' + process.pid + '.' + Math.floor(Math.random() * 1e9);
  try { fs.writeFileSync(tmp, JSON.stringify(obj, null, 1)); fs.renameSync(tmp, f); }
  catch (e) { try { fs.unlinkSync(tmp); } catch (_) {} throw e; }
}

function cmdStatus() {
  const [f, agent, st, phase, prog, msg, det, out] = a;
  let d = readJson(f, null);
  if (d === null) {
    // Datei fehlt ODER ist korrupt. Ist sie korrupt (existiert + nicht leer), einmal als
    // .bad sichern, statt still alle anderen Agent-Status zu ueberschreiben.
    try { if (fs.existsSync(f) && fs.statSync(f).size > 0) fs.copyFileSync(f, f + '.bad'); } catch (e) {}
    d = { agents: {} };
  }
  d.agents = d.agents || {};
  const ag = d.agents[agent] || (d.agents[agent] = { name: agent });
  ag.status = st; ag.phase = phase; ag.progress = parseInt(prog, 10) || 0; ag.message = msg;
  const now = localIso();
  if (st === 'running') ag.last_run = now;
  if (det) { try { ag.details = JSON.parse(det); } catch (e) {} }
  if (out) { try { ag.outputs = JSON.parse(out); } catch (e) {} }
  try {
    const lf = path.join(path.dirname(f), '..', 'logs', agent + '.log');
    ag.log_tail = fs.readFileSync(lf, 'utf8').slice(-1500);
  } catch (e) {}
  d.updated = now;
  writeAtomic(f, d);
}
function cmdModel() {
  const [f, agent] = a;
  const ag = (readJson(f, {}).agents || {})[agent] || {};
  // Default: alles haiku (guenstig). Pro Agent gezielt anheben via "model":"sonnet"|"opus"
  // in config/schedule.json. 'schwer' steuert NUR noch die Auto-Start-Freigabe, nicht das Modell.
  console.log(ag.model || 'haiku');
}
function cmdCfg() {
  const [f, agent, key] = a;
  const ag = (readJson(f, {}).agents || {})[agent] || {};
  const v = ag[key];
  console.log(v == null ? '' : String(v));
}
function cmdFinal() {
  const [f, agent] = a;
  const ag = (readJson(f, {}).agents || {})[agent] || {};
  process.stdout.write((ag.status || '') + '\t' + (ag.message || ''));
}
/* Token-/Kosten-Nutzung defensiv aus dem `claude -p --output-format json`-Objekt
   ziehen. Feldnamen koennen sich zwischen CLI-Versionen leicht unterscheiden, daher
   mehrere Fallbacks. Gibt null zurueck, wenn wirklich nichts Verwertbares drinsteht. */
function pickNum(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
function extractUsage(j) {
  if (!j || typeof j !== 'object') return null;
  const u = j.usage || (j.result && typeof j.result === 'object' && j.result.usage) || {};
  const inp = pickNum(u.input_tokens);
  const out = pickNum(u.output_tokens);
  const cw = pickNum(u.cache_creation_input_tokens != null ? u.cache_creation_input_tokens : u.cache_creation_tokens);
  const cr = pickNum(u.cache_read_input_tokens != null ? u.cache_read_input_tokens : u.cache_read_tokens);
  const cost = pickNum(j.total_cost_usd != null ? j.total_cost_usd : (j.cost_usd != null ? j.cost_usd : j.total_cost));
  const turns = pickNum(j.num_turns);
  const durMs = pickNum(j.duration_ms);
  const durApi = pickNum(j.duration_api_ms);
  const modelUsed = j.model || (j.modelUsage && Object.keys(j.modelUsage)[0]) || null;
  if (inp == null && out == null && cost == null) return null;
  const tokens = (inp || 0) + (out || 0) + (cw || 0) + (cr || 0);
  return {
    input: inp, output: out, cache_write: cw, cache_read: cr,
    tokens, cost_usd: cost, turns, duration_ms: durMs, duration_api_ms: durApi,
    model_used: modelUsed
  };
}

function cmdRecord() {
  const [f, jsonl, agent, t0, t1, rc, model, run, cjson] = a;
  const ag = (readJson(f, {}).agents || {})[agent] || {};
  const rec = {
    agent, run, t0, t1, rc: parseInt(rc, 10), model,
    status: ag.status || null, phase: ag.phase || null, message: ag.message || null,
    outputs: ag.outputs || [], log: `logs/${agent}/${run}.log`
  };
  if (cjson) {
    const usage = extractUsage(readJson(cjson, null));
    if (usage) {
      rec.usage = usage;               // volle Aufschluesselung
      rec.tokens = usage.tokens;       // Bequemlichkeit fuers Dashboard
      rec.cost_usd = usage.cost_usd;
    }
  }
  fs.appendFileSync(jsonl, JSON.stringify(rec) + '\n');
}

/* Lesbaren Ergebnistext aus dem claude-JSON ziehen (fuers Live-/Run-Log). Faellt auf
   den Rohinhalt zurueck, wenn es kein sauberes JSON ist – damit nie Output verloren geht. */
function cmdResultText() {
  const [cjson] = a;
  let raw = '';
  try { raw = fs.readFileSync(cjson, 'utf8'); } catch (e) { return; }
  let j = null; try { j = JSON.parse(raw); } catch (e) {}
  if (j && typeof j === 'object') {
    const txt = typeof j.result === 'string' ? j.result
      : (j.result && typeof j.result === 'object' && typeof j.result.text === 'string' ? j.result.text : '');
    if (txt) { process.stdout.write(txt.trim() + '\n'); return; }
    if (j.is_error && (j.error || j.subtype)) { process.stdout.write('[' + (j.subtype || 'error') + '] ' + (j.error || '') + '\n'); return; }
  }
  process.stdout.write(raw.trim() ? raw.trim().slice(0, 4000) + '\n' : '');
}

/* Einen kompakten Server-Snapshot an die Historie anhaengen (fuer Verlaufsgraphen).
   Schreibt sowohl ein append-only JSONL (Rohverlauf) als auch ein rollendes JSON-Array
   (letzte 500) fuers Dashboard – letzteres wird ins Docroot gespiegelt. */
function cmdSrvHist() {
  const [statusFile, jsonl, jsonArr] = a;
  const s = readJson(statusFile, null);
  if (!s || typeof s !== 'object') return;
  const disk = s.disk || {}, mem = s.memory || {}, load = s.load || {}, logins = s.logins || {};
  const sample = {
    t: s.stand || localIso(),
    state: s.state || null,
    disk: pickNum(disk.used_percent),
    disk_free_gb: pickNum(disk.free_gb),
    mem: pickNum(mem.used_percent),
    mem_used_gb: pickNum(mem.used_gb),
    load: pickNum(load.per_core),
    ssl: pickNum(s.ssl_min_days),
    log_mb: pickNum(s.log_dir_mb),
    failed_ssh: pickNum(logins.failed_ssh),
    services_up: Array.isArray(s.services) ? s.services.filter(x => x && x.active).length : null,
    services_total: Array.isArray(s.services) ? s.services.length : null,
    db_up: Array.isArray(s.databases) ? s.databases.filter(x => x && x.active).length : null,
    db_total: Array.isArray(s.databases) ? s.databases.length : null,
    backups_ok: Array.isArray(s.backups) ? s.backups.filter(x => x && x.ok).length : null,
    backups_total: Array.isArray(s.backups) ? s.backups.length : null
  };
  try { fs.appendFileSync(jsonl, JSON.stringify(sample) + '\n'); } catch (e) {}
  if (jsonArr) {
    let all = [];
    try {
      all = fs.readFileSync(jsonl, 'utf8').split('\n').filter(Boolean)
        .map(l => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean);
    } catch (e) { all = [sample]; }
    writeAtomic(jsonArr, all.slice(-500));
  }
}

const table = { status: cmdStatus, model: cmdModel, cfg: cmdCfg, final: cmdFinal, record: cmdRecord, resulttext: cmdResultText, srvhist: cmdSrvHist };
(table[cmd] || (() => { process.stderr.write('hq: unbekanntes Kommando ' + cmd + '\n'); process.exit(2); }))();
