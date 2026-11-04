'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { auditSite, normUrl, isHtmlResource, ampel, renderReport, sitemapUrls, orphanKey, sameSite } = require('./seo-audit');
const L = require('./lib');
const X = require('./seo-checks');

/* curl laeuft synchron (spawnSync) -> Testserver muss in eigenem Prozess laufen. */
const HOME = `<!doctype html><html lang="de"><head><title>Beispielseite fuer den SEO-Audit Test</title>
<meta name="description" content="${'x'.repeat(80)}"><link rel="canonical" href="/"></head>
<body><h1>Hallo</h1><a href="/">slash</a><a href="/#top">frag</a><a href="/cv/a.pdf">pdf</a><a href="/lade">lade</a><a href="">leer</a><a href=''>leer2</a>
<a href="/gone">gone</a><a href="/hang">hang</a><a href="http://127.0.0.1:1/fremd">fremderport</a></body></html>`;
const LADE = '<!doctype html><html><head><title>Ladeseite fuer den SEO-Audit Test hier</title></head><body><h1>x</h1><p>wird geladen ...</p></body></html>';
const SERVER = `
const http = require('http'); const HOME = ${JSON.stringify(HOME)}; const LADE = ${JSON.stringify(LADE)};
http.createServer((q, r) => {
  if (q.url === '/cv/a.pdf') { r.writeHead(200, { 'content-type': 'application/pdf' }); return r.end('%PDF-1.4'); }
  if (q.url === '/lade') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(LADE); }
  if (q.url === '/gone') { r.writeHead(404, { 'content-type': 'text/html' }); return r.end('<html><body>nicht gefunden</body></html>'); }
  if (q.url === '/hang') { q.socket.destroy(); return; }
  if (q.url === '/redir') { r.writeHead(302, { location: 'http://localhost:' + q.socket.localPort + '/' }); return r.end(); }
  if (q.url === '/robots.txt') {   // untrusted: Option-Injection, file://, fremder Host, fremder Port
    r.writeHead(200, { 'content-type': 'text/plain' });
    return r.end('User-agent: *\\nSitemap: -K' + process.env.SEO_TEST_CFG + '\\nSitemap: file:///etc/passwd\\nSitemap: http://' + q.headers.host + '/sitemap.xml\\n');
  }
  if (q.url === '/sitemap.xml') {
    r.writeHead(200, { 'content-type': 'application/xml' });
    return r.end('<urlset><url><loc>http://' + q.headers.host + '/ok</loc></url><url><loc>http://127.0.0.1:1/evil</loc></url>' +
      '<url><loc>file:///etc/passwd</loc></url><url><loc>http://localhost:1/x</loc></url><url><loc>http://' + q.headers.host + '/amp?a=1&amp;b=2</loc></url></urlset>');
  }
  if (q.url === '/') { r.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); return r.end(HOME); }
  r.writeHead(404); r.end();
}).listen(0, '127.0.0.1', function () { console.log(this.address().port); });`;
const TMPD = fs.mkdtempSync(path.join(os.tmpdir(), 'seo-test-'));
const fwd = p => p.split(path.sep).join('/');
const PWNED = fwd(path.join(TMPD, 'pwned.txt'));
process.env.SEO_TEST_CFG = fwd(path.join(TMPD, 'evil.cfg'));   // der Testserver (eigener Prozess) liest ihn
process.on('exit', () => { try { fs.rmSync(TMPD, { recursive: true, force: true }); } catch (e) {} });
const E = () => ({ findings: [], measurements: [], notMeasured: [] });
const MOCK = { geo: () => E(), psi: () => E(), gsc: () => E() };

test('normUrl: leerer Pfad = /, Fragment weg, Host lowercase, Slash bei Pfaden unangetastet', () => {
  assert.strictEqual(normUrl('https://Example.COM'), 'https://example.com/');
  assert.strictEqual(normUrl('https://example.com/a/#x'), 'https://example.com/a/');
  assert.strictEqual(normUrl('https://example.com/a'), 'https://example.com/a');
});

