#!/usr/bin/env node
'use strict';
/* Agent-HQ Kern-Helfer (Node statt Python, damit es überall läuft, wo der
   Dashboard-Server läuft – auch auf Windows ohne Python).
   Aufrufe:
     node hq.js status  <status.json> <agent> <st> <phase> <prog> <msg> [details_json] [outputs_json]
     node hq.js model   <schedule.json> <agent>
     node hq.js cfg     <schedule.json> <agent> <key>
     node hq.js final   <status.json> <agent>          -> "status\tmessage"
     node hq.js record  <status.json> <jsonl> <agent> <t0> <t1> <rc> <model> <run>
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
  const tmp = f + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 1));
  fs.renameSync(tmp, f);
}

function cmdStatus() {
  const [f, agent, st, phase, prog, msg, det, out] = a;
  const d = readJson(f, { agents: {} }); d.agents = d.agents || {};
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
function cmdRecord() {
  const [f, jsonl, agent, t0, t1, rc, model, run] = a;
  const ag = (readJson(f, {}).agents || {})[agent] || {};
  const rec = {
    agent, run, t0, t1, rc: parseInt(rc, 10), model,
    status: ag.status || null, phase: ag.phase || null, message: ag.message || null,
    outputs: ag.outputs || [], log: `logs/${agent}/${run}.log`
  };
  fs.appendFileSync(jsonl, JSON.stringify(rec) + '\n');
}

const table = { status: cmdStatus, model: cmdModel, cfg: cmdCfg, final: cmdFinal, record: cmdRecord };
(table[cmd] || (() => { process.stderr.write('hq: unbekanntes Kommando ' + cmd + '\n'); process.exit(2); }))();
