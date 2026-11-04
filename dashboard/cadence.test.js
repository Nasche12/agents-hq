'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { monthlyDue, nthWeekday } = require('./cadence');

const CAD = 'monatlich 1. Mi 07:00';
const z = (wd, min, date) => ({ wd, min, date });

test('keine Monats-Cadence -> null (bestehende Parser-Zweige bleiben zuständig)', () => {
  for (const c of ['Mi 06:00', '06:00', 'alle 60 min', 'auf Abruf', '', undefined]) assert.strictEqual(monthlyDue(c, z(3, 420, '2026-11-04'), 120), null);
});

test('erster Mittwoch, im Fenster -> fällig', () => {
  assert.strictEqual(monthlyDue(CAD, z(3, 7 * 60, '2026-11-04'), 120), true);
  assert.strictEqual(monthlyDue(CAD, z(3, 8 * 60 + 59, '2026-11-04'), 120), true);
  assert.strictEqual(monthlyDue(CAD.toUpperCase(), z(3, 7 * 60, '2026-12-02'), 120), true);
});

test('vor der Zeit oder nach dem Nachhol-Fenster -> nicht fällig', () => {
  assert.strictEqual(monthlyDue(CAD, z(3, 6 * 60 + 59, '2026-11-04'), 120), false);
  assert.strictEqual(monthlyDue(CAD, z(3, 9 * 60, '2026-11-04'), 120), false);
});

test('zweiter bis fünfter Mittwoch und andere Wochentage -> nicht fällig', () => {
  assert.strictEqual(monthlyDue(CAD, z(3, 450, '2026-11-11'), 120), false);
  assert.strictEqual(monthlyDue(CAD, z(3, 450, '2026-11-25'), 120), false);
  assert.strictEqual(monthlyDue(CAD, z(4, 450, '2026-11-05'), 120), false);
});

test('Tag 7 zählt noch als erster, Tag 8 nicht (Monatsgrenze)', () => {
  assert.strictEqual(monthlyDue(CAD, z(3, 450, '2027-07-07'), 120), true);
  assert.strictEqual(monthlyDue(CAD, z(3, 450, '2027-07-14'), 120), false);
});

test('n-ter Wochentag: 3. Freitag', () => {
  assert.strictEqual(monthlyDue('monatlich 3. Fr 08:30', z(5, 8 * 60 + 30, '2026-11-20'), 120), true);
  assert.strictEqual(monthlyDue('monatlich 3. Fr 08:30', z(5, 8 * 60 + 30, '2026-11-13'), 120), false);
});

test('kaputte Monats-Cadence feuert nie (nicht als täglich lesen)', () => {
  for (const c of ['monatlich 07:00', 'monatlich 5. Mi 07:00', 'monatlich 1. Xx 07:00', 'monatlich 1. Mi 25:00', 'monatlich']) {
    assert.strictEqual(monthlyDue(c, z(3, 450, '2026-11-04'), 120), false, c);
  }
});

test('nthWeekday: erster Mittwoch', () => {
  assert.strictEqual(nthWeekday(2026, 11, 1, 3), 4);
  assert.strictEqual(nthWeekday(2026, 12, 1, 3), 2);
  assert.strictEqual(nthWeekday(2027, 1, 1, 3), 6);
});