test('isHtmlResource: Content-Type vor Endung', () => {
  assert.ok(isHtmlResource('text/html', 'https://x.at/a.pdf'));
  assert.ok(!isHtmlResource('application/pdf', 'https://x.at/a'));
  assert.ok(!isHtmlResource('', 'https://x.at/a.pdf'));
  assert.ok(isHtmlResource('', 'https://x.at/a'));
});

test('auditSite (Mocks): PDF ohne Seiten-Befunde, Platzhalter + Schema + nicht gemessen', async () => {
  const child = spawn(process.execPath, ['-e', SERVER], { stdio: ['ignore', 'pipe', 'inherit'] });
  try {
    const port = await new Promise(res => child.stdout.once('data', d => res(String(d).trim())));
    const res = auditSite({ name: 'test', url: `http://127.0.0.1:${port}` }, MOCK);
    assert.strictEqual(res.pages, 3);                    // "/" + PDF + /lade, nicht "" und "/" getrennt
    assert.deepStrictEqual(res.findings.filter(f => f.url.endsWith('.pdf')), []);
    assert.ok(!res.findings.some(f => /identisch/.test(f.was)));
    assert.ok(res.findings.some(f => /Lade-Platzhalter/.test(f.was) && f.url.endsWith('/lade')));
    assert.ok(res.findings.some(f => /Organization|JSON-LD/.test(f.was)));   // kein Schema -> hoch
    assert.ok(res.findings.some(f => f.sev === 'mittel' && /Open Graph/.test(f.was)));
    assert.ok(res.notMeasured.length > 0);               // IP-Host: HTTPS-Checks nicht messbar
    assert.strictEqual(ampel(res.findings, res.notMeasured), '🔴 rot');
    assert.match(renderReport(res), /## Nicht gemessen/);
    assert.ok(!res.findings.some(f => /%22/.test(f.url)));                                  // M2: href="" / href=''
    assert.ok(!res.findings.some(f => f.url.endsWith('/gone') && !/kaputt/.test(f.was)));   // M3: nur "Link kaputt", keine Seiten-Checks
    assert.ok(res.findings.some(f => f.url.endsWith('/gone') && /HTTP 404/.test(f.was)));
    assert.ok(!res.findings.some(f => f.url.includes('127.0.0.1:1/')));                     // M6: anderer Port = andere Site
    assert.ok(res.notMeasured.some(n => /nicht prüfbar/.test(n)));                          // M4: /hang (Abbruch) = nicht gemessen
  } finally { child.kill(); }
});

test('ampel: ungemessen ist nie gruen', () => {
  assert.strictEqual(ampel([], []), '🟢 grün');
  assert.strictEqual(ampel([], ['x']), '🟡 gelb');
  assert.strictEqual(ampel([{ sev: 'mittel' }], []), '🟡 gelb');
  assert.strictEqual(ampel([{ sev: 'niedrig' }], []), '🟢 grün');
  assert.strictEqual(ampel([{ sev: 'kritisch' }], []), '🔴 rot');
});

test('cwvFindings: Schwellen, fehlende Felddaten = nicht gemessen', () => {
  const j = {
    loadingExperience: { metrics: { LARGEST_CONTENTFUL_PAINT_MS: { percentile: 4500 }, CUMULATIVE_LAYOUT_SHIFT_SCORE: { percentile: 15 } } },
    lighthouseResult: { categories: { performance: { score: 0.42 } } }
  };
  const r = X.cwvFindings({ json: j }, 'https://x.at/');
  assert.ok(r.findings.some(f => f.sev === 'hoch' && /LCP/.test(f.was)));
  assert.ok(r.findings.some(f => f.sev === 'mittel' && /CLS/.test(f.was)));
  assert.ok(r.findings.some(f => f.label === 'proxy' && /Lighthouse/.test(f.was)));
  assert.ok(r.notMeasured.some(n => /INP/.test(n)));
  const none = X.cwvFindings({ json: { lighthouseResult: {} } }, 'https://x.at/');
  assert.strictEqual(none.findings.length, 0);
  assert.ok(none.notMeasured.length >= 3);
  const err = X.cwvFindings({ json: { error: { message: 'Quota exceeded' } } }, 'https://x.at/');
  assert.ok(/Quota/.test(err.notMeasured[0]));
});

test('psi ohne API-Key: nicht gemessen, kein Netzwerkaufruf', () => {
  const old = process.env.PAGESPEED_API_KEY; delete process.env.PAGESPEED_API_KEY;
  try { assert.match(X.psi('https://x.at/').notMeasured[0], /kein API-Key/); }
  finally { if (old !== undefined) process.env.PAGESPEED_API_KEY = old; }
});

test('gsc: ohne Credentials nicht angebunden; mit Mock Befunde', () => {
  const old = process.env.GSC_CREDENTIALS; delete process.env.GSC_CREDENTIALS;
  try { assert.match(X.gsc({ name: 'a' }, 'https://x.at/').notMeasured[0], /nicht angebunden/); }
  finally { if (old !== undefined) process.env.GSC_CREDENTIALS = old; }
  const r = X.gsc({ name: 'a' }, 'https://x.at/', () => ({
    prop: 'sc-domain:x.at', cur: { clicks: 50, impressions: 900, ctr: 0.05, position: 14 },
    prev: { clicks: 100, impressions: 1000, ctr: 0.1, position: 9 }, inspect: { verdict: 'NEUTRAL', coverage: 'Gefunden - zurzeit nicht indexiert' }
  }));
  assert.ok(r.findings.some(f => /Klicks -50/.test(f.was)));
  assert.ok(r.findings.some(f => f.sev === 'hoch' && /Index/.test(f.was)));
  assert.ok(r.findings.some(f => /Position/.test(f.was)));
});

test('mapGeoResult: Severity-Mapping, doppelte Bereiche weg, UA-Test = proxy', () => {
  const r = X.mapGeoResult({
    origin: 'https://x.at', ua_test: { GPTBot: 403 }, robots: { matrix: { GPTBot: { root_allowed: false }, Googlebot: { root_allowed: true } } },
    findings: [
      { severity: 'critical', area: 'AI crawlers', issue: 'GPTBot blocked', fix: 'f', url: null },
      { severity: 'medium', area: 'CDN/WAF', issue: 'x', fix: 'f' },
      { severity: 'high', area: 'On-page', issue: 'Title missing', fix: 'f' },
      { severity: 'info', area: 'Schema', issue: 'FAQ', fix: 'f' }]
  });
  assert.deepStrictEqual(r.findings.map(f => f.sev), ['kritisch', 'mittel']);
  assert.strictEqual(r.findings[1].label, 'proxy');
  assert.ok(r.measurements.some(m => /GPTBot=403/.test(m.text) && m.label === 'proxy'));
});

test('httpJson: Body-Verzeichnis wird auch bei Fehler entfernt, Datei nur 0600', () => {
  const list = () => fs.readdirSync(os.tmpdir()).filter(n => n.startsWith('seo-body-')).length;
  const before = list();
  const r = X.httpJson('http://127.0.0.1:1/', { body: { secret: 'token' }, timeout: 5 });
  assert.ok(r.error);
  assert.strictEqual(list(), before);
  if (process.platform !== 'win32') {                    // Rechte pruefen: Verzeichnis 0700 + Datei 0600
    const d = fs.mkdtempSync(path.join(os.tmpdir(), 'seo-body-'));
    try {
      fs.writeFileSync(path.join(d, 'b'), 'x', { mode: 0o600, flag: 'wx' });
      assert.strictEqual(fs.statSync(d).mode & 0o077, 0);
      assert.strictEqual(fs.statSync(path.join(d, 'b')).mode & 0o077, 0);
    } finally { fs.rmSync(d, { recursive: true, force: true }); }
  }
});

async function withServer(fn) {
  const child = spawn(process.execPath, ['-e', SERVER], { stdio: ['ignore', 'pipe', 'inherit'] });
  try {
    const port = await new Promise(res => child.stdout.once('data', d => res(String(d).trim())));
    return await fn(port);
  } finally { child.kill(); }
}

test('H1: robots/Sitemap als untrusted Input: -K-Option, file://, fremder Host/Port werden verworfen', async () => {
  await withServer(async port => {
    const origin = `http://127.0.0.1:${port}`;
    // Config, die bei Option-Injection (-K) eine Datei schreiben wuerde
    fs.writeFileSync(process.env.SEO_TEST_CFG, `url = "${origin}/"\noutput = "${PWNED}"\n`);
    const robots = L.curlBody(origin + '/robots.txt').body;
    assert.match(robots, /Sitemap: -K/);
    const urls = sitemapUrls(origin, robots);
    assert.deepStrictEqual(urls, [`${origin}/ok`, `${origin}/amp?a=1&b=2`]);
    assert.ok(!fs.existsSync(PWNED), 'curl hat -K aus der URL als Option ausgefuehrt');
    // Wrapper selbst: URL mit fuehrendem "-" ist keine Option, file:// ist gesperrt
    assert.ok(!L.curlBody('-K' + process.env.SEO_TEST_CFG).ok);
    assert.ok(!fs.existsSync(PWNED));
    assert.strictEqual(L.curlStatus('file:///etc/hosts'), null);
    assert.ok(!L.curlBody('file:///etc/hosts').ok);
  });
});

test('M6/L4: sameSite nach Schema+Port+Host; orphanKey ignoriert www und Trailing Slash', () => {
  assert.ok(sameSite('https://www.x.at/a', 'https://x.at/'));
  assert.ok(!sameSite('http://x.at/', 'https://x.at/'));
  assert.ok(!sameSite('https://x.at:8443/', 'https://x.at/'));
  assert.ok(!sameSite('file:///etc/passwd', 'https://x.at/'));
  assert.strictEqual(orphanKey('https://www.x.at/a/'), orphanKey('https://x.at/a'));
});

test('L3: geo-Rendering-Befund ersetzt unseren Duenn-Befund derselben URL', async () => {
  await withServer(async port => {
    const url = `http://127.0.0.1:${port}`;
    const base = auditSite({ name: 't', url }, MOCK);
    assert.ok(base.findings.some(f => /Dünner Inhalt/.test(f.was) && f.url === url + '/'));
    const geo = () => ({ ...E(), findings: [{ sev: 'kritisch', was: 'Rendering: Only 6 word(s) in raw HTML', fix: 'f', url: url + '/', label: 'gemessen' }] });
    const res = auditSite({ name: 't', url }, { ...MOCK, geo });
    assert.ok(!res.findings.some(f => /Dünner Inhalt/.test(f.was) && f.url === url + '/'));
    assert.ok(res.findings.some(f => /^Rendering/.test(f.was)));
  });
});

test('geoFailed-Fallback: nicht gemessen statt bestanden', async () => {
  await withServer(async port => {
    const geo = () => ({ ...E(), geoFailed: true, notMeasured: ['geo_audit.py nicht gelaufen (x)'] });
    const res = auditSite({ name: 't', url: `http://127.0.0.1:${port}` }, { ...MOCK, geo });
    assert.ok(res.notMeasured.some(n => /nicht lauffähig/.test(n)));
    assert.notStrictEqual(ampel([], res.notMeasured), '🟢 grün');
  });
  const old = process.env.PYTHON; process.env.PYTHON = 'definitiv-kein-python';
  try {
    const r = X.runGeo('http://127.0.0.1:1/', { baseDir: TMPD, slug: 'x', dry: true });
    assert.ok(r.geoFailed);
  } finally { if (old === undefined) delete process.env.PYTHON; else process.env.PYTHON = old; }
});

test('Drift: kritischer geo-Befund wird kritisch und Ampel rot', () => {
  const r = X.mapGeoResult({ origin: 'https://x.at', findings: [{ severity: 'critical', area: 'Drift', issue: 'New noindex (meta_robots)', fix: 'f', url: 'https://x.at/' }] });
  assert.strictEqual(r.findings[0].sev, 'kritisch');
  assert.strictEqual(ampel(r.findings, []), '🔴 rot');
});

test('M1: kaputter GSC-Key liefert {error}, keinen Abbruch', () => {
  const cred = path.join(TMPD, 'cred.json');
  fs.writeFileSync(cred, JSON.stringify({ private_key: 'x', client_email: 'a@b' }));
  const old = process.env.GSC_CREDENTIALS; process.env.GSC_CREDENTIALS = cred;
  try {
    const r = X.gscFetch({ name: 'a' }, 'https://x.at/');
    assert.ok(r.error);
    assert.match(X.gsc({ name: 'a' }, 'https://x.at/').notMeasured[0], /^GSC:/);
  } finally { if (old === undefined) delete process.env.GSC_CREDENTIALS; else process.env.GSC_CREDENTIALS = old; }
});

test('writeBodyFile: Verzeichnis 0700, Datei 0600 (nicht unter Windows), Aufraeumen', { skip: process.platform === 'win32' }, () => {
  const { dir, file } = X.writeBodyFile({ secret: 1 });
  assert.strictEqual(fs.statSync(file).mode & 0o077, 0);
  assert.strictEqual(fs.statSync(dir).mode & 0o077, 0);
  X.cleanupTmp();
  assert.ok(!fs.existsSync(dir));
});

test('M5: defekte Baseline -> .corrupt + neu; REFRESH ohne --compare; atomar (nur mit Python)', async t => {
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  if (!L.run(py, ['--version']).ok) return t.skip('kein Python');
  await withServer(async port => {
    const url = `http://127.0.0.1:${port}/`;
    const dir = path.join(TMPD, 'bl'); fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'k.json'), '{kaputt');
    const r1 = X.runGeo(url, { baseDir: dir, slug: 'k', dry: false });
    assert.ok(fs.existsSync(path.join(dir, 'k.json.corrupt')));
    JSON.parse(fs.readFileSync(path.join(dir, 'k.json'), 'utf8'));
    assert.ok(r1.measurements.some(m => /defekt/.test(m.text)));
    assert.ok(!fs.existsSync(path.join(dir, 'k.json.tmp')));
    process.env.SEO_BASELINE_REFRESH = '1';
    try {
      const r2 = X.runGeo(url, { baseDir: dir, slug: 'k', dry: false });
      assert.ok(r2.measurements.some(m => /Baseline erneuert/.test(m.text)));
      assert.ok(!r2.measurements.some(m => /Drift-Vergleich gegen/.test(m.text)));
    } finally { delete process.env.SEO_BASELINE_REFRESH; }
  });
});

