'use strict';
/* Zusatz-Checks fuer seo-audit.js, alle TOKEN-FREI:
     runGeo   -> bin/lib/geo_audit.py (Python-stdlib; Bot-Matrix, WAF, noindex, SPA, JSON-LD, Drift)
     psi      -> PageSpeed Insights v5 (Core Web Vitals; Felddaten + Lab)
     gsc      -> Search Console (optional, nur mit GSC_CREDENTIALS)
   Jede Funktion liefert {findings, measurements, notMeasured}. Was nicht gemessen werden
   konnte, landet in notMeasured – es zaehlt NIE als bestanden. Netzwerk-Funktionen sind
   in seo-audit.js per `deps` ersetzbar (Tests). */
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const L = require('./lib');

const pyCmd = () => process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
/* Temp-Verzeichnisse, die bei Abbruch (SIGTERM) aufgeraeumt werden muessen. */
const tmpDirs = new Set();
function mkTmp(prefix) { const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); tmpDirs.add(d); return d; }
function rmTmp(d) { tmpDirs.delete(d); try { fs.rmSync(d, { recursive: true, force: true }); } catch (e) {} }
function cleanupTmp() { for (const d of [...tmpDirs]) rmTmp(d); }
const GEO = path.join(L.BASE, 'bin', 'lib', 'geo_audit.py');
const SEV_MAP = { critical: 'kritisch', high: 'hoch', medium: 'mittel', low: 'niedrig' };   // info entfaellt
/* Bereiche, die seo-audit.js selbst (mit eigenem Fix-Katalog) abdeckt -> nicht doppelt melden. */
const GEO_SKIP_AREA = new Set(['On-page', 'Internal links']);
const empty = () => ({ findings: [], measurements: [], notMeasured: [] });

/* ---------- geo_audit.py ---------- */
function mapGeoResult(res) {
  const out = empty();
  for (const f of res.findings || []) {
    const sev = SEV_MAP[f.severity];
    if (!sev || GEO_SKIP_AREA.has(f.area) || /^No canonical/.test(f.issue)) continue;
    const proxy = /CDN|WAF/i.test(f.area) || /SPA|shell/i.test(f.issue);
    out.findings.push({
      sev, was: `${f.area}: ${f.issue}`, fix: f.fix, url: f.url || res.origin,
      evidence: f.evidence ? String(f.evidence).slice(0, 200) : '', label: proxy ? 'proxy' : 'gemessen', quelle: 'geo_audit'
    });
  }
  const m = (res.robots && res.robots.matrix) || {};
  const bots = Object.entries(m);
  if (bots.length) {
    const blocked = bots.filter(([, v]) => !v.root_allowed).map(([b]) => b);
    out.measurements.push({ text: `robots.txt: ${bots.length - blocked.length}/${bots.length} Bots (inkl. KI-Bots) für "/" erlaubt` + (blocked.length ? `, blockiert: ${blocked.join(', ')}` : ''), label: 'gemessen' });
  } else if (res.robots && res.robots.mode === 'allow-all') {
    out.measurements.push({ text: 'robots.txt: keine Datei (4xx) = alle Bots erlaubt', label: 'gemessen' });
  }
  if (res.ua_test) {
    const bad = Object.entries(res.ua_test).filter(([, s]) => !/^2\d\d$/.test(String(s))).map(([b, s]) => `${b}=${s}`);
    out.measurements.push({ text: `Bot-User-Agent-Test: ${bad.length ? 'abweichend: ' + bad.join(', ') : 'alle 2xx'} (nur Indiz, eigene IP)`, label: 'proxy' });
  } else out.notMeasured.push('Bot-User-Agent-Test (WAF-Blocks) nicht gelaufen');
  const pages = res.pages || [];
  const words = pages.filter(p => p.words != null).map(p => `${p.words}`);
  if (words.length) out.measurements.push({ text: `Wörter im Roh-HTML je Seite: ${words.join(' / ')} (ohne JavaScript)`, label: 'gemessen' });
  return out;
}

