# Deployment: Agents automatisch auf deinem Server (Plesk)

Ziel: Die 3 Agents laufen ohne dein Zutun auf deinem Server und legen Ergebnisse
ab / posten sie in Discord. Basis ist Claude Code (headless) auf dem Server.

## Voraussetzungen

- SSH-Zugang zum Server (bei Plesk meist vorhanden)
- Node.js ≥ 18 auf dem Server (in Plesk unter "Node.js" aktivierbar oder via nvm)
- Ein Anthropic-API-Key (console.anthropic.com) ODER Claude-Abo-Login

> **NICHT als root laufen lassen.** Claude Code verweigert `--dangerously-skip-permissions`
> als root. Alles läuft unter dem Plesk-Subscription-User (Ordner-Eigentümer). User finden:
> `stat -c '%U' .` — dann Projekt übergeben (`chown -R <user>:psacln .`) und als dieser User
> arbeiten. Plesks "Geplante Aufgaben" laufen ohnehin als dieser User, nicht als root.

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
mkdir -p /var/www/vhosts/naschberger.info/agents.naschberger.info && cd /var/www/vhosts/naschberger.info/agents.naschberger.info
# Kompletten Ordner hochladen (scp/SFTP/Plesk-Dateimanager) ODER: git clone/pull.
# Nötig: .claude/agents/  bin/  dashboard/  config/  templates/  belege/  docs/  deploy.sh  .env.example
cp .env.example .env && nano .env   # Umami-Zugang + Discord-Webhooks eintragen
chmod 600 .env
nano config/sites.json              # echte Kunden-URLs für uptime-waechter + seo-audit eintragen
```

## Schritt 3: Cronjobs (Plesk: "Geplante Aufgaben" oder crontab -e)

Am saubersten über den Wrapper `bin/run-agent.sh <id> "<prompt>"` – der pflegt
Logs UND `status.json` fürs Dashboard (sonst zeigt das Dashboard den Lauf nicht an).

**Wichtig:** Cron startet mit minimalem PATH und findet `claude`/`node` sonst nicht.
Deshalb ganz oben in die Crontab (Ergebnis von `dirname $(command -v claude)` bzw.
`dirname $(command -v node)` einsetzen, oft `/usr/bin` oder ein nvm-Pfad):

```cron
PATH=/usr/local/bin:/usr/bin:/bin
```

```cron
# Freitag 08:00 – Wochenreport (ein HTML-Gesamtreport aller Kundenseiten)
0 8 * * 5  cd /var/www/vhosts/naschberger.info/agents.naschberger.info && bin/run-agent.sh wochenreport "Nutze den Subagent wochenreport und erstelle den Wochenreport für die abgelaufene Woche." >> logs/wochenreport.cron.log 2>&1

# Montag 09:00 – Belege verarbeiten
0 9 * * 1  cd /var/www/vhosts/naschberger.info/agents.naschberger.info && bin/run-agent.sh belege-buchhaltung "Nutze den Subagent belege-buchhaltung und verarbeite alle neuen Belege in belege/inbox/." >> logs/belege.cron.log 2>&1

# Sonntag 17:00 – Contentplan für die Folgewoche
0 17 * * 0 cd /var/www/vhosts/naschberger.info/agents.naschberger.info && bin/run-agent.sh content-recherche "Nutze den Subagent content-recherche und erstelle den Contentplan für die kommende Woche." >> logs/content.cron.log 2>&1

# Alle 15 Minuten – Uptime-Wächter (pingt config/sites.json)
*/15 * * * * cd /var/www/vhosts/naschberger.info/agents.naschberger.info && bin/run-agent.sh uptime-waechter "Nutze den Subagent uptime-waechter und prüfe jetzt alle Sites aus config/sites.json." >> logs/uptime.cron.log 2>&1

# Mittwoch 06:00 – SEO-Audit
0 6 * * 3  cd /var/www/vhosts/naschberger.info/agents.naschberger.info && bin/run-agent.sh seo-audit "Nutze den Subagent seo-audit und auditiere alle Sites aus config/sites.json." >> logs/seo.cron.log 2>&1

# Optional, alle 30 Min – Master/Kommandant: Lage aktualisieren + fällige Läufe abstimmen
# (nicht nötig, wenn die Einzel-Crons schon alles starten – dient v. a. master/lage.md)
*/30 * * * * cd /var/www/vhosts/naschberger.info/agents.naschberger.info && bin/run-agent.sh master "Nutze den Subagent kommandant: Überblick aus status.json, Zeitplan aus config/schedule.json abstimmen, fällige Läufe anstoßen, master/lage.md aktualisieren." >> logs/master.cron.log 2>&1

# rechnungssteller: KEIN Cron – läuft nur auf Abruf (Dashboard-START-Button oder von Hand).
```

Claude Code findet die Agents automatisch in `.claude/agents/` des Arbeitsverzeichnisses.
`--dangerously-skip-permissions` setzt der Wrapper bereits intern.

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
cd /var/www/vhosts/naschberger.info/agents.naschberger.info && claude -p "Nutze den Subagent wochenreport ..." 
tail -f logs/wochenreport.log
```

## Kostenrahmen

wochenreport + belege laufen auf Haiku (Centbeträge pro Lauf),
content-recherche bewusst auf Sonnet (~10–30 Cent pro Lauf, siehe README warum).
