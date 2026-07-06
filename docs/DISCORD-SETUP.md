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

## Optional später: echter Bot statt Webhooks

Wenn du willst, dass Agents Discord auch LESEN (z. B. dein "Go" automatisch
erkennen oder den Wochen-Fokus aus #content ziehen): Discord Developer Portal →
New Application → Bot → Token in `.env` (DISCORD_BOT_TOKEN), Bot mit
Scope `bot` + Rechten "Read Messages/Send Messages" einladen. Dann sag mir
Bescheid – ich baue dir das Lese-Skript dazu. Für den Start reichen Webhooks.
