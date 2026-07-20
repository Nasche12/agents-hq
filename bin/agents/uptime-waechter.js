#!/usr/bin/env node
'use strict';
/* TOKEN-FREIER uptime-waechter. Ersetzt den `claude -p`-Lauf 1:1 durch echte Messung.
   Regeln aus .claude/agents/uptime-waechter.md: jeder Wert aus echtem curl-Output,
   nie schaetzen, nie aus einem frueheren Lauf uebernehmen; im Zweifel ehrlich scheitern.
   Discord: nur ZUSTANDSWECHSEL melden (neu down / wieder oben / SSL kritisch) statt
   jede Stunde denselben Zustand – besser als die alte LLM-Version, kein Alarm-Spam. */
const fs = require('fs');
const path = require('path');
const L = require('./lib');

const A = L.agent('uptime-waechter');
const CFG = path.join(L.BASE, 'config', 'sites.json');
const OUT = path.join(L.BASE, 'uptime', 'uptime.json');
const ALERTDIR = path.join(L.BASE, 'uptime', 'alerts');
const MAX_HIST = 288;                                    // ~3 Tage bei 15-Min-Takt
const SLOW_MS = 3000, SSL_WARN = 21;
const CH_LOG = process.env.DISCORD_LOG_CHANNEL || 'agent-logs';
const CH_ALERT = process.env.DISCORD_COMMAND_CHANNEL || 'freigaben';

function sleepSync(ms) {
  try { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }
  catch (_) { const t = Date.now() + ms; while (Date.now() < t) {} }
}
function fail(msg) {                                     // ehrlicher harter Fehler -> run-agent.sh meldet error
  A.log('FEHLER: ' + msg);
  A.status('error', 'Abgebrochen', 0, msg.slice(0, 200));
  process.stdout.write(JSON.stringify({ result: 'uptime-waechter: ' + msg }) + '\n');
  process.exit(1);
}

/* <img src> aus HTML ziehen, relativ zur Site-URL aufloesen */
function imgUrls(html, baseUrl) {
  const out = [];
  const re = /<img\b[^>]*?\bsrc\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))/gi;
  let m;
  while ((m = re.exec(html)) && out.length < 40) {
    const src = (m[1] || m[2] || m[3] || '').trim();
    if (!src || src.startsWith('data:')) continue;
    try { out.push(new URL(src, baseUrl).href); } catch (e) {}
  }
  return [...new Set(out)];
}

/* Eine Site vollstaendig messen (jeder Wert echt) */
function measure(site) {
  const url = site.url;
  const met = L.curlMetric(url);
  const r = { name: site.name || url, url, http: met.http, ms: met.ms, ssl_days: null,
    expect_ok: null, assets: 'n/a', db: 'n/a', state: 'ok', reason: '' };
  const reasons = [];

  // Erreichbarkeit
  const reachable = met.ok && met.http != null && met.http < 400;
  if (!reachable) { r.state = 'down'; reasons.push(met.ok ? `HTTP ${met.http}` : (met.err || 'nicht erreichbar')); }

  // TLS-Restlaufzeit (nur https)
  if (/^https:/i.test(url)) {
    r.ssl_days = L.sslDaysLeft(url);
    if (r.ssl_days == null && reachable) reasons.push('TLS-Ablauf nicht lesbar');
  }

  // Inhalt + Bilder brauchen den Body – nur laden, wenn erreichbar
  let html = '';
  if (reachable && (site.expect || site.assets)) {
    const b = L.curlBody(url);
    html = b.body || '';
  }
  if (site.expect) {
    r.expect_ok = reachable && html.includes(site.expect);
    if (reachable && !r.expect_ok) { r.state = 'down'; reasons.push(`Inhalt "${site.expect}" fehlt`); }
  }
  if (site.assets && reachable) {
    let list = [];
    if (site.assets === 'auto') list = imgUrls(html, url);
    else if (Array.isArray(site.assets)) list = site.assets.map(p => { try { return new URL(p, url).href; } catch (e) { return null; } }).filter(Boolean);
    if (!list.length) { r.assets = 'n/a'; }
    else {
      let broken = 0; const badUrls = [];
      for (const iu of list) { const a = L.curlAsset(iu); if (!a.ok) { broken++; if (badUrls.length < 8) badUrls.push(iu); } }
      r.assets = broken ? `${broken} kaputt` : 'ok';
      if (broken) { reasons.push(`${broken} Bild(er) kaputt`); r._broken_imgs = badUrls; }
    }
  }
  if (site.health) {
    const code = L.curlStatus(site.health, { head: false });
    const alive = code != null && code < 500;            // <500 (auch 401/403) = lebt
    r.db = alive ? 'ok' : 'down';
    if (!alive) { r.state = 'down'; reasons.push('Backend/DB down' + (code ? ` (HTTP ${code})` : ' (Timeout/DNS)')); }
  }

  // slow nur, wenn sonst funktional
  if (r.state !== 'down' && r.ms != null && r.ms >= SLOW_MS) { r.state = 'slow'; reasons.push(`langsam ${r.ms} ms`); }
  r.reason = reasons.join('; ');
  return r;
}

