#!/usr/bin/env node
'use strict';
/* TOKEN-FREIER seo-audit. Ersetzt den `claude -p`-Lauf durch echtes Parsen der Live-Seiten.
   Regeln aus .claude/agents/seo-audit.md: nur BELEGTE Befunde (konkrete URL + Ist-Zustand
   aus echtem Abruf), keine Ranking-/Traffic-Versprechen, nur interne Links pruefen, max ~9
   Seiten pro Site, nichts an den Websites veraendern. Der Fix-Text je Befundtyp ist ein
   fixer, endlicher Katalog – dafuer braucht es kein Modell. */
const fs = require('fs');
const path = require('path');
const L = require('./lib');
const X = require('./seo-checks');

const DRY = process.argv.includes('--dry-run') || process.env.SEO_DRY_RUN === '1';   // nichts schreiben, nichts posten
const A = DRY ? { log: m => process.stdout.write('· ' + m + '\n'), status() {}, routine() {} } : L.agent('seo-audit');
const CFG = path.join(L.BASE, 'config', 'sites.json');
const OUTDIR = path.join(L.BASE, 'seo', L.nowKW());
const MAX_PAGES = 9;                                    // Startseite + 8
const MAX_LINKCHECK = 40;                               // Kundenseite nicht belasten
const BASELINE_DIR = process.env.SEO_BASELINE_DIR || path.join(L.BASE, 'seo', 'baselines');
/* Globales Zeitbudget (deutlich unter HQ_RUN_TIMEOUT 1800 s): danach werden Checks/Sites als "nicht gemessen" markiert. */
const BUDGET_MS = parseInt(process.env.SEO_BUDGET_MS, 10) || 1500000;
const DEADLINE = Date.now() + BUDGET_MS;
const over = () => Date.now() > DEADLINE;
const SEV = { kritisch: 4, hoch: 3, mittel: 2, niedrig: 1 };
const SEV_NAME = { kritisch: 'Kritisch', hoch: 'Hoch', mittel: 'Mittel', niedrig: 'Niedrig' };

function fail(msg) {
  A.log('FEHLER: ' + msg);
  A.status('error', 'Abgebrochen', 0, msg.slice(0, 200));
  process.stdout.write(JSON.stringify({ result: 'seo-audit: ' + msg }) + '\n');
  process.exit(1);
}

/* ---------- HTML-Parsing (regex, keine DOM-Deps) ---------- */
const rxTitle = /<title[^>]*>([\s\S]*?)<\/title>/i;
const rxCanon = /<link\b[^>]*rel=["']canonical["'][^>]*>/i;
const rxHref = /href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))/i;
function metaDesc(html) {
  const m = html.match(/<meta\b[^>]*name=["']description["'][^>]*>/i);
  if (!m) return null;
  const c = m[0].match(/content\s*=\s*(?:"([^"]*)"|'([^']*)')/i);
  return c ? (c[1] || c[2] || '') : '';
}
function h1Count(html) { return (html.match(/<h1[\s>]/gi) || []).length; }
function canonicalHref(html) {
  const m = html.match(rxCanon); if (!m) return null;
  const h = m[0].match(rxHref); return h ? (h[1] || h[2] || h[3] || '') : '';
}
function imgsMissingAlt(html) {
  const imgs = html.match(/<img\b[^>]*>/gi) || [];
  return imgs.filter(t => !/\balt\s*=/i.test(t)).length;
}
function links(html, baseUrl) {
  const out = [];
  const re = /<a\b[^>]*\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))/gi;
  let m;
  while ((m = re.exec(html))) {
    const raw = (m[1] || m[2] || m[3] || '').replace(/&amp;/g, '&').trim();
    if (!raw || raw.startsWith('#') || /^(mailto:|tel:|javascript:|data:)/i.test(raw)) continue;
    const n = normUrl(raw, baseUrl); if (n) out.push(n);
  }
  return out;
}
/* URL-Normalisierung: Host lowercase + leerer Pfad = "/" (macht new URL), ohne #Fragment.
   Trailing-Slash anderer Pfade bleibt unangetastet. */