test('L-E: Redirect auf fremden Host -> nur Befund, keine Seiten-Checks des Ziels', async () => {
  await withServer(async port => {
    const res = auditSite({ name: 't', url: `http://127.0.0.1:${port}/redir` }, MOCK);
    assert.ok(res.findings.some(f => f.sev === 'hoch' && /leitet auf fremden Host um/.test(f.was)));
    assert.ok(!res.findings.some(f => /Title|Meta-Description|canonical|<h1>/.test(f.was)));
  });
});

test('L-D: ohne Restbudget (>= 300 s) laeuft geo nicht, Status "Zeitbudget"', async () => {
  await withServer(async port => {
    const code = `const a = require(${JSON.stringify(path.join(__dirname, 'seo-audit.js'))});
      const E = () => ({ findings: [], measurements: [], notMeasured: [] });
      let geoCalled = false;
      const r = a.auditSite({ name: 't', url: 'http://127.0.0.1:${port}' }, { geo: () => { geoCalled = true; return E(); }, psi: E, gsc: E });
      console.log('JSON' + JSON.stringify({ geoCalled, nm: r.notMeasured }));`;
    const r = spawnSync(process.execPath, ['-e', code], { encoding: 'utf8', timeout: 60000, env: { ...process.env, SEO_BUDGET_MS: '1000', SEO_DRY_RUN: '1' } });
    const o = JSON.parse(r.stdout.split('\n').find(l => l.startsWith('JSON')).slice(4));
    assert.strictEqual(o.geoCalled, false);
    assert.ok(o.nm.some(n => /Zeitbudget/.test(n)));
  });
});