function main() {
  const cfg = L.readJson(CFG, null);
  if (!cfg || !Array.isArray(cfg.sites) || !cfg.sites.length) fail('config/sites.json fehlt oder leer');
  if (!L.haveTool('curl')) fail("'curl' nicht gefunden – ohne curl keine echte Messung");

  A.status('running', 'Messe Sites', 10, `${cfg.sites.length} Sites…`);
  const prev = L.readJson(OUT, { sites: [] });
  const prevBy = {}; for (const s of (prev.sites || [])) prevBy[s.name] = s;

  const results = [];
  cfg.sites.forEach((site, i) => {
    A.log(`messe ${site.name}…`);
    let r = measure(site);
    if (r.state === 'down') {                             // Ein Fehlversuch ist kein Ausfall: nach ~10 s erneut
      A.log(`${site.name} sieht down aus – Nachmessung in 10 s`);
      sleepSync(10000);
      const r2 = measure(site);
      if (r2.state !== 'down') { r2.reason = (r2.reason ? r2.reason + '; ' : '') + '(erst beim 2. Versuch ok)'; r = r2; }
      else { r.reason += '; 2× bestaetigt'; r = r2; }
    }
    results.push(r);
    A.status('running', 'Messe Sites', 10 + Math.round(80 * (i + 1) / cfg.sites.length), `${site.name}: ${r.state}`);
  });

  // uptime.json + Historie schreiben (atomar; Schema wie bisher, Historie waechst deterministisch)
  const now = L.localIso();
  const data = L.readJson(OUT, { stand: now, sites: [], history: [] });
  data.stand = now;
  data.sites = results.map(({ _broken_imgs, ...s }) => s);
  data.history = Array.isArray(data.history) ? data.history : [];
  data.history.push({ t: now, p: results.map(s => ({ n: s.name, ms: s.ms, ssl: s.ssl_days, up: (s.state === 'ok' || s.state === 'slow') ? 1 : 0 })) });
  if (data.history.length > MAX_HIST) data.history = data.history.slice(-MAX_HIST);
  L.atomicWrite(OUT, data, 1);
  A.log(`uptime.json geschrieben: ${results.length} Sites, ${data.history.length} Historienpunkte`);

  // Alerts + Zustandswechsel-Meldungen
  fs.mkdirSync(ALERTDIR, { recursive: true });
  const outputs = [];
  for (const r of results) {
    const wasDown = prevBy[r.name] && !(prevBy[r.name].state === 'ok' || prevBy[r.name].state === 'slow');
    const isDown = r.state === 'down';
    const sslBad = r.ssl_days != null && r.ssl_days < SSL_WARN;
    const imgsBad = typeof r.assets === 'string' && r.assets.endsWith('kaputt');

    if (isDown || sslBad || imgsBad) {                    // Alert-Entwurf ablegen (ein File pro Site/Tag)
      const f = path.join(ALERTDIR, `${L.isoDate()}_${L.slug(r.name)}.md`);
      const lines = [
        `# uptime-Alert · ${r.name}`, '', `- **Zeit:** ${now}`, `- **URL:** ${r.url}`, `- **Status:** ${r.state}`,
        `- **HTTP:** ${r.http ?? '–'}   **Zeit:** ${r.ms ?? '–'} ms   **SSL-Tage:** ${r.ssl_days ?? '–'}`,
        `- **Befund:** ${r.reason || '—'}`
      ];
      if (r._broken_imgs && r._broken_imgs.length) lines.push('', '**Kaputte Bilder:**', ...r._broken_imgs.map(u => '- ' + u));
      lines.push('', '_Automatischer Entwurf (uptime-waechter, token-frei). Kein Versand._', '');
      try { fs.writeFileSync(f, lines.join('\n')); outputs.push(path.relative(L.BASE, f).split(path.sep).join('/')); } catch (e) {}
    }

    // Discord nur bei WECHSEL (kein Stunden-Spam)
    if (isDown && !wasDown) A.discord(CH_ALERT, `❌ **${r.name}** ist DOWN — ${r.reason || 'nicht erreichbar'}.`);
    else if (!isDown && wasDown) A.discord(CH_LOG, `✅ **${r.name}** wieder oben (${r.state}, ${r.ms ?? '–'} ms).`);
    else if (sslBad) A.discord(CH_ALERT, `⚠️ **${r.name}** SSL laeuft in ${r.ssl_days} Tagen ab.`);
    else if (imgsBad && !wasDown) A.discord(CH_LOG, `⚠️ **${r.name}**: ${r.assets} Bild(er) laden nicht.`);
  }

  // Endstatus
  const down = results.filter(r => r.state === 'down');
  const slow = results.filter(r => r.state === 'slow');
  const details = results.map(r => `${r.name}: ${r.http ?? '–'}, ${r.ms ?? '–'} ms, SSL ${r.ssl_days ?? '–'} T` +
    (r.db !== 'n/a' ? `, DB ${r.db}` : '') + (r.state !== 'ok' ? ` — ${r.state}` : ''));
  const up = results.length - down.length;
  const summary = down.length
    ? `${up}/${results.length} oben — DOWN: ${down.map(r => r.name).join(', ')}`
    : (slow.length ? `${results.length}/${results.length} oben, ${slow.length} langsam` : `${results.length}/${results.length} Sites oben ✓`);

  A.status('ok', 'Fertig', 100, summary, details, outputs);

  // Routine-Zeile in den Themen-Kanal – JEDEN Lauf, genau wie der LLM-Agent (respektiert quiet).
  const okMs = results.map(r => r.ms).filter(x => x != null);
  const avgMs = okMs.length ? Math.round(okMs.reduce((a, b) => a + b, 0) / okMs.length) : null;
  const sslVals = results.map(r => r.ssl_days).filter(x => x != null);
  const sslMin = sslVals.length ? Math.min(...sslVals) : null;
  // Nur 1×/Stunde posten (gemessen wird trotzdem alle 15 min) – aber ein echter
  // Zustandswechsel (Site kippt/erholt sich) kommt sofort durch (force).
  const prevDown = new Set((prev.sites || []).filter(s => !(s.state === 'ok' || s.state === 'slow')).map(s => s.name));
  const curDown = new Set(down.map(r => r.name));
  const changed = prevDown.size !== curDown.size || [...curDown].some(n => !prevDown.has(n));
  A.routine(down.length
    ? `⚠️ **uptime** ${up}/${results.length} oben — DOWN: ${down.map(r => r.name).join(', ')}`
    : `✅ **uptime** ${results.length}/${results.length} oben${avgMs != null ? ` · ⌀${avgMs} ms` : ''}${sslMin != null ? ` · SSL min ${sslMin} T` : ''}${slow.length ? ` · ${slow.length} langsam` : ''}`,
    { minMinutes: 60, force: changed });
  process.stdout.write(JSON.stringify({ result: summary, engine: 'script' }) + '\n');
  process.exit(0);
}

try { main(); } catch (e) { fail(String(e && e.stack || e)); }
