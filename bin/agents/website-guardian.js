#!/usr/bin/env node
'use strict';
/* TOKEN-FREIER website-guardian. Woechentlicher Tiefen-Check per curl – ersetzt den
   `claude -p`-Lauf 1:1. Regeln aus .claude/agents/website-guardian.md: jeder Befund aus
   echtem curl-Output belegbar, keine "koennte sein"-Befunde, nur GET/HEAD, nichts aendern.
   KEIN Browser -> JS/Formulare/Mobile werden NICHT geprueft und das steht klar im Bericht. */
const fs = require('fs');
const path = require('path');
const L = require('./lib');

const A = L.agent('website-guardian');
const CFG = path.join(L.BASE, 'config', 'sites.json');
const OUTDIR = path.join(L.BASE, 'guardian', L.nowKW());
const ALERTDIR = path.join(L.BASE, 'guardian', 'alerts');
const MAX_PAGES = 9, MAX_LINKCHECK = 40;
const CH_ALERT = process.env.DISCORD_COMMAND_CHANNEL || 'freigaben';
const SEV = { hoch: 3, mittel: 2, niedrig: 1 };

function fail(msg) {
  A.log('FEHLER: ' + msg);
  A.status('error', 'Abgebrochen', 0, msg.slice(0, 200));
  process.stdout.write(JSON.stringify({ result: 'website-guardian: ' + msg }) + '\n');
  process.exit(1);
}

