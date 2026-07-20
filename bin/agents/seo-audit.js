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

const A = L.agent('seo-audit');
const CFG = path.join(L.BASE, 'config', 'sites.json');
const OUTDIR = path.join(L.BASE, 'seo', L.nowKW());
const MAX_PAGES = 9;                                    // Startseite + 8
const MAX_LINKCHECK = 40;                               // Kundenseite nicht belasten
const SEV = { hoch: 3, mittel: 2, niedrig: 1 };

function fail(msg) {
  A.log('FEHLER: ' + msg);
  A.status('error', 'Abgebrochen', 0, msg.slice(0, 200));
  process.stdout.write(JSON.stringify({ result: 'seo-audit: ' + msg }) + '\n');
  process.exit(1);
}

/* ---------- HTML-Parsing (regex, keine DOM-Deps) ---------- */
const rxTitle = /<title[^>]*>([\s\S]*?)<\/title>/i;
const rxCanon = /<link\b[^>]*rel=["']canonical["'][^>]*>/i;
const rxHref = /href\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))/i;
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
  const re = /<a\b[^>]*\bhref\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))/gi;
  let m;
  while ((m = re.exec(html))) {
    const raw = (m[1] || m[2] || m[3] || '').trim();
    if (!raw || raw.startsWith('#') || /^(mailto:|tel:|javascript:|data:)/i.test(raw)) continue;
    try { out.push(new URL(raw, baseUrl).href.split('#')[0]); } catch (e) {}
  }
  return out;
}