/* Baseline je Site: <baseDir>/<slug>.json (slug = Host). Erster Lauf legt sie an, danach --compare (Drift).
   SEO_BASELINE_REFRESH=1 schreibt sie nach einer gewollten Aenderung neu (dann OHNE --compare).
   Defekte Baseline -> nach .corrupt umbenennen und neu anlegen. Geschrieben wird atomar (Temp-Datei + rename).
   dry = nichts schreiben. */
function runGeo(url, { baseDir, slug, dry }) {
  const tmp = mkTmp('seo-geo-');
  const jsonOut = path.join(tmp, 'r.json');
  const baseline = path.join(baseDir, slug + '.json');
  const refresh = process.env.SEO_BASELINE_REFRESH === '1';
  const notes = [];
  let hasBase = fs.existsSync(baseline);
  if (hasBase) {
    try { JSON.parse(fs.readFileSync(baseline, 'utf8')); } catch (e) {
      hasBase = false;
      if (!dry) { try { fs.renameSync(baseline, baseline + '.corrupt'); } catch (e2) {} }
      notes.push('Baseline war defekt' + (dry ? ' (Dry-Run: nicht ersetzt)' : ' (nach .corrupt verschoben, neu angelegt)'));
    }
  }
  const compare = hasBase && !refresh;
  const save = !dry && (!hasBase || refresh);
  const tmpBase = path.join(tmp, 'baseline.json');
  const args = ['-I', GEO, url, '--pages', '5', '--ua-test', '--json', jsonOut, '--md', path.join(tmp, 'r.md')];
  if (compare) args.push('--compare', baseline);
  if (save) args.push('--save-baseline', tmpBase);
  try {
    const r = L.run(pyCmd(), args, { timeoutMs: 300000 });
    if (r.code !== 0 && r.code !== 2) {                // 2 = kritische Befunde (kein Fehler)
      return { ...empty(), notMeasured: [`geo_audit.py nicht gelaufen (${pyCmd()}, Exit ${r.code}): ${(r.err || '').trim().split('\n').pop().slice(0, 160)}`], geoFailed: true };
    }
    const res = JSON.parse(fs.readFileSync(jsonOut, 'utf8'));
    const out = mapGeoResult(res);
    if (save) {                                         // atomar ersetzen; JSON vorher pruefen
      JSON.parse(fs.readFileSync(tmpBase, 'utf8'));
      fs.mkdirSync(baseDir, { recursive: true });
      fs.copyFileSync(tmpBase, baseline + '.tmp');
      fs.renameSync(baseline + '.tmp', baseline);
    }
    const txt = compare ? 'Drift-Vergleich gegen Baseline' : refresh && !dry ? 'Baseline erneuert (SEO_BASELINE_REFRESH, kein Drift-Vergleich)' : save ? 'Baseline neu angelegt (Drift ab nächstem Lauf)' : 'keine Baseline (Dry-Run)';
    out.measurements.push({ text: [txt, ...notes].join('; '), label: 'gemessen' });
    if (!compare) out.notMeasured.push('Drift-Vergleich: in diesem Lauf nicht möglich (Baseline neu/erneuert/Dry-Run)');
    return out;
  } catch (e) {
    return { ...empty(), notMeasured: ['geo_audit.py Ausgabe nicht lesbar: ' + String(e.message || e).slice(0, 160)], geoFailed: true };
  } finally { rmTmp(tmp); }
}

/* Body-Datei fuer curl: eigenes 0700-Verzeichnis, Datei 0600 (Tokens nicht fuer andere User lesbar). */
function writeBodyFile(body) {
  const dir = mkTmp('seo-body-');
  const file = path.join(dir, 'b');
  fs.writeFileSync(file, typeof body === 'string' ? body : JSON.stringify(body), { mode: 0o600, flag: 'wx' });
  return { dir, file };
}

