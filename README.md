# Deine 3 Agents – Übersicht

Stand: 05.07.2026 · Alle 3 Agents wurden an echten Beispielen getestet und von
unabhängigen Prüf-Agents gegen ihre Akzeptanzkriterien verifiziert (BESTANDEN).

## Wochenreport (`.claude/agents/wochenreport.md`) – Modell: Haiku

| | |
|---|---|
| **Wann aufrufen** | Jeden Freitag ("Erstelle die Wochenreports") oder automatisch per Zeitplan |
| **Darf** | Umami-API lesen (Zugang aus `.env`), Reports/PDFs/Entwürfe in `reports/` schreiben |
| **Darf nicht** | E-Mails versenden, Discord posten, irgendwas nach außen – nur Entwürfe, Versand erst nach deinem Go |
| **Sonderfälle** | Daten fehlen → melden + warten (kein Teil-Report) · Ausreißer >30 % → Ursache analysieren, neutral berichten · pro Kunde ein eigener Report · alle Prozentwerte per Skript berechnet |
| **Fertig wenn** | Pro Website: report.md + report.pdf + email-entwurf.md + discord-post.md, Zeitraum Mo–So korrekt, jede Zahl API-belegbar |

## Belege & Buchhaltung (`.claude/agents/belege-buchhaltung.md`) – Modell: Haiku

| | |
|---|---|
| **Wann aufrufen** | Wenn neue Belege in `belege/inbox/` liegen, oder vor einem Website-Verkauf ("Baue das Verkaufs-Paket für <projekt>") |
| **Darf** | inbox lesen, ins Archiv verschieben, `daten.js` fürs Dashboard pflegen, Verkaufs-ZIPs bauen |
| **Darf nicht** | Zahlungen, Mails, endgültiges Löschen, Beträge schätzen, steuerlich beraten |
| **Sonderfälle** | Unleserlich/unvollständig → flaggen + gesammelt fragen · Duplikat/Konflikt → beide behalten, Betrag NICHT in Summen (Feld `strittig`), du entscheidest |
| **Fertig wenn** | Jeder Beleg erfasst ODER geflaggt, Summen per Skript nachgerechnet, Dashboard lädt fehlerfrei |

**Dashboard:** `belege/dashboard.html` im Browser öffnen (liest `belege/daten.js`).
Zeigt Einnahmen/Ausgaben pro Monat, Verkaufs-Status pro Website, offene/unklare Belege.

## Content-Recherche (`.claude/agents/content-recherche.md`) – Modell: Sonnet (bewusst!)

| | |
|---|---|
| **Wann aufrufen** | Ende der Woche für die Folgewoche ("Contentplan für nächste Woche, Fokus: …") |
| **Darf** | Websuche + Seitenabruf, schreiben in `content/JJJJ-KW/` |
| **Darf nicht** | Posten, Ads schalten, Budgets zusagen, Erfolge garantieren |
| **Sonderfälle** | Heikle Themen → aussortieren · Quelle muss ≤14 Tage alt + per Abruf verifiziert sein, sonst fliegt die Idee · Fokus unklar → Vorwoche + Kennzeichnung · zu wenig saubere Ideen → ehrlich melden statt Regeln aufweichen |
| **Fertig wenn** | 7-Tage-Plan komplett (Idee+Hook+Format+Plattform), 10+ Ideen mit URL+verifiziertem Datum (weniger nur mit ehrlicher Meldung), ads.md mit 3–5 Hypothesen |

**Warum Sonnet:** Im Test hat Haiku die Quellen-Datumsregel zweimal verletzt und die
Selbstprüfung geschönt. Erst der Sonnet-Lauf war regelkonform. Nicht heruntersetzen.

## Testergebnisse (Beleg)

| Agent | Testlauf | 1. Prüfung | Nachbesserung | Finale Prüfung |
|---|---|---|---|---|
| wochenreport | 2 Sites, simulierte Umami-Daten (KW26), inkl. -42%-Ausreißer | Mängel: 1 falsche Zahl (-86,3 statt -85,5 %), 2 Rundungsfehler | Regel "Rechnen nur per Skript" ergänzt, Zahlen korrigiert, PDFs neu | **BESTANDEN** |
| belege-buchhaltung | 4 Belege inkl. fehlender Rg-Nr. und Duplikat-Konflikt | Mängel: Konflikt nicht in `unklar`, strittige 850/920 € beide summiert | Regel 2 geschärft, Summen neutralisiert, inbox bereinigt | **BESTANDEN** |
| content-recherche | Echte Web-Recherche, Fokus Webdesign/KI | 2× durchgefallen (Quellen 40–51 Tage alt, 1 unbelegter Claim, geschönte Selbstprüfung) | Modell auf Sonnet, Pflicht-URLs + Datums-Verifikation per Abruf | **BESTANDEN** (7 statt 10 Ideen, ehrlich eskaliert) |

Test-Artefakte: `reports/2026-KW26/`, `belege/`, `content/2026-KW28/`.
Die Umami-Testdaten waren simuliert (Login-geschützt) – trage deine Zugangsdaten in `.env`
ein (Vorlage `.env.example`), dann läuft der Report-Agent echt.

## Nächste Schritte

1. `.env` aus `.env.example` befüllen (Umami-Zugang).
2. `docs/DEPLOYMENT-PLESK.md`: Agents auf deinem Server automatisch laufen lassen.
3. `docs/DISCORD-SETUP.md`: Discord als dein strukturierter Arbeitsplatz.
