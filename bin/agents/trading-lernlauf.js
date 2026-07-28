'use strict';
/* TOKEN-FREIER taeglicher Lernlauf des Trading-Bots (engine=script -> 0 Tokens).
 *
 * Baut das Evidenzpaket (inkl. Forensik + Nachrichten-Zuordnung) und laesst den Optimizer
 * die Backlog-/Gitter-Kandidaten bewerten: Walk-Forward ueber mehrere Symbole + ein
 * unberuehrter Holdout. Was den Holdout besteht, promotet promote.py nach config.local.json;
 * JEDES Urteil - angenommen wie verworfen - landet im Gedaechtnis (state/memory.jsonl). So
 * baut sich die Erinnerung Tag fuer Tag von selbst auf, ohne Modell und ohne Rueckfrage.
 *
 * Arbeitsteilung: dieser Lauf ist die deterministische Fleissarbeit. Der woechentliche
 * LLM-Agent 'trading-forscher' liest dieselbe Forensik und setzt die klugen, aus Muster +
 * Nachrichtenlage abgeleiteten Hypothesen obendrauf. Faellt eine Woche aus, laeuft dieser
 * hier trotzdem weiter. Reine Rechenarbeit, echte Zahlen, nichts nach aussen. */
const fs = require('fs');
const path = require('path');
const L = require('./lib');

const A = L.agent('trading-lernlauf');
const BOT = path.join(L.BASE, 'trading-bot');
const RC = path.join(BOT, 'research_cycle.py');

function venvPython() {
  const cands = process.platform === 'win32'
    ? [path.join(BOT, '.venv', 'Scripts', 'python.exe')]
    : [path.join(BOT, '.venv', 'bin', 'python')];
  for (const p of cands) if (fs.existsSync(p)) return p;
  return process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
}

function main() {
  const py = venvPython();

  A.status('running', 'Evidenz', 20, 'Baue Evidenzpaket…');
  A.log('evidence: ' + py + ' research_cycle.py evidence');
  const ev = L.run(py, [RC, 'evidence'], { timeoutMs: 120000 });
  if (!ev.ok) {
    A.log('evidence fehlgeschlagen: ' + (ev.err || ev.out).slice(0, 300));
    A.status('error', 'Evidenz fehlgeschlagen', 0, 'research_cycle.py evidence brach ab');
    process.exit(ev.code || 1);
  }

  // Bewertung: token-frei, aber rechenintensiv (pandas + hmmlearn). Grosszuegiges Limit,
  // bleibt aber unter dem 30-min-Haenge-Schutz von run-agent.sh.
  A.status('running', 'Bewertung', 55, 'Optimizer (Walk-Forward + Holdout)…');
  A.log('evaluate: ' + py + ' research_cycle.py evaluate');
  const r = L.run(py, [RC, 'evaluate'], { timeoutMs: 26 * 60 * 1000 });
  A.log((r.out || '').slice(-600));
  if (!r.ok) {
    A.log('evaluate fehlgeschlagen: ' + (r.err || '').slice(0, 300));
    A.status('error', 'Bewertung fehlgeschlagen', 0, 'research_cycle.py evaluate brach ab');
    process.exit(r.code || 1);
  }

  // Ergebnis aus dem Report ziehen -> EIN knapper Einzeiler, kein Roman.
  const rep = L.readJson(path.join(BOT, 'state', 'learning_report.json'), {});
  const mem = rep.memory || {};
  const promoted = rep.promoted;
  const tested = rep.tested || 0;
  let line;
  if (promoted && promoted.changes) {
    line = '📈 Lernlauf: übernommen ' + JSON.stringify(promoted.changes) +
           ` · Gedächtnis ${mem.accepted || 0}✅/${mem.rejected || 0}❌`;
  } else {
    line = `🔬 Lernlauf: ${tested} Kandidat(en) geprüft, nichts bestand den Holdout` +
           ` · Gedächtnis ${mem.accepted || 0}✅/${mem.rejected || 0}❌ (${mem.total || 0} gesamt)`;
  }
  A.routine(line, { minMinutes: 60 });
  A.status('ok', 'Fertig', 100, promoted ? 'Parameter übernommen' : `${tested} geprüft, 0 übernommen`,
    [{ label: 'Getestet', value: String(tested) },
     { label: 'Gedächtnis', value: `${mem.accepted || 0}✅ / ${mem.rejected || 0}❌` },
     { label: 'Übernommen', value: promoted ? 'ja' : 'nein' }]);
  A.log('fertig: ' + line);
}

try {
  main();
} catch (e) {
  try { A.status('error', 'Abgebrochen', 0, String((e && e.message) || e).slice(0, 120)); } catch (_) {}
  process.stderr.write(String((e && e.stack) || e) + '\n');
  process.exit(1);
}
