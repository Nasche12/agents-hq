'use strict';
/* Monats-Cadence 'monatlich <n>. <Wochentag> HH:MM' (z. B. 'monatlich 1. Mi 07:00' = erster Mittwoch
   des Monats). Rein und ohne Seiteneffekte, damit testbar (server.js startet beim Laden einen Server).
   z = { wd: 0-6 (So=0), min: Minuten seit 00:00, date: 'JJJJ-MM-TT' } in der Zeitzone aus schedule.json.
   Rueckgabe: null = keine Monats-Cadence (beginnt nicht mit 'monatlich') · true/false = jetzt im Nachhol-Fenster fällig oder nicht.
   Der n-te Wochentag liegt immer am Tag (n-1)*7+1 … n*7; n = 1..4 (5. Wochentag gibt es nicht in jedem Monat). */
const CAD_WD = { mo: 1, di: 2, mi: 3, do: 4, fr: 5, sa: 6, so: 0 };
const MONTHLY_RE = /^monatlich\s+([1-4])\.\s*(mo|di|mi|do|fr|sa|so)\s+(\d{1,2}):(\d{2})\s*$/;

function monthlyDue(cad, z, catchup) {
  const c = (cad || '').toLowerCase().trim();
  if (!c.startsWith('monatlich')) return null;
  const m = MONTHLY_RE.exec(c);
  if (!m) return false;                       // kaputte Monats-Cadence feuert nie (nicht als 'täglich' fehlinterpretieren)
  const n = +m[1], hh = +m[3], mm = +m[4];
  if (hh > 23 || mm > 59) return false;
  if (z.wd !== CAD_WD[m[2]]) return false;
  const day = parseInt(String(z.date).slice(8, 10), 10);
  if (!(day >= (n - 1) * 7 + 1 && day <= n * 7)) return false;
  const sched = hh * 60 + mm;
  return z.min >= sched && z.min < sched + catchup;
}

/* Naechster Termin (fuer Doku/Tests): Datum 'JJJJ-MM-TT' des n-ten Wochentags im Monat (year, month 1-12). */
function nthWeekday(year, month, n, wd) {
  const first = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  return 1 + ((wd - first + 7) % 7) + (n - 1) * 7;
}

module.exports = { monthlyDue, nthWeekday, CAD_WD };
