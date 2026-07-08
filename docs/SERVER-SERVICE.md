# Agent HQ als Dauer-Service (server.js)

Damit die interaktiven Teile des Dashboards funktionieren (START-Buttons, Reports-Tab,
Live-Log, **Steuerung + Eingabefeld an den Kommandant im Datacenter**), muss
`dashboard/server.js` dauerhaft laufen. Ohne Service ist alles nur Anzeige.

Architektur: Node lauscht lokal auf `127.0.0.1:8788`, Plesk reicht nur `/api/` dorthin
weiter. Das Dashboard und die Datenfiles bleiben statisch über Plesk (schnell, gecacht).

## 1. Service installieren (als root)

```bash
cd /var/www/vhosts/naschberger.info/agents.naschberger.info
git pull
bash deploy/install-service.sh
```

Das Skript ermittelt den richtigen User/Node-Pfad selbst, schreibt
`/etc/systemd/system/agents-hq.service`, startet ihn (`enable --now`) und testet
`/api/ping`. Anderer Port? `PORT=9000 bash deploy/install-service.sh`.

## 2. Plesk: /api/ an den Service proxien

Plesk → Domain **agents.naschberger.info** → **Apache & nginx Settings** →
**Zusätzliche nginx-Direktiven** → Inhalt von `deploy/nginx-proxy.conf` einfügen →
Übernehmen. (Port anpassen, falls nicht 8788.)

## 3. Prüfen

- `curl -s http://127.0.0.1:8788/api/ping` → `{"api":true,...}`
- Dashboard öffnen → Fußzeile zeigt **API: VERBUNDEN**.
- Master (magenta, Korridor-Mitte) → Datacenter: Steuerung/Eingabefeld sind aktiv.

## Betrieb

| Aktion | Befehl |
| --- | --- |
| Live-Logs | `journalctl -u agents-hq -f` |
| Neustart (nach `git pull`) | `systemctl restart agents-hq` |
| Stoppen | `systemctl stop agents-hq` |
| Status | `systemctl status agents-hq` |

## Sicherheit

- Node bindet nur `127.0.0.1` – von außen nicht direkt erreichbar, nur über den
  Plesk-Proxy. Deshalb greift der **Passwortschutz der Domain** (Plesk → Zugriffsschutz)
  auch für `/api/`. Diesen Schutz aktiviert lassen: sonst kann jeder mit der URL
  Agent-Läufe auslösen.
- Der Service läuft als Subscription-User (nicht root) – Voraussetzung dafür, dass
  `claude --dangerously-skip-permissions` überhaupt startet.
- Der `ANTHROPIC_API_KEY` kommt weiterhin aus `.env` (der Wrapper exportiert ihn an die
  Agent-Läufe); der Service selbst braucht ihn nicht.

## Warum keine Datenbank

Status, Uptime-Verlauf und Zeitplan liegen als JSON-Dateien
(`dashboard/status.json` bzw. `httpdocs/status.json`, `uptime/uptime.json`,
`config/schedule.json`). Die überleben Neustarts und brauchen keine Dependencies.
Eine echte DB würde nur für Monate an Verlauf lohnen – dann via Node-eigenem
`node:sqlite` ohne npm install. Aktuell nicht nötig.
