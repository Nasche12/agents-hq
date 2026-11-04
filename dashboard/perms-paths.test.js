'use strict';
/* Rechte-Profile (.claude/perms/*.json): Pfadregeln fuer absolute Systempfade muessen //-Form haben.
   Claude-Code-Syntax: //pfad = absolut, ~/pfad = Home, /pfad = relativ zur Settings-Datei,
   pfad = relativ zum cwd. Ein "Write(/etc/**)" blockiert also NICHT /etc. */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const DIR = path.resolve(__dirname, '..', '.claude', 'perms');
const files = fs.readdirSync(DIR).filter(f => f.endsWith('.json'));
const load = f => JSON.parse(fs.readFileSync(path.join(DIR, f), 'utf8')).permissions;
const SYS = /^\/(etc|root|usr|bin|sbin|boot|var|home|proc|sys|lib|lib64|opt|dev|srv|mnt|run)(\/|$)/;

test('es gibt Profile', () => assert.ok(files.length >= 8));

for (const f of files) {
  test(`${f}: gueltiges JSON, keine einfach-slash Systempfade`, () => {
    const p = load(f);
    for (const rule of [...(p.allow || []), ...(p.deny || [])]) {
      const m = /^(Read|Edit|Write)\((.*)\)$/.exec(rule);
      if (m) assert.ok(!SYS.test(m[2]), `${f}: "${rule}" ist relativ zur Settings-Datei, gemeint ist //...`);
    }
  });
}

test('default.json: kein pauschales Write/Edit, Secrets gesperrt', () => {
  const p = load('default.json');
  assert.ok(!p.allow.includes('Write') && !p.allow.includes('Edit'), 'pauschales Write/Edit');
  for (const r of ['Read(.env)', 'Read(**/.env*)', 'Read(//proc/**)', 'Read(~/.claude/**)', 'Read(~/.claude.json)',
    'Read(~/.ssh/**)', 'Read(**/*.pem)', 'Write(//etc/**)', 'Edit(//etc/**)', 'Write(//root/**)', 'Write(~/.ssh/**)', 'Write(~/.claude/**)']) {
    assert.ok(p.deny.includes(r), `default.json deny fehlt ${r}`);
  }
});

test('seo-audit.json: keine weiten Bash-Rechte (LLM-Modus)', () => {
  const p = load('seo-audit.json');
  for (const a of p.allow) {
    assert.ok(!/^Bash\((curl|sed|awk|cat|head|tail|grep|egrep|cut|sort|uniq|wc|ls)\b/.test(a), `Bash zu weit: ${a}`);
  }
  assert.ok(p.deny.includes('Bash(curl:*)') && p.deny.includes('Bash(*>*)'));
});

/* Server-Realitaet: BASE liegt im Home des Service-Users. Kein Deny darf Allow-Schreibpfade unter BASE treffen. */
const esc = s => s.replace(/[.+^$()|{}[\]\\?]/g, '\\$&');
const rx = g => new RegExp('^' + g.split('**/').map(x => x.split('**').map(y => y.split('*')
  .map(esc).join('[^/]*')).join('.*')).join('(?:.*/)?') + '$');
const HOME = '/var/www/vhosts/fake', BASE = HOME + '/agents.naschberger.info';
const abs = pat => pat.startsWith('~/') ? HOME + pat.slice(1) : pat.startsWith('//') ? pat.slice(1)
  : pat.startsWith('/') ? BASE + pat : BASE + '/' + pat.replace(/^\.\//, '');
const SAMPLES = ['trading-bot/state/news_risk.json', 'master/lage.md', 'config/schedule.json', 'seo/monat-2026-12/x.md',
  'reports/2026-KW45/report.md', 'belege/daten.js'];
for (const f of files) {
  test(`${f}: kein Deny trifft Schreibpfade unter BASE (BASE im Home)`, () => {
    const p = load(f);
    const wr = (p.allow || []).map(r => /^(?:Write|Edit)\((.*)\)$/.exec(r)).filter(Boolean).map(m => m[1]);
    const dn = (p.deny || []).map(r => /^(?:Write|Edit)\((.*)\)$/.exec(r)).filter(Boolean).map(m => m[1]);
    for (const s of SAMPLES) {
      const full = BASE + '/' + s;
      if (!wr.some(a => rx(abs(a)).test(full))) continue;   // vom Profil gar nicht erlaubt
      for (const d of dn) assert.ok(!rx(abs(d)).test(full), `${f}: Deny "${d}" sperrt erlaubten Pfad ${s}`);
    }
  });
}