test('M-A/M-B/L-A/L-B: geo_audit.py Redirect auf file://, Sitemap-Zaehlung vor Filter, same_site-Randfaelle (nur mit Python)', t => {
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  if (!L.run(py, ['--version']).ok) return t.skip('kein Python');
  const r = L.run(py, ['-I', path.join(__dirname, 'fixtures', 'geo_harness.py'), path.join(__dirname, '..', 'lib', 'geo_audit.py')]);
  assert.strictEqual(r.code, 0, r.err);
  const o = JSON.parse(r.out.trim().split('\n').pop());
  assert.strictEqual(o.redir.error, 'blocked redirect scheme');           // M-A: 302 -> file://
  assert.strictEqual(o.redir.body, 0);
  assert.ok(!o.handlers.some(h => /File|FTP|Data/.test(h)));
  // L-A (kaputter Port) / L-B (Default-Port) / Gross-Schreibung / Host-Suffix-Trick
  assert.deepStrictEqual(o.same_site, [false, false, true, false, true, false, true, false]);
  assert.deepStrictEqual(o.same_host, [true, true, false, false, false]);   // robots: http+https desselben Hosts ok
  // M-B: fremde/andere Schemata werden auf der Rohliste gezaehlt und gemeldet, nur same_site wird ausgewertet
  assert.deepStrictEqual(o.sm1.urls, ['https://site.at/a']);
  assert.ok(o.sm1.issues.some(i => /^2 URLs on a different host/.test(i)));
  assert.ok(o.sm1.issues.some(i => /different scheme/.test(i)));
  // Alle robots-Sitemaps gefiltert -> Fallback auf /sitemap.xml + Meldung
  assert.ok(o.sm2.issues.some(i => /rejected/.test(i)));
  assert.deepStrictEqual(o.sm2.calls, ['https://site.at/sitemap.xml']);
});