function normUrl(raw, base) {
  try { const u = new URL(raw, base); u.hash = ''; return u.href; } catch (e) { return null; }
}

/* Nicht-HTML-Ressourcen (PDF, Bilder, ...) bekommen keine Seiten-Checks. Content-Type zaehlt,
   die Dateiendung nur als Fallback, wenn der Server keinen Content-Type liefert. */
const NON_HTML_EXT = /\.(pdf|jpe?g|png|gif|webp|avif|svg|ico|bmp|mp4|webm|mov|mp3|wav|zip|gz|rar|7z|docx?|xlsx?|pptx?|csv|json|xml|txt|css|js|mjs|woff2?|ttf|otf)$/i;
function isHtmlResource(ct, url) {
  if (ct) return /^(text\/html|application\/xhtml\+xml)\b/i.test(ct);
  try { return !NON_HTML_EXT.test(new URL(url).pathname); } catch (e) { return true; }
}
/* Gleiche Site = Schema + Port + Host (www-Variante desselben Hosts erlaubt). */
function sameSite(a, b) {
  try {
    const x = new URL(a), y = new URL(b);
    const h = u => u.hostname.replace(/^www\./, '');
    return x.protocol === y.protocol && x.port === y.port && h(x) === h(y);
  } catch (e) { return false; }
}
function probe(url) {                                // Statuscode + Content-Type der Endziel-URL
  const r = L.run('curl', ['-sS', '-o', process.platform === 'win32' ? 'NUL' : '/dev/null',
    '-w', '%{http_code} %{content_type}', '-L', '--max-time', '20', ...L.SAFE_CURL, '--', url], { timeoutMs: 26000 });
  const p = r.out.trim().split(/\s+/);
  const http = parseInt(p[0], 10);
  return { http: Number.isFinite(http) && http > 0 ? http : null, ct: (p[1] || '').toLowerCase().replace(/;$/, ''), err: r.err.trim().slice(0, 200) };
}