/* ---------- HTTP-JSON ueber curl (Key/Token nie in der Prozessliste: curl-Config per stdin) ---------- */
const cq = s => '"' + String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
function httpJson(url, { headers = [], body, timeout = 90 } = {}) {
  let cfg = `url = ${cq(url)}\nsilent\nshow-error\nmax-time = ${timeout}\n`;
  for (const h of headers) cfg += `header = ${cq(h)}\n`;
  let bf = null;
  try {
    if (body != null) { bf = writeBodyFile(body); cfg += `data-binary = ${cq('@' + bf.file)}\n`; }
    const r = L.run('curl', ['-K', '-'], { timeoutMs: (timeout + 6) * 1000, input: cfg });
    try { return { json: JSON.parse(r.out) }; } catch (e) { return { error: (r.err || r.out || 'keine Antwort').trim().slice(0, 200) }; }
  } finally { if (bf) rmTmp(bf.dir); }
}

/* ---------- Core Web Vitals (PageSpeed Insights v5, mobile) ---------- */
function psiFetch(url) {
  const key = process.env.PAGESPEED_API_KEY;
  const api = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed?strategy=mobile&category=performance&url=' +
    encodeURIComponent(url) + (key ? '&key=' + encodeURIComponent(key) : '');
  return httpJson(api, { timeout: 100 });
}
/* web.dev-Schwellen: gut <= a, schlecht > b */
const CWV = {
  lcp: { a: 2500, b: 4000, name: 'LCP', unit: 'ms', fmt: v => (v / 1000).toFixed(2) + ' s', fix: 'Hero-Bild/Schrift priorisieren (preload, fetchpriority), Bilder komprimieren, Server-Antwortzeit senken.' },
  inp: { a: 200, b: 500, name: 'INP', unit: 'ms', fmt: v => Math.round(v) + ' ms', fix: 'Lange JavaScript-Aufgaben aufteilen, Drittanbieter-Skripte reduzieren.' },
  cls: { a: 0.1, b: 0.25, name: 'CLS', unit: '', fmt: v => v.toFixed(2), fix: 'Bildern/Einbettungen feste Breite+Höhe geben, Schrift-Nachladen ohne Layout-Sprung.' }
};
function cwvFindings(resp, url) {
  const out = empty();
  if (!resp || resp.error || !resp.json || resp.json.error) {
    const msg = (resp && (resp.error || (resp.json && resp.json.error && resp.json.error.message))) || 'keine Antwort';
    out.notMeasured.push('Core Web Vitals (PageSpeed Insights nicht erreichbar/Limit): ' + String(msg).slice(0, 140));
    return out;
  }
  const j = resp.json;
  const fe = j.loadingExperience && j.loadingExperience.metrics ? { m: j.loadingExperience.metrics, scope: 'URL' }
    : (j.originLoadingExperience && j.originLoadingExperience.metrics ? { m: j.originLoadingExperience.metrics, scope: 'Origin' } : null);
  const val = {};
  if (fe) {
    const g = k => fe.m[k] && Number.isFinite(fe.m[k].percentile) ? fe.m[k].percentile : null;
    val.lcp = g('LARGEST_CONTENTFUL_PAINT_MS'); val.inp = g('INTERACTION_TO_NEXT_PAINT');
    const c = g('CUMULATIVE_LAYOUT_SHIFT_SCORE'); val.cls = c == null ? null : c / 100;
  }
  const parts = [];
  for (const k of ['lcp', 'inp', 'cls']) {
    const t = CWV[k], v = val[k];
    if (v == null) { out.notMeasured.push(`Core Web Vitals ${t.name}: keine Felddaten (CrUX) – nicht gemessen`); continue; }
    parts.push(`${t.name} ${t.fmt(v)}`);
    if (v > t.b) out.findings.push({ sev: 'hoch', was: `Core Web Vitals: ${t.name} schlecht (${t.fmt(v)}, p75, Grenze ${t.fmt(t.b)})`, fix: t.fix, url, label: 'gemessen', quelle: 'psi' });
    else if (v > t.a) out.findings.push({ sev: 'mittel', was: `Core Web Vitals: ${t.name} verbesserungswürdig (${t.fmt(v)}, p75, gut ≤ ${t.fmt(t.a)})`, fix: t.fix, url, label: 'gemessen', quelle: 'psi' });
  }
  if (parts.length) out.measurements.push({ text: `Core Web Vitals Felddaten (CrUX p75, ${fe.scope}): ${parts.join(', ')}`, label: 'gemessen' });
  const sc = j.lighthouseResult && j.lighthouseResult.categories && j.lighthouseResult.categories.performance
    ? j.lighthouseResult.categories.performance.score : null;
  if (typeof sc === 'number') {
    const p = Math.round(sc * 100);
    out.measurements.push({ text: `Lighthouse-Performance (Labor, mobil, simuliert): ${p}/100`, label: 'proxy' });
    if (p < 50) out.findings.push({ sev: 'mittel', was: `Lighthouse-Performance mobil niedrig (${p}/100, Labor-Proxy)`, fix: 'Größte Bremsen im PageSpeed-Bericht der URL abarbeiten (Bilder, JS, Render-Blocker).', url, label: 'proxy', quelle: 'psi' });
  } else out.notMeasured.push('Lighthouse-Performance (Labor) nicht geliefert');
  return out;
}
function psi(url, fetchFn = psiFetch) {
  if (fetchFn === psiFetch && !process.env.PAGESPEED_API_KEY) {      // ohne Key liefert die API "Quota exceeded"
    const o = empty();
    o.notMeasured.push('CWV: nicht gemessen (kein API-Key, PAGESPEED_API_KEY nicht gesetzt)');
    return o;
  }
  let r;
  try { r = fetchFn(url); } catch (e) { r = { error: String(e.message || e) }; }
  return cwvFindings(r, url);
}

