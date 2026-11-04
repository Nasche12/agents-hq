'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { fileHeaders } = require('./filehdr');

test('PDF ohne Sandbox, aber nosniff + no-store', () => {
  const h = fileHeaders('application/pdf');
  assert.strictEqual(h['Content-Security-Policy'], undefined);
  assert.strictEqual(h['X-Content-Type-Options'], 'nosniff');
  assert.strictEqual(h['Cache-Control'], 'no-store');
});

test('alle anderen Typen mit Sandbox und nosniff', () => {
  for (const t of ['text/html; charset=utf-8', 'image/svg+xml', 'text/plain; charset=utf-8', 'application/octet-stream',
    'application/json; charset=utf-8', 'image/png', 'text/javascript; charset=utf-8']) {
    const h = fileHeaders(t);
    assert.strictEqual(h['Content-Security-Policy'], 'sandbox', t);
    assert.strictEqual(h['X-Content-Type-Options'], 'nosniff', t);
    assert.strictEqual(h['Content-Type'], t);
  }
});