/* Eine Seite abrufen + prüfen; gibt {url, bytes, findings[], title, internalLinks[]} */
function auditPage(url, host, keepHtml) {
  const pr = probe(url);
  if (pr.http == null) return { url, error: pr.err || 'nicht abrufbar', findings: [], internalLinks: [], title: null };
  if (pr.http >= 400) return { url, error: 'HTTP ' + pr.http, findings: [], internalLinks: [], title: null };   // keine Seiten-Checks an Fehlerseiten
  if (!isHtmlResource(pr.ct, url)) return { url, bytes: 0, findings: [], title: null, internalLinks: [], nonHtml: pr.ct || 'unbekannt' };
  const b = L.curlBody(url);
  if (!b.ok && !b.body) return { url, error: b.err || 'nicht abrufbar', findings: [], internalLinks: [], title: null };
  const html = b.body || '';
  const bytes = Buffer.byteLength(html, 'utf8');
  const f = [];
  const add = (sev, was, fix, label = 'gemessen') => f.push({ sev, was, fix, url, label });

  const tm = html.match(rxTitle);
  const title = tm ? tm[1].replace(/\s+/g, ' ').trim() : null;
  if (!title) add('hoch', 'kein <title>', 'Eindeutigen Title (~30–60 Zeichen) setzen.');
  else if (title.length < 30) add('mittel', `Title zu kurz (${title.length})`, 'Title auf ~30–60 Zeichen erweitern, Kernbegriff + Ort/Marke.');
  else if (title.length > 60) add('mittel', `Title zu lang (${title.length})`, 'Title auf ~55 Zeichen kürzen, Wichtigstes nach vorn.');

  const md = metaDesc(html);
  if (md == null) add('hoch', 'keine Meta-Description', 'Meta-Description (~70–160 Zeichen) mit Nutzen + Call-to-Action ergänzen.');
  else if (md.length < 70) add('niedrig', `Meta-Description zu kurz (${md.length})`, 'Auf ~70–160 Zeichen ausbauen.');
  else if (md.length > 160) add('niedrig', `Meta-Description zu lang (${md.length})`, 'Auf ~160 Zeichen kürzen (sonst abgeschnitten).');

  const h1 = h1Count(html);
  const internalLinks = links(html, url).filter(u => sameSite(u, url));
  // Client-gerenderte SPA? Dann sieht curl nur die leere Shell -> DOM-Checks (h1/Bilder/
  // interne Links) sind statisch NICHT belegbar. Ehrlich melden statt Fehlbefunde erfinden.
  const mount = /<div\s+id=["'](root|app|__next|__nuxt|q-app|svelte)["']/i.test(html);
  const spa = mount && h1 === 0 && internalLinks.length === 0 && bytes < 60000;

  const thin = X.thinInfo(html);
  if (thin.placeholder && !spa) add('hoch', 'Lade-Platzhalter im Roh-HTML ("wird geladen …"): Inhalt erst per JavaScript', 'Inhalt server-seitig/prerendert ausliefern; Crawler sehen sonst nur den Platzhalter.', 'proxy');
  else if (!spa && thin.words < 120) add('mittel', `Dünner Inhalt im Roh-HTML (${thin.words} Wörter)`, 'Eigenständigen Text ergänzen oder Seite per noindex/Redirect bereinigen; bei JS-Inhalt Prerendering.', 'proxy');
  if (spa) {
    add('hoch', 'Client-gerendert (SPA): Roh-HTML ohne Inhalt (h1/Bilder/interne Links nur im Browser)',
      'SSR/Prerendering einführen: KI-Crawler und viele Suchsysteme führen kein JavaScript aus und sehen nur die leere Shell.', 'proxy');
  } else {
    if (h1 === 0) add('hoch', 'keine <h1>', 'Genau eine aussagekräftige <h1> je Seite setzen.');
    else if (h1 > 1) add('mittel', `${h1}× <h1>`, 'Auf genau eine <h1> reduzieren, Rest zu <h2>/<h3>.');
    const noAlt = imgsMissingAlt(html);
    if (noAlt > 0) add('niedrig', `${noAlt} <img> ohne alt`, 'Sprechende alt-Texte ergänzen (Barrierefreiheit + Bild-SEO).');
    const og = X.ogMissing(html);
    if (og.length) add(og.length === 3 ? 'mittel' : 'niedrig', 'Open Graph unvollständig (fehlt: ' + og.join(', ') + ')', 'og:title, og:description und og:image (1200×630) setzen – bestimmt die Vorschau beim Teilen und in KI-Antworten.');
    if (internalLinks.length < 3) add('niedrig', `nur ${internalLinks.length} interne Link(s) im Roh-HTML (Waisen-Verdacht)`, 'Wichtige Seiten aus Navigation/Fließtext intern verlinken.', 'proxy');
    if (bytes > 2 * 1024 * 1024) add('niedrig', `HTML groß (${Math.round(bytes / 1024)} KB)`, 'HTML/Inline-Assets verschlanken; Bilder auslagern/komprimieren.');
  }

  const can = canonicalHref(html);
  if (can == null) add(spa ? 'niedrig' : 'mittel', 'kein rel=canonical', 'Selbstreferenzierendes <link rel="canonical"> auf die kanonische URL setzen.');
  else { try { if (new URL(can, url).hostname !== host) add('mittel', `canonical zeigt auf fremde Domain (${can})`, 'Canonical auf die eigene kanonische URL korrigieren.'); } catch (e) { add('niedrig', `canonical unlesbar (${can})`, 'Canonical als absolute, gültige URL setzen.'); } }

  return { url, bytes, findings: f, title, internalLinks, spa, html: keepHtml ? html : undefined };
}

/* HTTP->HTTPS, Redirect-Ketten, www/non-www: je Site ein paar curl-Aufrufe (GET, nur lesen). */
function curlFinal(url) {
  const r = L.run('curl', ['-sS', '-o', process.platform === 'win32' ? 'NUL' : '/dev/null', '-w', '%{http_code} %{num_redirects} %{url_effective}', '-L', '--max-time', '20', ...L.SAFE_CURL, '--', url], { timeoutMs: 26000 });
  const p = r.out.trim().split(/\s+/);
  const http = parseInt(p[0], 10);
  return Number.isFinite(http) && http > 0 ? { http, hops: parseInt(p[1], 10) || 0, eff: p[2] || url } : null;
}
function hostChecks(start) {
  const out = { findings: [], measurements: [], notMeasured: [] };
  const u = new URL(start);
  if (/^[\d.]+$/.test(u.hostname) || u.hostname === 'localhost' || u.protocol !== 'https:') {
    out.notMeasured.push('HTTP→HTTPS, www/non-www, Redirect-Ketten: nur für https-Domains messbar');
    return out;
  }
  const add = (sev, was, fix, url, label = 'gemessen') => out.findings.push({ sev, was, fix, url, label });
  const http = curlFinal('http://' + u.hostname + '/');
  if (!http) out.notMeasured.push('HTTP→HTTPS: http://-Variante nicht abrufbar');
  else {
    if (!http.eff.startsWith('https://')) add('hoch', `http:// leitet nicht auf HTTPS weiter (Endziel ${http.eff})`, '301-Weiterleitung von http:// auf https:// einrichten.', 'http://' + u.hostname + '/');
    if (http.hops > 2) add('mittel', `Redirect-Kette http:// → Startseite: ${http.hops} Sprünge`, 'Direkt auf die finale URL weiterleiten (max. 1–2 Sprünge).', 'http://' + u.hostname + '/');
    out.measurements.push({ text: `http:// → ${http.eff} in ${http.hops} Sprung/Sprüngen (HTTP ${http.http})`, label: 'gemessen' });
  }
  const main = curlFinal(start);
  const canonHost = main ? new URL(main.eff).hostname : u.hostname;
  const alt = u.hostname.startsWith('www.') ? u.hostname.slice(4) : 'www.' + u.hostname;
  const a = curlFinal('https://' + alt + '/');
  if (!a) out.measurements.push({ text: `${alt}: nicht erreichbar (kein Duplikat, aber Besucher mit dieser Schreibweise landen im Leeren)`, label: 'gemessen' });
  else if (new URL(a.eff).hostname !== canonHost && a.http < 400) add('hoch', `${alt} ist ohne Weiterleitung erreichbar (Duplicate Content, Endziel ${a.eff})`, `${alt} per 301 auf ${canonHost} weiterleiten.`, 'https://' + alt + '/');
  else out.measurements.push({ text: `${alt} → ${a.eff} (einheitlich ${canonHost})`, label: 'gemessen' });
  if (main && main.hops > 2) add('mittel', `Redirect-Kette Startseite: ${main.hops} Sprünge`, 'Interne Links/Sitemap direkt auf die finale URL zeigen lassen.', start);
  return out;
}

/* Sitemap-URLs (max. 200) fuer den Waisen-Verdacht; robots.txt nennt die Sitemap. */
/* Untrusted Eingabe (robots.txt/Sitemap): nur http(s)-URLs der eigenen Site (Schema+Port+Host, www erlaubt). */
function allowedUrl(raw, origin) {
  const n = normUrl(String(raw).replace(/&amp;/g, '&').trim());
  return n && /^https?:/i.test(n) && sameSite(n, origin) ? n : null;
}
function sitemapUrls(origin, robotsText) {
  const lines = (robotsText || '').match(/^\s*sitemap:\s*(\S+)/gim) || [];
  const queue = lines.map(l => allowedUrl(l.replace(/^\s*sitemap:\s*/i, ''), origin)).filter(Boolean).slice(0, 3);
  if (!queue.length) queue.push(origin + '/sitemap.xml');
  const urls = []; let fetched = 0;
  while (queue.length && fetched < 4 && urls.length < 200) {
    const b = L.curlBody(queue.shift()); fetched++;
    if (!b.body || !/<(urlset|sitemapindex)/i.test(b.body)) continue;
    const locs = [...b.body.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/gi)].map(m => allowedUrl(m[1], origin)).filter(Boolean);
    if (/<sitemapindex/i.test(b.body)) queue.push(...locs.slice(0, 3)); else urls.push(...locs);
  }
  return urls.slice(0, 200);
}
/* Vergleichsschluessel fuer den Waisen-Check: ohne www, ohne Trailing Slash, ohne Fragment. */
function orphanKey(u) {
  try { const x = new URL(u); return x.hostname.replace(/^www\./, '').toLowerCase() + x.pathname.replace(/\/+$/, '') + x.search; } catch (e) { return u; }
}

