'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { spawn } = require('node:child_process');
const { auditSite, normUrl, isHtmlResource } = require('./seo-audit');

/* curl laeuft synchron (spawnSync) -> Testserver muss in eigenem Prozess laufen. */
const HOME = `<!doctype html><html><head><title>Beispielseite fuer den SEO-Audit Test</title>
<meta name="description" content="${'x'.repeat(80)}"><link rel="canonical" href="/"></head>
<body><h1>Hallo</h1><a href="/">slash</a><a href="/#top">frag</a><a href="/cv/a.pdf">pdf</a></body></html>`;
const SERVER = `
const http = require('http'); const HOME = ${JSON.stringify(HOME)};
http.createServer((q, r) => {
  if (q.url === '/cv/a.pdf') { r.writeHead(200, { 'content-type': 'application/pdf' }); return r.end('%PDF-1.4'); }
  if (q.url === '/') { r.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); return r.end(HOME); }
  r.writeHead(404); r.end();
}).listen(0, '127.0.0.1', function () { console.log(this.address().port); });`;

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

test('auditSite: PDF ohne Seiten-Befunde, Startseite nicht doppelt', async () => {
  const child = spawn(process.execPath, ['-e', SERVER], { stdio: ['ignore', 'pipe', 'inherit'] });
  try {
    const port = await new Promise(res => child.stdout.once('data', d => res(String(d).trim())));
    const res = auditSite({ name: 'test', url: `http://127.0.0.1:${port}` });
    assert.strictEqual(res.pages, 2);                    // "/" + PDF, nicht "" und "/" getrennt
    const pdf = res.findings.filter(f => f.url.endsWith('.pdf'));
    assert.deepStrictEqual(pdf, []);
    assert.ok(!res.findings.some(f => /identisch/.test(f.was)));
  } finally { child.kill(); }
});