test('L-C: Baseline-Speichern scheitert -> Notiz, kein Abbruch (nur mit Python)', async t => {
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  if (!L.run(py, ['--version']).ok) return t.skip('kein Python');
  await withServer(async port => {
    const blocker = path.join(TMPD, 'iststdatei'); fs.writeFileSync(blocker, 'x');
    const r = X.runGeo(`http://127.0.0.1:${port}/`, { baseDir: blocker, slug: 'z', dry: false });
    assert.ok(!r.geoFailed);
    assert.ok(r.measurements.some(m => /nicht gespeichert/.test(m.text)));
  });
});

test('thinInfo: Platzhalter und Wortzahl', () => {
  assert.ok(X.thinInfo('<body><div id="root">Seite wird geladen…</div></body>').placeholder);
  assert.strictEqual(X.thinInfo('<script>var a=1</script><p>eins zwei drei</p>').words, 3);
});

test('runGeo end-to-end (nur wenn Python da): Baseline anlegen, dann Drift-Vergleich', async t => {
  const { run } = require('./lib');
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  if (!run(py, ['--version']).ok) return t.skip('kein Python');
  const child = spawn(process.execPath, ['-e', SERVER], { stdio: ['ignore', 'pipe', 'inherit'] });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'seo-bl-'));
  try {
    const port = await new Promise(res => child.stdout.once('data', d => res(String(d).trim())));
    const url = `http://127.0.0.1:${port}/`;
    const r1 = X.runGeo(url, { baseDir: dir, slug: 't', dry: false });
    assert.ok(!r1.geoFailed, JSON.stringify(r1.notMeasured));
    assert.ok(fs.existsSync(path.join(dir, 't.json')));
    const r2 = X.runGeo(url, { baseDir: dir, slug: 't', dry: false });
    assert.ok(r2.measurements.some(m => /Drift-Vergleich/.test(m.text)));
  } finally { child.kill(); fs.rmSync(dir, { recursive: true, force: true }); }
});