function auditSite(site, deps = {}) {
  const d = { geo: X.runGeo, psi: X.psi, gsc: X.gsc, ...deps };
  const start = normUrl(site.url);
  let host; try { host = new URL(start).hostname; } catch (e) { return { site, error: 'ungültige URL' }; }
  A.log(`audit ${site.name} …`);

  const home = auditPage(start, host, true);
  const pages = [home];
  const seen = new Set([start]);
  for (const u of (home.internalLinks || [])) {
    if (pages.length >= MAX_PAGES) break;
    if (seen.has(u)) continue;
    seen.add(u);
    const p = auditPage(u, host);
    if (p.error) continue;                              // Fehlerseiten belegen keinen Platz; der Link-Check meldet sie
    pages.push(p);
  }

  const origin = new URL(start).origin;
  const robotsTxt = L.curlBody(origin + '/robots.txt').body || '';
  const sm = sitemapUrls(origin, robotsTxt);
  const siteFindings = [];
  const measurements = [], notMeasured = [];
  for (const u of sm) {                                 // Sitemap-URLs mit auditieren (dünn/ohne canonical/h1); URLs sind schon gefiltert
    if (pages.length >= MAX_PAGES || over()) break;
    if (seen.has(u)) continue;
    seen.add(u);
    const p = auditPage(u, host);
    if (p.error) continue;
    pages.push(p);
  }
  // Waisen-Vergleich erst NACH dem Audit der Sitemap-Seiten: deren Links zaehlen mit
  const linkedKeys = new Set(pages.flatMap(p => p.internalLinks || []).concat([start]).map(orphanKey));
  const take = r => { siteFindings.push(...r.findings); measurements.push(...r.measurements); notMeasured.push(...r.notMeasured); };

  // 1) geo_audit.py: robots/KI-Bots, WAF, noindex, SPA, JSON-LD, Soft-404, Sitemap, Drift
  const geo = over() ? { findings: [], measurements: [], notMeasured: ['geo_audit.py (KI-Bots, WAF, noindex, Schema, Drift): nicht gemessen (Zeitbudget)'] }
    : d.geo(start, { baseDir: BASELINE_DIR, slug: L.slug(host), dry: DRY });
  take(geo);
  // Doppelmeldungen: hat geo_audit "Rendering" (zu wenig Roh-HTML) fuer eine URL gemeldet, entfaellt unser SPA-/Duenn-Befund dort
  const geoThin = new Set((geo.findings || []).filter(f => /^Rendering/.test(f.was)).map(f => f.url));
  if (geoThin.size) for (const p of pages) p.findings = (p.findings || []).filter(f => !(geoThin.has(f.url) && /SPA|Dünner Inhalt/.test(f.was)));
  if (geo.geoFailed) {                                  // Fallback ohne Python: einfache Erreichbarkeits-Checks
    const robots = L.curlStatus(origin + '/robots.txt', { head: true });
    const sitemap = L.curlStatus(origin + '/sitemap.xml', { head: true });
    if (!(robots && robots < 400)) siteFindings.push({ sev: 'niedrig', was: `robots.txt nicht erreichbar (HTTP ${robots ?? '–'})`, fix: 'robots.txt bereitstellen (auch minimal), Sitemap darin verlinken.', url: origin + '/robots.txt', label: 'gemessen' });
    else if (!/^\s*sitemap:/im.test(robotsTxt)) siteFindings.push({ sev: 'niedrig', was: 'robots.txt ohne Sitemap-Zeile', fix: 'Sitemap: https://…/sitemap.xml ergänzen.', url: origin + '/robots.txt', label: 'gemessen' });
    if (!(sitemap && sitemap < 400)) siteFindings.push({ sev: 'mittel', was: `sitemap.xml nicht erreichbar (HTTP ${sitemap ?? '–'})`, fix: 'XML-Sitemap generieren und unter /sitemap.xml ausliefern.', url: origin + '/sitemap.xml', label: 'gemessen' });
    notMeasured.push('KI-Bot-Matrix, WAF-Blocks, noindex, Soft-404, Schema-Validität (geo_audit.py nicht lauffähig)');
  }

  // 2) Core Web Vitals + 3) Search Console (beide optional/mockbar)
  if (over()) notMeasured.push('Core Web Vitals und GSC: nicht gemessen (Zeitbudget)');
  else { take(d.psi(start)); take(d.gsc(site, start)); }

  // 4) On-Page der Startseite: Schema + Redirects/Hosts
  if (home.html) take(X.homeSchemaFindings(home.html, start, home.spa));
  take(hostChecks(start));
  const spaPages = pages.filter(p => p.spa);
  if (spaPages.length) notMeasured.push(`h1, Bilder-alt, Open Graph, interne Links auf ${spaPages.length} SPA-Seite(n): im Roh-HTML nicht belegbar (z. B. ${spaPages[0].url})`);

  // Title-Duplikate über Seiten
  const byTitle = {};
  for (const p of pages) if (p.title) (byTitle[p.title] = byTitle[p.title] || []).push(p.url);
  for (const [t, urls] of Object.entries(byTitle)) if (urls.length > 1)
    siteFindings.push({ sev: 'mittel', was: `Title "${t.slice(0, 50)}" ${urls.length}× identisch`, fix: 'Je Seite einen eindeutigen Title vergeben.', url: urls[0], label: 'gemessen' });

  // Waisen-Verdacht: Sitemap-URL, die von keiner geprüften Seite verlinkt wird
  if (sm.length) {
    const orphans = sm.filter(u => !linkedKeys.has(orphanKey(u)));
    if (orphans.length) siteFindings.push({ sev: 'niedrig', was: `Waisen-Verdacht: ${orphans.length} von ${sm.length} Sitemap-URLs von keiner der ${pages.length} geprüften Seiten verlinkt (z. B. ${orphans.slice(0, 3).join(', ')})`, fix: 'Seiten intern verlinken (Navigation, Fließtext, Footer); Verdacht, da nur ~9 Seiten gecrawlt werden.', url: orphans[0], label: 'proxy' });
    measurements.push({ text: `Sitemap: ${sm.length} URL(s), ${sm.length - orphans.length} intern verlinkt (Stichprobe ${pages.length} Seiten)`, label: 'proxy' });
  } else notMeasured.push('Waisen-Seiten: keine lesbare Sitemap');

  // kaputte interne Links (dedupe über alle Seiten, gedeckelt)
  const allLinks = [...new Set(pages.flatMap(p => p.internalLinks || []))].slice(0, MAX_LINKCHECK);
  let checked = 0, unchecked = 0;
  for (const u of allLinks) {
    if (over()) { unchecked++; continue; }              // Zeitbudget: Rest nicht pruefbar
    let code = L.curlStatus(u, { head: true });
    if (code === 405 || code === 501) code = L.curlStatus(u, { head: false });  // HEAD verboten -> GET
    if (code == null) { unchecked++; continue; }        // Timeout/DNS/TLS: nicht gemessen, nicht "ok"
    checked++;
    if (code >= 400) siteFindings.push({ sev: 'hoch', was: `interner Link kaputt (HTTP ${code})`, fix: 'Link korrigieren oder entfernen; ggf. 301 auf Ziel.', url: u, label: 'gemessen' });
  }

  if (unchecked) notMeasured.push(`${unchecked} interne Link(s) nicht prüfbar (Timeout/DNS/TLS)`);
  const allFindings = [...siteFindings, ...pages.flatMap(p => (p.findings || []).length ? p.findings : (p.error ? [{ sev: 'hoch', was: `Seite nicht abrufbar: ${p.error}`, fix: 'Erreichbarkeit prüfen.', url: p.url, label: 'gemessen' }] : []))];
  allFindings.sort((a, b) => SEV[b.sev] - SEV[a.sev]);
  return { site, host, pages: pages.length, links_checked: checked, findings: allFindings, measurements, notMeasured: [...new Set(notMeasured)] };
}

