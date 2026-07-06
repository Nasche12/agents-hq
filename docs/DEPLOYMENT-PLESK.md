# Deployment: Agents automatisch auf deinem Server (Plesk)

Ziel: Die 3 Agents laufen ohne dein Zutun auf deinem Server und legen Ergebnisse
ab / posten sie in Discord. Basis ist Claude Code (headless) auf dem Server.

## Voraussetzungen

- SSH-Zugang zum Server (bei Plesk meist vorhanden)
- Node.js ≥ 18 auf dem Server (in Plesk unter "Node.js" aktivierbar oder via nvm)
- Ein Anthropic-API-Key (console.anthropic.com) ODER Claude-Abo-Login

## Schritt 1: Claude Code installieren

```bash
ssh dein-user@dein-server
npm install -g @anthropic-ai/claude-code
claude --version
```

Authentifizieren: `claude` einmal interaktiv starten und einloggen,
oder API-Key setzen: `export ANTHROPIC_API_KEY=sk-ant-...` (in ~/.bashrc).

## Schritt 2: Projektordner anlegen

```bash
mkdir -p ~/agents && cd ~/agents
# Diesen kompletten Paket-Ordner hochladen (scp/SFTP/Plesk-Dateimanager):
#   .claude/agents/  belege/  docs/  .env.example
cp .env.example .env && nano .env   # Umami-Zugang + Discord-Webhooks eintragen
chmod 600 .env
```

## Schritt 3: Cronjobs (Plesk: "Geplante Aufgaben" oder crontab -e)

```cron
# Freitag 08:00 – Wochenreport
0 8 * * 5  cd ~/agents && claude -p "Nutze den Subagent wochenreport und erstelle die Wochenreports für die abgelaufene Woche." --dangerously-skip-permissions >> logs/wochenreport.log 2>&1

# Montag 09:00 – Belege verarbeiten
0 9 * * 1  cd ~/agents && claude -p "Nutze den Subagent belege-buchhaltung und verarbeite alle neuen Belege in belege/inbox/." --dangerously-skip-permissions >> logs/belege.log 2>&1

# Sonntag 17:00 – Contentplan für die Folgewoche
0 17 * * 0 cd ~/agents && claude -p "Nutze den Subagent content-recherche und erstelle den Contentplan für die kommende Woche. Fokus: siehe letzte Nachricht in Discord #content, sonst Vorwochen-Fokus." --dangerously-skip-permissions >> logs/content.log 2>&1
```

Vorher `mkdir ~/agents/logs`. Claude Code findet die Agents automatisch in
`.claude/agents/` des Arbeitsverzeichnisses.

**Hinweis zu `--dangerously-skip-permissions`:** nötig für unbeaufsichtigte Läufe.
Die Leitplanken stecken dafür in den Agent-Dateien selbst (nichts versenden ohne Go,
nur definierte Ordner). Alternativ restriktiver: `--allowedTools "Read,Write,Bash,WebFetch"`.

## Schritt 4: Ergebnisse nach Discord (empfohlen: Webhooks)

Pro Kanal einen Webhook anlegen (siehe DISCORD-SETUP.md), URLs in `.env`.
Am Ende jedes Cron-Prompts ergänzen: "Poste die Zusammenfassung per curl an den
Webhook $DISCORD_WEBHOOK_REPORTS (Entwürfe als Datei-Anhang, Freigabe-Fragen als Text)."
Beispiel-curl, den die Agents nutzen können:

```bash
curl -H "Content-Type: application/json" \
  -d '{"content":"**Wochenreport KW27 fertig** – 3 Entwürfe warten auf Freigabe."}' \
  "$DISCORD_WEBHOOK_REPORTS"
```

Wichtig: Webhooks posten nur Status/Zusammenfassungen in DEINEN Discord –
das verletzt nicht die "nichts nach außen"-Regel. Kunden-E-Mails bleiben
Entwürfe, bis du in Discord Go gibst.

## Schritt 5: Testlauf von Hand

```bash
cd ~/agents && claude -p "Nutze den Subagent wochenreport ..." 
tail -f logs/wochenreport.log
```

## Kostenrahmen

wochenreport + belege laufen auf Haiku (Centbeträge pro Lauf),
content-recherche bewusst auf Sonnet (~10–30 Cent pro Lauf, siehe README warum).