/* ---------- Search Console (optional) ---------- */
const b64u = b => Buffer.from(b).toString('base64url');
function gscToken(cred) {
  const now = Math.floor(Date.now() / 1000);
  const head = b64u(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const claim = b64u(JSON.stringify({ iss: cred.client_email, scope: 'https://www.googleapis.com/auth/webmasters.readonly', aud: 'https://oauth2.googleapis.com/token', iat: now, exp: now + 3000 }));
  const sig = crypto.sign('RSA-SHA256', Buffer.from(head + '.' + claim), cred.private_key).toString('base64url');
  const r = httpJson('https://oauth2.googleapis.com/token', { body: 'grant_type=' + encodeURIComponent('urn:ietf:params:oauth:grant-type:jwt-bearer') + '&assertion=' + head + '.' + claim + '.' + sig, headers: ['Content-Type: application/x-www-form-urlencoded'], timeout: 30 });
  return r.json && r.json.access_token ? r.json.access_token : null;
}
/* Gibt {cur, prev, inspect} oder {error}. Credentials nur per Env-Pfad GSC_CREDENTIALS (Service-Account-JSON). */
function gscFetch(site, homeUrl) {
  let cred;
  try { cred = JSON.parse(fs.readFileSync(process.env.GSC_CREDENTIALS, 'utf8')); } catch (e) { return { error: 'GSC_CREDENTIALS nicht lesbar' }; }
  let token = null;
  try { token = gscToken(cred); } catch (e) { return { error: 'Token-Signatur fehlgeschlagen (private_key/client_email prüfen)' }; }
  if (!token) return { error: 'Token-Abruf fehlgeschlagen (Service-Account prüfen)' };
  const host = new URL(homeUrl).hostname.replace(/^www\./, '');
  const prop = site.gsc || 'sc-domain:' + host;
  const H = ['Authorization: Bearer ' + token, 'Content-Type: application/json'];
  const day = d => new Date(Date.now() - d * 86400000).toISOString().slice(0, 10);   // GSC-Daten ~3 Tage verzoegert
  const q = (s, e) => {
    const r = httpJson(`https://www.googleapis.com/webmasters/v3/sites/${encodeURIComponent(prop)}/searchAnalytics/query`, { headers: H, body: { startDate: day(s), endDate: day(e) }, timeout: 40 });
    if (r.json && r.json.error) throw new Error((r.json.error.message || 'API-Fehler').slice(0, 120));
    if (!r.json) throw new Error(r.error);
    const row = (r.json.rows || [])[0] || { clicks: 0, impressions: 0, ctr: 0, position: 0 };
    return { clicks: row.clicks, impressions: row.impressions, ctr: row.ctr, position: row.position };
  };
  try {
    const cur = q(30, 3), prev = q(58, 31);
    const ins = httpJson('https://searchconsole.googleapis.com/v1/urlInspection/index:inspect', { headers: H, body: { inspectionUrl: homeUrl, siteUrl: prop }, timeout: 40 });
    const idx = ins.json && ins.json.inspectionResult && ins.json.inspectionResult.indexStatusResult;
    return { prop, cur, prev, inspect: idx ? { verdict: idx.verdict, coverage: idx.coverageState } : null };
  } catch (e) { return { error: `Property ${prop}: ${e.message}` }; }
}
function gsc(site, homeUrl, fetchFn = gscFetch) {
  const out = empty();
  if (!process.env.GSC_CREDENTIALS && fetchFn === gscFetch) {
    out.notMeasured.push('GSC: nicht angebunden (GSC_CREDENTIALS nicht gesetzt)');
    return out;
  }
  let r;
  try { r = fetchFn(site, homeUrl); } catch (e) { r = { error: String(e.message || e).slice(0, 140) }; }
  if (!r || r.error) { out.notMeasured.push('GSC: ' + ((r && r.error) || 'keine Antwort')); return out; }
  const { cur, prev } = r, n = x => (x == null ? 0 : x);
  const pct = (a, b) => (b ? Math.round((a - b) / b * 100) : null);
  const dc = pct(cur.clicks, prev.clicks), di = pct(cur.impressions, prev.impressions);
  out.measurements.push({ text: `GSC 28 Tage (${r.prop || site.name}): ${Math.round(cur.clicks)} Klicks (${dc == null ? 'n/a' : (dc >= 0 ? '+' : '') + dc + ' %'} vs. Vorperiode), ${Math.round(cur.impressions)} Impressionen (${di == null ? 'n/a' : (di >= 0 ? '+' : '') + di + ' %'}), CTR ${(n(cur.ctr) * 100).toFixed(1)} %, Ø Position ${n(cur.position).toFixed(1)}`, label: 'gemessen' });
  if (cur.impressions === 0) out.findings.push({ sev: 'mittel', was: 'GSC: keine Impressionen in 28 Tagen', fix: 'Property/Sitemap in der Search Console prüfen; Seite wird in der Suche nicht ausgespielt.', url: homeUrl, label: 'gemessen', quelle: 'gsc' });
  else if (dc != null && dc <= -30 && prev.clicks >= 20) out.findings.push({ sev: 'mittel', was: `GSC: Klicks ${dc} % gegenüber Vorperiode (${Math.round(prev.clicks)} → ${Math.round(cur.clicks)})`, fix: 'Verlierer-Seiten/-Suchanfragen in der GSC prüfen; Änderungen der letzten Wochen abgleichen.', url: homeUrl, label: 'gemessen', quelle: 'gsc' });
  if (cur.impressions > 0 && prev.impressions > 0 && cur.position - prev.position >= 3) out.findings.push({ sev: 'niedrig', was: `GSC: Ø Position verschlechtert (${prev.position.toFixed(1)} → ${cur.position.toFixed(1)})`, fix: 'Suchanfragen mit größtem Positionsverlust prüfen.', url: homeUrl, label: 'gemessen', quelle: 'gsc' });
  if (r.inspect) {
    out.measurements.push({ text: `GSC Indexierung Startseite: ${r.inspect.verdict} (${r.inspect.coverage || '–'})`, label: 'gemessen' });
    if (r.inspect.verdict !== 'PASS') out.findings.push({ sev: 'hoch', was: `GSC: Startseite nicht im Google-Index (${r.inspect.coverage || r.inspect.verdict})`, fix: 'In der GSC „Indexierung beantragen“; Ursache (noindex, Canonical, Crawling) laut Abdeckungsstatus beheben.', url: homeUrl, label: 'gemessen', quelle: 'gsc' });
  } else out.notMeasured.push('GSC: Indexierungsstatus nicht geliefert');
  return out;
}

/* ---------- Statische On-Page-Helfer ---------- */
function ogMissing(html) {
  const have = new Set();
  for (const t of html.match(/<meta\b[^>]*>/gi) || []) {
    const p = t.match(/\bproperty\s*=\s*["']?(og:[a-z:_]+)/i);
    const c = t.match(/\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)')/i);
    if (p && c && (c[1] || c[2] || '').trim()) have.add(p[1].toLowerCase());
  }
  return ['og:title', 'og:description', 'og:image'].filter(k => !have.has(k));
}
function jsonLdTypes(html) {
  const types = new Set(); let invalid = 0, blocks = 0;
  const walk = o => {
    if (Array.isArray(o)) return o.forEach(walk);
    if (o && typeof o === 'object') { [].concat(o['@type'] || []).forEach(t => types.add(String(t))); Object.values(o).forEach(walk); }
  };
  const re = /<script\b[^>]*type\s*=\s*["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html))) { blocks++; try { walk(JSON.parse(m[1])); } catch (e) { invalid++; } }
  return { types: [...types], invalid, blocks };
}
/* Fast leeres Roh-HTML oder Lade-Platzhalter = SPA-/Thin-Verdacht (generisch, ohne JS). */
function thinInfo(html) {
  const text = html.replace(/<(script|style|noscript)\b[\s\S]*?<\/\1>/gi, ' ').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
  const words = text ? text.split(' ').length : 0;
  const placeholder = /(wird geladen|lädt\.\.\.|loading\.\.\.|bitte warten|please wait|enable javascript|aktivieren sie javascript)/i.test(text.slice(0, 2000));
  return { words, placeholder };
}
const ENTITY_RX = /(Organization|LocalBusiness|Restaurant|Hotel|Store|Person|Accountant|Attorney|Dentist|Physician|Photographer|Service|Winery|Bakery|Cafe|BarOrPub|FoodEstablishment|LodgingBusiness|Professional)/;
function homeSchemaFindings(html, url, spa) {
  const out = empty();
  if (spa) { out.notMeasured.push('Schema/Open Graph der Startseite: SPA, Roh-HTML leer – nicht belegbar'); return out; }
  const s = jsonLdTypes(html);
  if (!s.types.some(t => ENTITY_RX.test(t)))
    out.findings.push({ sev: 'hoch', was: s.blocks ? `Startseite: kein Organization/LocalBusiness-Schema (gefunden: ${s.types.join(', ') || 'keine Typen'})` : 'Startseite: keine strukturierten Daten (JSON-LD) im Roh-HTML', fix: 'JSON-LD Organization bzw. LocalBusiness (Name, Adresse, Telefon, Öffnungszeiten, sameAs) server-seitig ausliefern.', url, label: 'gemessen', quelle: 'onpage' });
  if (!s.types.includes('WebSite'))
    out.findings.push({ sev: 'niedrig', was: 'Startseite: kein WebSite-Schema', fix: 'JSON-LD WebSite (name, url) ergänzen.', url, label: 'gemessen', quelle: 'onpage' });
  out.measurements.push({ text: `Startseite JSON-LD-Typen im Roh-HTML: ${s.types.join(', ') || 'keine'}`, label: 'gemessen' });
  return out;
}

module.exports = { cleanupTmp, writeBodyFile, httpJson, thinInfo, mapGeoResult, runGeo, cwvFindings, psi, psiFetch, gsc, gscFetch, ogMissing, jsonLdTypes, homeSchemaFindings, CWV };