/* Ehrliche Ampel: Rot bei jedem Blocker (hoch/kritisch), Gelb bei Mittel-Befunden ODER ungemessenen
   Punkten, Grün nur wenn alles gemessen und ok. */
function ampel(findings, notMeasured = []) {
  if (findings.some(f => f.sev === 'hoch' || f.sev === 'kritisch')) return '🔴 rot';
  if (findings.some(f => f.sev === 'mittel') || notMeasured.length) return '🟡 gelb';
  return '🟢 grün';
}

function renderReport(res) {
  const g = { kritisch: [], hoch: [], mittel: [], niedrig: [] };
  for (const x of res.findings) g[x.sev].push(x);
  const nm = res.notMeasured || [];
  const lines = [
    `# SEO-Audit · ${res.site.name}`, '',
    `**Ampel:** ${ampel(res.findings, nm)}  ·  ${res.pages} Seiten geprüft  ·  ${res.links_checked} interne Links  ·  ${res.findings.length} Befund(e)  ·  ${nm.length} nicht gemessen`,
    `**Stand:** ${L.localIso()}  ·  ${res.site.url}`,
    '_Kennzeichnung je Zahl/Befund: **gemessen** = direkt abgerufen/berechnet, **proxy** = Indiz oder Schätzung, nicht belegt._', ''
  ];
  for (const sev of ['kritisch', 'hoch', 'mittel', 'niedrig']) {
    if (!g[sev].length) continue;
    lines.push(`## ${SEV_NAME[sev]} (${g[sev].length})`, '');
    for (const x of g[sev]) {
      lines.push(`- **${x.was}** _(${x.label || 'gemessen'})_`, `  - URL: ${x.url}`);
      if (x.evidence) lines.push(`  - Beleg: \`${x.evidence}\``);
      lines.push(`  - Fix: ${x.fix}`);
    }
    lines.push('');
  }
  if (!res.findings.length) lines.push('_Keine technischen Mängel unter den gemessenen Punkten._', '');
  if ((res.measurements || []).length) {
    lines.push('## Messwerte', '');
    for (const m of res.measurements) lines.push(`- ${m.text} _(${m.label})_`);
    lines.push('');
  }
  lines.push('## Nicht gemessen', '', '_Zählt nie als bestanden._', '');
  for (const n of nm) lines.push(`- ${n}`);
  if (!nm.length) lines.push('- (alles Vorgesehene wurde gemessen)');
  lines.push('', '## Grenzen (bekannte Systemgrenzen, keine Lücke dieses Laufs)', '',
    '- Nur Roh-HTML ohne JavaScript geprüft; gerendertes HTML (Googlebot-Sicht) → GSC URL-Inspektion / Rich-Results-Test.',
    '- Bot-User-Agent-Test sendet gefälschte UAs von der eigenen IP: Indiz für WAF/CDN-Blocks, kein Beleg für echten Bot-Zugriff (Server-Logs).',
    '- Stichprobe von höchstens ' + MAX_PAGES + ' Seiten je Site; Waisen-Befunde sind Verdacht.',
    '- Lighthouse-Labordaten sind simuliert (proxy); maßgeblich sind Felddaten (CrUX).', '');
  lines.push('_Automatischer Audit (seo-audit, token-frei). Nur Lesezugriff, nichts verändert._', '');
  return lines.join('\n');
}

