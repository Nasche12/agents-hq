'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { auditSite, normUrl, isHtmlResource, ampel, renderReport } = require('./seo-audit');
const X = require('./seo-checks');

/* curl laeuft synchron (spawnSync) -> Testserver muss in eigenem Prozess laufen. */
const HOME = `<!doctype html><html lang="de"><head><title>Beispielseite fuer den SEO-Audit Test</title>
<meta name="description" content="${'x'.repeat(80)}"><link rel="canonical" href="/"></head>
<body><h1>Hallo</h1><a href="/">slash</a><a href="/#top">frag</a><a href="/cv/a.pdf">pdf</a><a href="/lade">lade</a></body></html>`;
const LADE = '<!doctype html><html><head><title>Ladeseite fuer den SEO-Audit Test hier</title></head><body><h1>x</h1><p>wird geladen ...</p></body></html>';
const SERVER = `
const http = require('http'); const HOME = ${JSON.stringify(HOME)}; const LADE = ${JSON.stringify(LADE)};
http.createServer((q, r) => {
  if (q.url === '/cv/a.pdf') { r.writeHead(200, { 'content-type': 'application/pdf' }); return r.end('%PDF-1.4'); }
  if (q.url === '/lade') { r.writeHead(200, { 'content-type': 'text/html' }); return r.end(LADE); }
  if (q.url === '/') { r.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); return r.end(HOME); }
  r.writeHead(404); r.end();
}).listen(0, '127.0.0.1', function () { console.log(this.address().port); });`;
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
