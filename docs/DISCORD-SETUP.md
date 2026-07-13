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
DISCORD_APP_ID=...           # Dev-Portal → General Information → Application ID
DISCORD_PUBLIC_KEY=...       # Dev-Portal → General Information → Public Key (für Slash-Signaturen)
DISCORD_COMMAND_CHANNEL=freigaben   # hier landen Freigabe-Fragen (/ja /nein /go)
DISCORD_LOG_CHANNEL=agent-logs      # technische Meldungen/Heartbeat
```

**4. Struktur anlegen, Slash-Commands registrieren, Service starten:**

```
python3 bin/discord.py setup          # legt Kategorien/Kanäle idempotent an
python3 bin/discord-register.py       # registriert /status /run /ja /nein /go /master …
sudo bash deploy/install-service.sh   # zieht .env via EnvironmentFile
```

**5. Interactions-Endpoint freischalten (nur für Slash-Commands):**

- Plesk → Domain `agents.naschberger.info` → nginx-Direktiven → Block aus
  `deploy/nginx-proxy.conf` einfügen (enthält jetzt auch `/discord/interactions`).
  Dieser Pfad muss **ohne Passwortschutz** erreichbar sein – Discord kann sich nicht per
  Basic-Auth anmelden; die Echtheit sichert die ed25519-Signaturprüfung in `server.js`.
- Dev-Portal → deine App → **General Information → Interactions Endpoint URL**:
  `https://agents.naschberger.info/discord/interactions` → Speichern. Discord schickt einen
  signierten PING; klappt die Prüfung, wird die URL akzeptiert.

### Steuerung per Slash-Commands (nativ, mit Autocomplete)

| Kommando | Wirkung |
| --- | --- |
| `/status` | Ampel-Übersicht aller Agents (nur du siehst die Antwort) |
| `/offen` | nur Waits und Fehler |
| `/run <agent>` | Lauf sofort starten |
| `/ja <agent>` | einen als *fällig* gemeldeten Lauf freigeben und starten |
| `/nein <agent>` | diesen fälligen Lauf überspringen (Frage kommt zum nächsten Termin wieder) |
| `/go [agent]` | Freigabe: wartender Agent führt seine Aktion aus (z. B. Mailversand) |
| `/master <frage>` | Frage an den Master (kostet Tokens) |
| `/agents`, `/help` | Liste bzw. Hilfe |

Zusätzlich läuft die **Text-Bridge** weiter: `#freigaben` wird gepollt, du kannst dort auch frei
tippen (`status`, `<agent>`, `go`, oder eine **Frage mit `?`** an den Master).

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

- **Auto-Scheduler (zeitzonen-fest):** `server.js` liest `config/schedule.json` und rechnet
  die Zeit über die `zeitzone` (Intl, unabhängig von der Server-TZ). Intervalle (`alle 60 min`)
  sind an der Uhr ausgerichtet; Wochentag/Uhrzeit-Läufe feuern nur im Nachhol-Fenster
  (`catchup_minuten`, Default 120) – verpasst der Server die Zeit um mehr, wird übersprungen
  statt zu einer „zufälligen" Uhrzeit zu feuern.
- **Leichte** Agents (z. B. `uptime-waechter`) starten automatisch; **schwere**
  (`wochenreport`, `content-recherche`, `seo-audit`) posten in `#freigaben`
  „⏳ fällig – `/ja` / `/nein`". `/nein` überspringt; die Frage kommt zum nächsten Termin wieder.
- **Finanz** (`belege-buchhaltung`, `rechnungssteller`) hat aktuell **keinen Termin**
  (`enabled:false` / `auf Abruf`) – nur per `/run` bzw. auf Zuruf.
- **Tägliche Lage:** Zur Uhrzeit `DISCORD_MASTER_DAILY` (Default 07:30) postet der
  `kommandant` **eine** knappe Lage-Zeile (Ampel, Waits/Fehler zuerst) nach `#agent-logs`.
- **`next_run` im Dashboard** wird vom Scheduler direkt aus `schedule.json` gesetzt –
  Log/Report/Dashboard können nicht mehr auseinanderdriften.
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
**Einen Agent wieder terminieren:** `"enabled": true` und eine `cadence` setzen
(z. B. `"Mo 09:00"` oder `"alle 90 min"`).

Die Zeit rechnet der Scheduler selbst über `"zeitzone"` in `schedule.json` (via Intl),
also **unabhängig** von der Server-TZ. `install-service.sh` setzt zusätzlich `TZ=Europe/Vienna`
für die Agent-Läufe (Datumsangaben in Reports).