function writeReport(res) {
  fs.mkdirSync(OUTDIR, { recursive: true });
  const f = path.join(OUTDIR, L.slug(res.site.name) + '.md');
  fs.writeFileSync(f, renderReport(res));
  return path.relative(L.BASE, f).split(path.sep).join('/');
}

function main() {
  const cfg = L.readJson(CFG, null);
  if (!cfg || !Array.isArray(cfg.sites) || !cfg.sites.length) fail('config/sites.json fehlt oder leer');
  if (!L.haveTool('curl')) fail("'curl' nicht gefunden – ohne curl kein Audit");
  const only = process.argv.find(a => a.startsWith('--site='));
  const sites = only ? cfg.sites.filter(s => s.name === only.slice(7)) : cfg.sites;

  A.status('running', 'Audit', 10, `${sites.length} Sites…`);
  const outputs = [], details = [];
  const finish = (msg) => {                              // Status + Discord-Zeile werden IMMER geschrieben
    const summary = `SEO-Audit ${L.nowKW()}: ${details.length} Sites — ` + details.map(d => d.split(':')[0].trim()).join(', ') + (msg ? ` (${msg})` : '');
    A.status(msg ? 'error' : 'ok', msg ? 'Abgebrochen' : 'Fertig', 100, summary, details, outputs);
    A.routine(`🔎 **SEO-Audit ${L.nowKW()}** ${msg ? 'unvollständig (' + msg + ')' : 'fertig'}: ${details.join(' · ')}`);
    return summary;
  };
  process.on('SIGTERM', () => {                          // greift, sobald ein blockierender Aufruf zurueckkehrt
    X.cleanupTmp();
    finish('SIGTERM');
    process.exit(143);
  });
  sites.forEach((site, i) => {
    if (over()) { details.push(`${site.name}: 🟡 gelb, nicht gemessen (Zeitbudget ${Math.round(BUDGET_MS / 1000)} s erschöpft)`); return; }
    let res;
    try { res = auditSite(site); } catch (e) { res = { error: 'Audit-Fehler: ' + String(e && e.message || e).slice(0, 120) }; }
    if (res.error) { details.push(`${site.name}: ${res.error}`); return; }
    const nm = res.notMeasured.length;
    if (DRY) process.stdout.write(renderReport(res) + '\n');
    else outputs.push(writeReport(res));
    const top = res.findings.filter(x => x.sev === 'hoch' || x.sev === 'kritisch').length;
    details.push(`${site.name}: ${ampel(res.findings, res.notMeasured)}, ${res.findings.length} Befunde${top ? `, ${top} hoch` : ''}${nm ? ` + ${nm} nicht gemessen` : ''}`);
    A.status('running', 'Audit', 10 + Math.round(80 * (i + 1) / sites.length), `${site.name} fertig`);
  });

  X.cleanupTmp();
  const summary = finish('');                            // Routine-Zeile in den Themen-Kanal (reports), respektiert quiet
  if (DRY) process.stdout.write('DRY-RUN-ZUSAMMENFASSUNG\n' + details.join('\n') + '\n');
  process.stdout.write(JSON.stringify({ result: summary, engine: 'script' }) + '\n');
  process.exit(0);
}

if (require.main === module) {
  try { main(); } catch (e) { fail(String(e && e.stack || e)); }
} else {
  module.exports = { auditSite, normUrl, isHtmlResource, ampel, renderReport, sitemapUrls, orphanKey, sameSite };
}
