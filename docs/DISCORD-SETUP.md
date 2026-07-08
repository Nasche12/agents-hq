# Discord als dein Arbeitsplatz – Setup

Ich kann keinen Discord-Server für dich erstellen (braucht deinen Account) –
mit dieser Anleitung steht er in ~15 Minuten.

## Schritt 1: Server anlegen

Discord → "+" → "Eigenen Server erstellen" → Name z. B. "Naschberger HQ".

## Schritt 2: Kanalstruktur (bewährt für deinen Workflow)

```
📌 STEUERUNG
 ├ #freigaben      ← Agents posten hier, was auf dein Go wartet (Mails, Pakete)
 └ #agent-logs     ← Status jedes automatischen Laufs (ok/Fehler)

📊 KUNDEN
 ├ #reports        ← Wochenreport-Zusammenfassungen + PDF-Entwürfe
 └ #kunden-notizen ← deine Notizen, die Agents als Kontext nutzen dürfen

💶 FINANZEN
 ├ #belege         ← neue/unklare Belege, Rückfragen des Belege-Agents
 └ #verkauf        ← Verkaufs-Pakete, Status pro Website

🎬 CONTENT
 ├ #content        ← Wochen-Contentplan; hier postest du auch den Fokus der Woche
 └ #ideen          ← Ideenpool / verworfene Ideen
```

## Schritt 3: Webhooks anlegen (einfachste, sichere Anbindung)

Pro Ziel-Kanal: Kanal-Einstellungen → Integrationen → Webhooks → Neuer Webhook
→ URL kopieren. In die `.env` auf dem Server:

```
DISCORD_WEBHOOK_REPORTS=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_BELEGE=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_CONTENT=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_FREIGABEN=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_LOGS=https://discord.com/api/webhooks/...
```

Webhooks können nur POSTEN, nichts lesen – ideal: Agents melden Ergebnisse,
Entscheidungen triffst nur du.

## Schritt 4: Arbeits-Rhythmus

- **Mo 09:00** Belege-Agent läuft → Rückfragen in #belege beantworten
- **Fr 08:00** Report-Agent läuft → Entwürfe in #freigaben prüfen → "Go" →
  Versand (per Cron-Folgeprompt oder von Hand)
- **So 17:00** Content-Agent läuft → Plan in #content, Fokus für nächste Woche posten

## Zwei-Wege-Steuerung (Bot) – Discord als Fernbedienung

Damit Discord dein Kommandokanal wird (du steuerst die Website-Agents von
unterwegs, die Agents melden zurück), brauchst du einen Bot statt reiner Webhooks.

**1. Bot anlegen:** Discord Developer Portal → New Application → Bot →
Token kopieren. Unter *Privileged Gateway Intents* **Message Content Intent**
einschalten (nötig, damit der Bot deine Kommandos lesen darf).

**2. Einladen:** OAuth2 → URL Generator → Scope `bot`, Rechte
*View Channels, Send Messages, Read Message History, Manage Channels*
(letzteres nur fürs einmalige `setup`). Link öffnen, Bot auf deinen Server holen.

**3. `.env` auf dem Server:**

```
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...          # Server-ID (Rechtsklick auf Server → ID kopieren, Entwicklermodus an)
DISCORD_COMMAND_CHANNEL=freigaben   # hier tippst du Kommandos
DISCORD_LOG_CHANNEL=agent-logs      # hierhin melden Agents Start/Ende
```

**4. Struktur anlegen & Service neu starten:**

```
python3 bin/discord.py setup          # legt Kategorien/Kanäle idempotent an
sudo bash deploy/install-service.sh   # zieht .env jetzt via EnvironmentFile
```

Der `server.js`-Service pollt `#freigaben` alle ~12 s und führt deine Kommandos aus.

### Was du in #freigaben tippen kannst

| Kommando | Wirkung |
| --- | --- |
| `status` | Lage aller Agents |
| `run wochenreport` / nur `wochenreport` | Lauf starten |
| `wochenreport: nur naschberger.info` | Lauf mit eigenem Auftrag |
| `go` / `go wochenreport` | Freigabe: wartender Agent führt seine Aktion aus (z. B. Mailversand) |
| `agents` | bekannte Agents auflisten |
| `help` | Kommandoliste |

### Rückmeldung der Agents (automatisch)

`bin/run-agent.sh` postet für **jeden** Lauf ohne Zutun:
- `▶️ <agent> gestartet` → `#agent-logs`
- `✅ <agent> fertig: <Fazit>` bzw. `❌ … Fehler` → `#agent-logs`
- `⏳ <agent> wartet auf dein Go …` → `#freigaben` (du antwortest mit `go <agent>`)

Zusätzlich posten Agents ihre Kernergebnisse selbst in den passenden Kanal
(`bin/discord.py post reports "…" --attach report.pdf`). Nur Kunden-E-Mails
brauchen weiterhin dein Go.

### Schnelltest

```
python3 bin/discord.py post agent-logs "Bridge-Test ✅"   # Ausgabe muss im Kanal erscheinen
python3 bin/discord.py read freigaben --limit 5 --json    # zeigt letzte Nachrichten als JSON
```

Webhooks (oben) und Bot schließen sich nicht aus – der Bot kann alles, was die
Webhooks können, plus Lesen. Wer nur Ergebnisse will, bleibt bei Webhooks.

## Der Bot arbeitet wie der Master (Scheduler + Chat)

Sobald der Service läuft, ist der HQ nicht mehr nur reaktiv:

- **Auto-Scheduler:** `server.js` liest `config/schedule.json` und feuert fällige
  Läufe von selbst. **Leichte** Agents (z. B. `uptime-waechter`) starten automatisch;
  **schwere** (`wochenreport`, `content-recherche`, `seo-audit`) posten in `#freigaben`
  „⏳ fällig – starten?" und warten auf `run <agent>` (schützt den Server, du behältst die Kontrolle).
- **Tägliche Lage:** Zur Uhrzeit `DISCORD_MASTER_DAILY` (Default 07:30) läuft der
  `kommandant` und postet die Gesamtlage (Ampel je Agent, offene Waits/Fehler) nach `#agent-logs`.
- **Master-Chat (token-sparsam):** Ein deterministischer Filter beantwortet zuerst alles,
  was ohne LLM geht – `status`, `offen`, lockere Startbefehle mit Aliasen („mach die belege",
  „prüf die erreichbarkeit", „starte den report"), Bestätigungen („danke" → still). Der
  **Master (LLM, kostet Tokens) läuft nur**, wenn du eine echte **Frage mit `?`** stellst oder
  die Nachricht mit `master …` / `kommandant …` beginnst. So bleibt der Chat natürlich, ohne
  bei jedem Wort Tokens zu verbrennen.

Umschalten (in `.env`):

```
DISCORD_SCHEDULER=off        # Auto-Feuern ganz aus
DISCORD_MASTER_DAILY=        # keine tägliche Lage (leer)
```

**Schwere Läufe voll automatisch** statt Rückfrage: in `config/schedule.json` beim
jeweiligen Agent `"schwer": false` setzen – dann startet der Scheduler ihn ohne Nachfrage.

Zeit richtet sich nach der Serverzeit; `install-service.sh` setzt `TZ=Europe/Vienna`
passend zur `zeitzone` in `schedule.json`.