/* ---------- curl-Header-Helfer ---------- */
function curlHead(url, follow) {
  const args = ['-sSI', '--max-time', '20'];
  if (follow) args.push('-L');
  args.push(url);
  const r = L.run('curl', args, { timeoutMs: 26000 });
  return { ok: r.ok && /^HTTP\//m.test(r.out), raw: r.out, err: r.err };
}
const headerBlocks = raw => raw.split(/\r?\n\r?\n/).map(b => b.trim()).filter(Boolean);
const statusOf = blk => { const m = blk.match(/^HTTP\/[\d.]+\s+(\d+)/m); return m ? parseInt(m[1], 10) : null; };
const headerVal = (blk, name) => { const m = blk.match(new RegExp('^' + name + ':\\s*(.+)$', 'im')); return m ? m[1].trim() : null; };

/* ---------- HTML-Helfer ---------- */
function links(html, baseUrl) {
  const out = []; const re = /<a\b[^>]*\bhref\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))/gi; let m;
  while ((m = re.exec(html))) {
    const raw = (m[1] || m[2] || m[3] || '').trim();
    if (!raw || raw.startsWith('#') || /^(mailto:|tel:|javascript:|data:)/i.test(raw)) continue;
    try { out.push(new URL(raw, baseUrl).href.split('#')[0]); } catch (e) {}
  }
  return out;
}
function metaNoindex(html) {
  const m = html.match(/<meta\b[^>]*name=["']robots["'][^>]*>/i);
  return m ? /noindex/i.test(m[0]) : false;
}
function mixedContent(html) {                            // http://-Referenzen in src=/href= auf HTTPS-Seiten
  const re = /\b(?:src|href)\s*=\s*(?:"|')?(http:\/\/[^"'\s>]+)/gi; const out = []; let m;
  while ((m = re.exec(html)) && out.length < 8) out.push(m[1]);
  return [...new Set(out)];
}
function robotsBlocksAll(txt) {                          // User-agent: * mit Disallow: / (ganze Site)
  const lines = txt.split(/\r?\n/).map(l => l.replace(/#.*$/, '').trim());
  let inStar = false, blocked = false;
  for (const l of lines) {
    const ua = l.match(/^user-agent:\s*(.+)$/i);
    if (ua) { inStar = ua[1].trim() === '*'; continue; }
    if (inStar) { const d = l.match(/^disallow:\s*(.*)$/i); if (d && d[1].trim() === '/') blocked = true; }
  }
  return blocked;
}

function guardSite(site) {
  const url = site.url; let host, origin;
  try { const u = new URL(url); host = u.hostname; origin = u.origin; } catch (e) { return { site, error: 'ungültige URL' }; }
  A.log(`guard ${site.name} …`);
  const f = [];
  const add = (sev, was, fix, u) => f.push({ sev, was, fix, url: u || url });

  // 1) HTTP -> HTTPS
  const bare = host.replace(/^www\./, '');
  const httpHead = curlHead('http://' + host + '/', false);
  if (httpHead.ok) {
    const blk = headerBlocks(httpHead.raw)[0] || '';
    const st = statusOf(blk), loc = headerVal(blk, 'location');
    const ok = [301, 308, 302, 307].includes(st) && loc && /^https:\/\//i.test(loc);
    if (!ok) add('hoch', `kein HTTP→HTTPS-Redirect (http lieferte ${st ?? '?'}${loc ? ', Location ' + loc : ''})`, 'HTTP dauerhaft per 301 auf HTTPS umleiten.', 'http://' + host + '/');
  } // http nicht erreichbar (Port 80 zu) -> kein Befund, nicht pruefbar

  // 2) Finale Header der Startseite (Security-Header)
  const fh = curlHead(url, true);
  const finalBlk = (headerBlocks(fh.raw).pop()) || '';
  if (fh.ok) {
    if (!headerVal(finalBlk, 'strict-transport-security')) add('hoch', 'Strict-Transport-Security (HSTS) fehlt', 'HSTS-Header setzen: `Strict-Transport-Security: max-age=31536000; includeSubDomains`.');
    if (!headerVal(finalBlk, 'content-security-policy')) add('mittel', 'Content-Security-Policy fehlt', 'CSP-Header einführen (mind. `default-src`), schützt vor XSS/Injection.');
    const xcto = headerVal(finalBlk, 'x-content-type-options');
    if (!xcto || !/nosniff/i.test(xcto)) add('niedrig', 'X-Content-Type-Options: nosniff fehlt', '`X-Content-Type-Options: nosniff` setzen.');
    const csp = headerVal(finalBlk, 'content-security-policy') || '';
    if (!headerVal(finalBlk, 'x-frame-options') && !/frame-ancestors/i.test(csp)) add('mittel', 'Klickjacking-Schutz fehlt (X-Frame-Options / frame-ancestors)', '`X-Frame-Options: SAMEORIGIN` oder CSP `frame-ancestors` setzen.');
    if (!headerVal(finalBlk, 'referrer-policy')) add('niedrig', 'Referrer-Policy fehlt', '`Referrer-Policy: strict-origin-when-cross-origin` setzen.');
    // X-Robots-Tag: noindex auf der Startseite = kritisch
    const xr = headerVal(finalBlk, 'x-robots-tag');
    if (xr && /noindex/i.test(xr)) add('hoch', `Startseite auf noindex (X-Robots-Tag: ${xr})`, 'noindex entfernen – Seite ist sonst aus dem Index.');
  }

  // 3) www/non-www-Konsistenz
  const e1 = L.curlMetric('https://' + bare + '/');
  const e2 = L.curlMetric('https://www.' + bare + '/');
  if (e1.ok && e2.ok) {
    try {
      const c1 = new URL(e1.url_eff).hostname, c2 = new URL(e2.url_eff).hostname;
      if (c1 !== c2) add('mittel', `www/non-www uneinheitlich (${c1} vs ${c2})`, 'Eine kanonische Form wählen, die andere per 301 dorthin umleiten.');
    } catch (e) {}
  }

  // 4) robots.txt
  const rStatus = L.curlStatus(origin + '/robots.txt', { head: true });
  if (!(rStatus && rStatus < 400)) add('niedrig', `robots.txt nicht erreichbar (HTTP ${rStatus ?? '–'})`, 'robots.txt bereitstellen und Sitemap darin verlinken.', origin + '/robots.txt');
  else { const rb = L.curlBody(origin + '/robots.txt'); if (robotsBlocksAll(rb.body || '')) add('hoch', 'robots.txt blockiert die GANZE Site (User-agent: * / Disallow: /)', 'Globales `Disallow: /` entfernen oder gezielt einschränken.', origin + '/robots.txt'); }

  // 5) sitemap.xml
  const smStatus = L.curlStatus(origin + '/sitemap.xml', { head: true });
  if (!(smStatus && smStatus < 400)) add('mittel', `sitemap.xml nicht erreichbar (HTTP ${smStatus ?? '–'})`, 'XML-Sitemap unter /sitemap.xml ausliefern.', origin + '/sitemap.xml');
  else { const smb = L.curlBody(origin + '/sitemap.xml'); if (!/<(urlset|sitemapindex)/i.test(smb.body || '')) add('niedrig', 'sitemap.xml nicht wohlgeformt (<urlset>/<sitemapindex> fehlt)', 'Gültige XML-Sitemap generieren.', origin + '/sitemap.xml'); }

  // 6) Crawl: Startseite + bis zu 8 Hauptseiten -> noindex(meta), Mixed-Content, interne Links
  const home = L.curlBody(url);
  const pages = [{ u: url, body: home.body || '' }];
  const seen = new Set([url.split('#')[0]]);
  for (const lu of links(home.body || '', url)) {
    if (pages.length >= MAX_PAGES) break;
    try { if (new URL(lu).hostname !== host) continue; } catch (e) { continue; }
    if (seen.has(lu)) continue; seen.add(lu);
    pages.push({ u: lu, body: L.curlBody(lu).body || '' });
  }
  for (const p of pages) {
    if (metaNoindex(p.body)) add(p.u === url ? 'hoch' : 'mittel', `noindex im HTML (<meta robots>)`, 'noindex entfernen, wenn die Seite indexiert werden soll.', p.u);
    const mc = mixedContent(p.body);
    if (mc.length) add('mittel', `Mixed-Content: ${mc.length} http://-Referenz(en)`, 'Alle Ressourcen über https:// laden (sonst Browser-Warnung/Blockade).', p.u);
  }
  // kaputte interne Links (dedupe, gedeckelt)
  const allLinks = [...new Set(pages.flatMap(p => links(p.body, p.u).filter(u => { try { return new URL(u).hostname === host; } catch (e) { return false; } })))].slice(0, MAX_LINKCHECK);
  let checked = 0;
  for (const lu of allLinks) {
    let code = L.curlStatus(lu, { head: true });
    if (code === 405 || code === 501) code = L.curlStatus(lu, { head: false });
    checked++;
    if (code != null && code >= 400) add('hoch', `interner Link kaputt (HTTP ${code})`, 'Link korrigieren/entfernen oder 301 auf Ziel.', lu);
  }

  f.sort((a, b) => SEV[b.sev] - SEV[a.sev]);
  return { site, host, pages: pages.length, links_checked: checked, findings: f };
}

function ampel(f) { return f.some(x => x.sev === 'hoch') ? '🔴 rot' : f.some(x => x.sev === 'mittel') ? '🟡 gelb' : '🟢 grün'; }

function writeReport(res) {
  fs.mkdirSync(OUTDIR, { recursive: true });
  const file = path.join(OUTDIR, L.slug(res.site.name) + '.md');
  const g = { hoch: [], mittel: [], niedrig: [] };
  for (const x of res.findings) g[x.sev].push(x);
  const lines = [
    `# Website-Guardian · ${res.site.name}`, '',
    `**Ampel:** ${ampel(res.findings)}  ·  ${res.pages} Seiten  ·  ${res.links_checked} interne Links  ·  ${res.findings.length} Befund(e)`,
    `**Stand:** ${L.localIso()}  ·  ${res.site.url}`, ''
  ];
  for (const sev of ['hoch', 'mittel', 'niedrig']) {
    if (!g[sev].length) continue;
    lines.push(`## ${sev[0].toUpperCase() + sev.slice(1)} (${g[sev].length})`, '');
    for (const x of g[sev]) lines.push(`- **${x.was}**`, `  - URL: ${x.url}`, `  - Fix: ${x.fix}`);
    lines.push('');
  }
  if (!res.findings.length) lines.push('_Keine Mängel in den geprüften Punkten._', '');
  lines.push('> **Nicht geprüft (kein Browser):** JavaScript-Fehler, Formular-Absenden und mobile Darstellung – das braucht Playwright, das hier nicht eingerichtet ist.', '',
    '_Automatischer Tiefen-Check (website-guardian, token-frei). Nur GET/HEAD, nichts verändert._', '');
  fs.writeFileSync(file, lines.join('\n'));
  return path.relative(L.BASE, file).split(path.sep).join('/');
}

function main() {
  const cfg = L.readJson(CFG, null);
  if (!cfg || !Array.isArray(cfg.sites) || !cfg.sites.length) fail('config/sites.json fehlt oder leer');
  if (!L.haveTool('curl')) fail("'curl' nicht gefunden – ohne curl kein Tiefen-Check");

  A.status('running', 'Tiefen-Check', 10, `${cfg.sites.length} Sites…`);
  const outputs = [], details = [];
  let anyHoch = false;
  fs.mkdirSync(ALERTDIR, { recursive: true });

  cfg.sites.forEach((site, i) => {
    const res = guardSite(site);
    if (res.error) { details.push(`${site.name}: ${res.error}`); return; }
    outputs.push(writeReport(res));
    const hoch = res.findings.filter(x => x.sev === 'hoch');
    if (hoch.length) {
      anyHoch = true;
      const af = path.join(ALERTDIR, `${L.isoDate()}_${L.slug(site.name)}.md`);
      const al = [`# Guardian-Alert · ${site.name}`, '', `- **Zeit:** ${L.localIso()}`, `- **URL:** ${site.url}`, '', '**Hoch-Befunde:**',
        ...hoch.map(x => `- ${x.was} — ${x.url}\n  Fix: ${x.fix}`), '', '_Automatischer Entwurf. Kein Versand._', ''];
      try { fs.writeFileSync(af, al.join('\n')); outputs.push(path.relative(L.BASE, af).split(path.sep).join('/')); } catch (e) {}
    }
    details.push(`${site.name}: ${ampel(res.findings)}, ${res.findings.length} Befunde${hoch.length ? `, ${hoch.length} hoch` : ''}`);
    A.status('running', 'Tiefen-Check', 10 + Math.round(80 * (i + 1) / cfg.sites.length), `${site.name} fertig`);
  });

  const summary = `Guardian ${L.nowKW()}: ${outputs.filter(o => !o.includes('/alerts/')).length} Sites — ${details.join(' · ')}`;
  A.status('ok', 'Fertig', 100, summary, details, outputs);
  A.routine(`🛡️ **Website-Guardian ${L.nowKW()}**: ${details.join(' · ')}`);
  if (anyHoch) A.discord(CH_ALERT, `🛡️ **Guardian**: Hoch-Befunde — ${details.filter(d => /hoch/.test(d)).join(' · ')}`);
  process.stdout.write(JSON.stringify({ result: summary, engine: 'script' }) + '\n');
  process.exit(0);
}

try { main(); } catch (e) { fail(String(e && e.stack || e)); }
