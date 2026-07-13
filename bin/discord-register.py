#!/usr/bin/env python3
"""Registriert die HQ-Slash-Commands als Guild-Commands (sofort aktiv, keine 1h-Wartezeit).

Einmalig bzw. nach Aenderung der Kommandoliste ausfuehren:
    python3 bin/discord-register.py

Braucht in der Umgebung (run-agent.sh sourcet .env, hier ggf. selbst sourcen):
    DISCORD_BOT_TOKEN   Bot-Token
    DISCORD_GUILD_ID    Server-ID
    DISCORD_APP_ID      Application-ID (Dev-Portal -> General Information)
"""
import os, sys, json, urllib.request, urllib.error

API = "https://discord.com/api/v10"


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"discord-register: {name} fehlt (in .env setzen)")
    return v


# Aliase, die server.js/matchAgent aufloest -> als Auswahl im Slash-Menue
AGENT_CHOICES = [
    {"name": "report",   "value": "report"},
    {"name": "belege",   "value": "belege"},
    {"name": "content",  "value": "content"},
    {"name": "uptime",   "value": "uptime"},
    {"name": "seo",      "value": "seo"},
    {"name": "rechnung", "value": "rechnung"},
    {"name": "server",     "value": "server"},
    {"name": "mail",       "value": "mail"},
    {"name": "video",      "value": "video"},
    {"name": "influencer", "value": "influencer"},
]


def agent_opt(required, desc="Welcher Agent"):
    return {"type": 3, "name": "agent", "description": desc,
            "required": required, "choices": AGENT_CHOICES}


COMMANDS = [
    {"name": "status", "description": "Ampel-Uebersicht aller Agents"},
    {"name": "offen",  "description": "Nur Waits und Fehler"},
    {"name": "agents", "description": "Bekannte Agents auflisten"},
    {"name": "help",   "description": "HQ-Kommandos anzeigen"},
    {"name": "run",    "description": "Agent-Lauf jetzt starten",
     "options": [agent_opt(True)]},
    {"name": "ja",     "description": "Faelligen Lauf freigeben und starten",
     "options": [agent_opt(True)]},
    {"name": "nein",   "description": "Faelligen Lauf diesmal ueberspringen",
     "options": [agent_opt(True)]},
    {"name": "go",     "description": "Freigabe erteilen (Versand/Aktion des wartenden Laufs)",
     "options": [agent_opt(False)]},
    {"name": "master", "description": "Frage an den Master stellen (kostet Tokens)",
     "options": [{"type": 3, "name": "frage", "description": "Deine Frage", "required": True}]},
]


def main():
    tok, gid, app = env("DISCORD_BOT_TOKEN"), env("DISCORD_GUILD_ID"), env("DISCORD_APP_ID")
    url = f"{API}/applications/{app}/guilds/{gid}/commands"
    req = urllib.request.Request(
        url, data=json.dumps(COMMANDS).encode(), method="PUT",
        headers={"Authorization": "Bot " + tok,
                 "Content-Type": "application/json",
                 "User-Agent": "agents-hq (naschberger.info, 1.0)"})
    try:
        with urllib.request.urlopen(req) as r:
            out = json.loads(r.read().decode())
        print(f"OK - {len(out)} Slash-Commands fuer Guild {gid} registriert:")
        for c in out:
            print("  /" + c.get("name", "?"))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} bei PUT commands: {e.read().decode(errors='replace')[:400]}")


if __name__ == "__main__":
    main()
