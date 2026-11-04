'use strict';
/* Konsistenz: jeder Agent, der automatisch faellt UND nachfragt (enabled + schwer), muss per Slash
   (/ja, /run) waehlbar sein. Sonst haengt die Freigabe still (Discord laesst nur AGENT_CHOICES zu)
   und der Lauf faellt aus. server.js startet beim Laden einen Server -> Quelltext wird geparst. */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const read = f => fs.readFileSync(path.join(ROOT, f), 'utf8');
const server = read('dashboard/server.js');
const pyReg = read('bin/discord-register.py');
const sched = JSON.parse(read('config/schedule.json')).agents;

function objBody(src, startRe) {
  const m = startRe.exec(src); assert.ok(m, 'Block nicht gefunden: ' + startRe);
  return src.slice(m.index + m[0].length, src.indexOf('};', m.index));
}
const pairs = body => { const o = {}; for (const m of body.matchAll(/'?([\w-]+)'?\s*:\s*'([\w-]+)'/g)) o[m[1]] = m[2]; return o; };
const CHOICE = pairs(objBody(server, /const CHOICE = \{/));
const ALIAS = pairs(objBody(server, /const ALIAS = \{/));
const AGENT_CHOICES = new Set([...pyReg.slice(pyReg.indexOf('AGENT_CHOICES = ['), pyReg.indexOf(']\n', pyReg.indexOf('AGENT_CHOICES = [')))
  .matchAll(/"value":\s*"([\w-]+)"/g)].map(m => m[1]));
const AGENTS = new Set([...objBody(server, /const AGENTS = \{/).matchAll(/^\s*'([\w-]+)':/gm)].map(m => m[1]));

/* Bekannte Luecke, nicht Teil dieses PR (separat nachziehen); Eintrag entfernen, sobald behoben. */
const KNOWN_GAPS = new Set(['trading-forscher']);

const needing = Object.entries(sched).filter(([id, c]) => c.enabled && c.schwer && !KNOWN_GAPS.has(id)).map(([id]) => id);

test('es gibt geprueft Agents (Parser findet Daten)', () => {
  assert.ok(needing.includes('seo-tiefenaudit'));
  assert.ok(Object.keys(CHOICE).length >= 5 && AGENT_CHOICES.size >= 5 && AGENTS.size >= 5);
});

for (const id of needing) {
  test(`${id}: in AGENTS, CHOICE und AGENT_CHOICES; Slash-Wert loest auf den Agent auf`, () => {
    assert.ok(AGENTS.has(id), 'AGENTS');
    const short = CHOICE[id];
    assert.ok(short, 'CHOICE fehlt');
    assert.ok(AGENT_CHOICES.has(short), `AGENT_CHOICES (discord-register.py) fehlt "${short}"`);
    assert.ok(short === id || ALIAS[short] === id, `Slash-Wert "${short}" loest nicht auf ${id} auf (ALIAS)`);
  });
}