/* Eine Seite abrufen + prüfen; gibt {url, bytes, findings[], title, internalLinks[]} */
function auditPage(url, host) {
  const b = L.curlBody(url);
  if (!b.ok && !b.body) return { url, error: b.err || 'nicht abrufbar', findings: [], internalLinks: [], title: null };
  const html = b.body || '';
  const bytes = Buffer.byteLength(html, 'utf8');
  const f = [];
  const add = (sev, was, fix) => f.push({ sev, was, fix, url });

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
  const internalLinks = links(html, url).filter(u => { try { return new URL(u).hostname === host; } catch (e) { return false; } });
  // Client-gerenderte SPA? Dann sieht curl nur die leere Shell -> DOM-Checks (h1/Bilder/
  // interne Links) sind statisch NICHT belegbar. Ehrlich melden statt Fehlbefunde erfinden.
  const mount = /<div\s+id=["'](root|app|__next|__nuxt|q-app|svelte)["']/i.test(html);
  const spa = mount && h1 === 0 && internalLinks.length === 0 && bytes < 60000;

  if (spa) {
    add('niedrig', 'Client-gerendert (SPA): h1/Bilder/interne Links nur im Browser vorhanden',
      'Für Suchmaschinen SSR/Prerendering erwägen; statischer Audit prüft nur Title/Meta/Canonical/robots/sitemap.');
  } else {
    if (h1 === 0) add('hoch', 'keine <h1>', 'Genau eine aussagekräftige <h1> je Seite setzen.');
    else if (h1 > 1) add('mittel', `${h1}× <h1>`, 'Auf genau eine <h1> reduzieren, Rest zu <h2>/<h3>.');
    const noAlt = imgsMissingAlt(html);
    if (noAlt > 0) add('niedrig', `${noAlt} <img> ohne alt`, 'Sprechende alt-Texte ergänzen (Barrierefreiheit + Bild-SEO).');
    if (bytes > 2 * 1024 * 1024) add('niedrig', `HTML groß (${Math.round(bytes / 1024)} KB)`, 'HTML/Inline-Assets verschlanken; Bilder auslagern/komprimieren.');
  }

  const can = canonicalHref(html);
  if (can == null) add(spa ? 'niedrig' : 'mittel', 'kein rel=canonical', 'Selbstreferenzierendes <link rel="canonical"> auf die kanonische URL setzen.');
  else { try { if (new URL(can, url).hostname !== host) add('mittel', `canonical zeigt auf fremde Domain (${can})`, 'Canonical auf die eigene kanonische URL korrigieren.'); } catch (e) { add('niedrig', `canonical unlesbar (${can})`, 'Canonical als absolute, gültige URL setzen.'); } }

  return { url, bytes, findings: f, title, internalLinks, spa };
}

function auditSite(site) {
  const start = site.url;
  let host; try { host = new URL(start).hostname; } catch (e) { return { site, error: 'ungültige URL' }; }
  A.log(`audit ${site.name} …`);

  const home = auditPage(start, host);
  const pages = [home];
  const seen = new Set([start.split('#')[0]]);
  for (const u of (home.internalLinks || [])) {
    if (pages.length >= MAX_PAGES) break;
    if (seen.has(u)) continue;
    seen.add(u);
    pages.push(auditPage(u, host));
  }

  // robots.txt + sitemap.xml (Site-Ebene, einmal)
  const origin = new URL(start).origin;
  const robots = L.curlStatus(origin + '/robots.txt', { head: true });
  const sitemap = L.curlStatus(origin + '/sitemap.xml', { head: true });
  const siteFindings = [];
  if (!(robots && robots < 400)) siteFindings.push({ sev: 'niedrig', was: `robots.txt nicht erreichbar (HTTP ${robots ?? '–'})`, fix: 'robots.txt bereitstellen (auch minimal), Sitemap darin verlinken.', url: origin + '/robots.txt' });
  if (!(sitemap && sitemap < 400)) siteFindings.push({ sev: 'mittel', was: `sitemap.xml nicht erreichbar (HTTP ${sitemap ?? '–'})`, fix: 'XML-Sitemap generieren und unter /sitemap.xml ausliefern.', url: origin + '/sitemap.xml' });

  // Title-Duplikate über Seiten
  const byTitle = {};
  for (const p of pages) if (p.title) (byTitle[p.title] = byTitle[p.title] || []).push(p.url);
  for (const [t, urls] of Object.entries(byTitle)) if (urls.length > 1)
    siteFindings.push({ sev: 'mittel', was: `Title "${t.slice(0, 50)}" ${urls.length}× identisch`, fix: 'Je Seite einen eindeutigen Title vergeben.', url: urls[0] });

  // kaputte interne Links (dedupe über alle Seiten, gedeckelt)
  const allLinks = [...new Set(pages.flatMap(p => p.internalLinks || []))].slice(0, MAX_LINKCHECK);
  let checked = 0;
  for (const u of allLinks) {
    let code = L.curlStatus(u, { head: true });
    if (code === 405 || code === 501) code = L.curlStatus(u, { head: false });  // HEAD verboten -> GET
    checked++;
    if (code != null && code >= 400) siteFindings.push({ sev: 'hoch', was: `interner Link kaputt (HTTP ${code})`, fix: 'Link korrigieren oder entfernen; ggf. 301 auf Ziel.', url: u });
  }

  const allFindings = [...siteFindings, ...pages.flatMap(p => (p.findings || []).length ? p.findings : (p.error ? [{ sev: 'hoch', was: `Seite nicht abrufbar: ${p.error}`, fix: 'Erreichbarkeit prüfen.', url: p.url }] : []))];
  allFindings.sort((a, b) => SEV[b.sev] - SEV[a.sev]);
  return { site, host, pages: pages.length, links_checked: checked, findings: allFindings };
}

function ampel(findings) {
  if (findings.some(f => f.sev === 'hoch')) return '🔴 rot';
  if (findings.some(f => f.sev === 'mittel')) return '🟡 gelb';
  return '🟢 grün';
}

function writeReport(res) {
  fs.mkdirSync(OUTDIR, { recursive: true });
  const f = path.join(OUTDIR, L.slug(res.site.name) + '.md');
  const g = { hoch: [], mittel: [], niedrig: [] };
  for (const x of res.findings) g[x.sev].push(x);
  const lines = [
    `# SEO-Audit · ${res.site.name}`, '',
    `**Ampel:** ${ampel(res.findings)}  ·  ${res.pages} Seiten geprüft  ·  ${res.links_checked} interne Links  ·  ${res.findings.length} Befund(e)`,
    `**Stand:** ${L.localIso()}  ·  ${res.site.url}`, ''
  ];
  for (const sev of ['hoch', 'mittel', 'niedrig']) {
    if (!g[sev].length) continue;
    lines.push(`## ${sev === 'hoch' ? 'Hoch' : sev === 'mittel' ? 'Mittel' : 'Niedrig'} (${g[sev].length})`, '');
    for (const x of g[sev]) lines.push(`- **${x.was}**`, `  - URL: ${x.url}`, `  - Fix: ${x.fix}`);
    lines.push('');
  }
  if (!res.findings.length) lines.push('_Keine technischen Mängel gefunden._', '');
  lines.push('_Automatischer Audit (seo-audit, token-frei). Nur Lesezugriff, nichts verändert._', '');
  fs.writeFileSync(f, lines.join('\n'));
  return path.relative(L.BASE, f).split(path.sep).join('/');
}

function main() {
  const cfg = L.readJson(CFG, null);
  if (!cfg || !Array.isArray(cfg.sites) || !cfg.sites.length) fail('config/sites.json fehlt oder leer');
  if (!L.haveTool('curl')) fail("'curl' nicht gefunden – ohne curl kein Audit");

  A.status('running', 'Audit', 10, `${cfg.sites.length} Sites…`);
  const outputs = [], details = [];
  cfg.sites.forEach((site, i) => {
    const res = auditSite(site);
    if (res.error) { details.push(`${site.name}: ${res.error}`); return; }
    outputs.push(writeReport(res));
    const top = res.findings.filter(x => x.sev === 'hoch').length;
    details.push(`${site.name}: ${ampel(res.findings)}, ${res.findings.length} Befunde${top ? `, ${top} hoch` : ''}`);
    A.status('running', 'Audit', 10 + Math.round(80 * (i + 1) / cfg.sites.length), `${site.name} fertig`);
  });

  const summary = `SEO-Audit ${L.nowKW()}: ${outputs.length} Sites — ` + details.map(d => d.split(':')[0].trim()).join(', ');
  A.status('ok', 'Fertig', 100, summary, details, outputs);
  // Routine-Zeile in den Themen-Kanal (reports) – wie der LLM-Agent (respektiert quiet).
  A.routine(`🔎 **SEO-Audit ${L.nowKW()}** fertig: ${details.join(' · ')}`);
  process.stdout.write(JSON.stringify({ result: summary, engine: 'script' }) + '\n');
  process.exit(0);
}

try { main(); } catch (e) { fail(String(e && e.stack || e)); }
