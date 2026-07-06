# Agent HQ auf agents.naschberger.info (Plesk)

Das Dashboard ist eine statische Seite (dashboard/index.html + status.json) –
kein PHP, keine Datenbank. Die Roboter lesen alle 30 s status.json, das der
Cron-Wrapper bei jedem Agent-Lauf aktualisiert.

## Ordnerstruktur am Server (Ziel)

```
~/agents/                        ← Hauptordner (kommt von mir, kompletter Upload)
├── .claude/agents/              ← die 3 Agents
├── .env                         ← Umami + Discord (aus .env.example, chmod 600)
├── bin/run-agent.sh             ← Cron-Wrapper: führt Agent aus + pflegt Status
├── bin/status-update.sh         ← Status-Helper (nutzt auch der Agent selbst)
├── dashboard/index.html         ← Agent HQ
├── dashboard/status.json        ← Live-Status (wird automatisch geschrieben)
├── belege/  reports/  content/  logs/
```

## Schritt 1: Subdomain in Plesk

Plesk → Websites & Domains → Subdomain hinzufügen:
- Name: `agents`, Domain: `naschberger.info`
- Dokumentenstamm (Docroot): auf `agents/dashboard` zeigen lassen.
  Geht das bei deinem Plesk nicht außerhalb von httpdocs: Docroot-Standard lassen
  und stattdessen im Cron einen Sync ergänzen (siehe Schritt 4).
- SSL: "Let's Encrypt"-Zertifikat für agents.naschberger.info ausstellen.

## Schritt 2: Basic Auth (Pflicht – Finanz-/Kundendaten!)

Plesk → agents.naschberger.info → "Passwortgeschützte Verzeichnisse" →
Verzeichnis `/` schützen → Benutzer (z. B. `sebastian`) + starkes Passwort anlegen.

## Schritt 3: Cronjobs auf den Wrapper umstellen

Ersetzt die Cron-Zeilen aus DEPLOYMENT-PLESK.md:

```cron
0 8 * * 5  ~/agents/bin/run-agent.sh wochenreport "Nutze den Subagent wochenreport und erstelle die Wochenreports für die abgelaufene Woche."
0 9 * * 1  ~/agents/bin/run-agent.sh belege-buchhaltung "Nutze den Subagent belege-buchhaltung und verarbeite alle neuen Belege in belege/inbox/."
0 17 * * 0 ~/agents/bin/run-agent.sh content-recherche "Nutze den Subagent content-recherche und erstelle den Contentplan für die kommende Woche."
```

Der Wrapper setzt automatisch: Status `running` beim Start, `ok`/`error` am Ende,
Log-Auszug ins Dashboard. Zusätzlich weist er den Agent an, Zwischenstände zu
melden (`bin/status-update.sh`) – daher zeigen die Sprechblasen live, was der
Agent gerade tut, und `waiting`, wenn er auf dein Go wartet.

## Schritt 4 (nur falls Docroot nicht umbiegbar): Sync ins httpdocs

```cron
* * * * * cp ~/agents/dashboard/status.json ~/httpdocs/agents/status.json 2>/dev/null
```
(index.html einmalig nach ~/httpdocs/agents/ kopieren.)

## Schritt 5: Test

1. `https://agents.naschberger.info` öffnen → Login → Haus mit 3 Robotern, Status "wartet".
2. Von Hand starten: `~/agents/bin/run-agent.sh wochenreport "…"` → Roboter im
   Report-Büro muss auf "läuft" (cyan, blinkend) springen, Sprechblase wechselt.
3. Klick auf Roboter → Detail-Panel: Phase, Fortschritt, Ergebnisse, Log.

## Status-Kontrakt (falls du mal was Eigenes anbinden willst)

`status.json` → `agents.<id>`: `status` (idle|running|ok|waiting|error),
`phase`, `progress` 0–100, `message` (Sprechblase, ≤34 Zeichen),
`details[]`, `outputs[]`, `last_run`, `next_run`, `log_tail`.

## Mission-Control-API (optional, empfohlen)

Das Dashboard funktioniert statisch (status.json). Für ▶ START, Live-Log und
Reports-Liste muss zusätzlich der kleine Node-Server laufen:

```bash
node dashboard/server.js 8788        # lokal testen: http://localhost:8788
```

Am Plesk-Server: als Node.js-App anlegen (Startdatei dashboard/server.js) oder
per Cron/`nohup` starten und die Subdomain per Reverse-Proxy auf den Port leiten.
Endpoints: POST /api/run/<agent>, GET /api/log/<agent>, /api/reports, /api/file?p=…
Der Server nutzt bin/run-agent.sh mit denselben Prompts wie die Cronjobs.
