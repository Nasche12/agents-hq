#!/usr/bin/env python3
"""Discord über die REST-API – ohne discord.js, nur stdlib.

Nutzt DISCORD_BOT_TOKEN + DISCORD_GUILD_ID aus der Umgebung (run-agent.sh sourced .env).

  discord.py setup                      Server-Struktur anlegen (idempotent)
  discord.py post  <kanal> <text>       Nachricht posten (Kanal per Name oder ID)
  discord.py post  <kanal> <text> --attach datei.pdf
  discord.py read  <kanal> [--limit 20] letzte Nachrichten ausgeben (fürs "Go")

Bot-Rechte: setup braucht "Kanäle verwalten", read braucht "Message Content Intent"
(Dev-Portal → Bot → Privileged Gateway Intents) plus "Nachrichtenverlauf lesen".
"""
import sys, os, json, time, urllib.request, urllib.error, mimetypes, uuid

API = "https://discord.com/api/v10"
UA = "agents-hq (naschberger.info, 1.0)"

# Server-Struktur: (Kategorie, [Kanäle]) – aus docs/DISCORD-SETUP.md
STRUCTURE = [
    ("📌 STEUERUNG", ["freigaben", "agent-logs"]),
    ("📊 KUNDEN",    ["reports", "kunden-notizen"]),
    ("💶 FINANZEN",  ["belege", "verkauf"]),
    ("🎬 CONTENT",   ["content", "ideen"]),
]


def die(msg):
    sys.stderr.write("discord.py: " + msg + "\n")
    sys.exit(1)


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        die(f"{name} fehlt (in .env setzen)")
    return v


def api(method, path, token, body=None, headers=None, raw=None):
    """REST-Call mit Bot-Auth. body=dict -> JSON, raw=(content_type, bytes) -> roh."""
    url = API + path
    hdr = {"Authorization": "Bot " + token, "User-Agent": UA}
    data = None
    if raw is not None:
        hdr["Content-Type"], data = raw
    elif body is not None:
        hdr["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code == 429:  # Rate-Limit: einmal warten, dann nochmal
            try:
                time.sleep(float(json.loads(detail).get("retry_after", 1)) + 0.3)
            except Exception:
                time.sleep(2)
            return api(method, path, token, body=body, headers=headers, raw=raw)
        die(f"HTTP {e.code} bei {method} {path}: {detail[:300]}")


def guild_channels(token, gid):
    return api("GET", f"/guilds/{gid}/channels", token)


def resolve_channel(token, gid, name_or_id):
    """Kanal per ID (nur Ziffern) oder per Name finden -> ID."""
    if name_or_id.isdigit():
        return name_or_id
    want = name_or_id.lstrip("#").lower()
    for c in guild_channels(token, gid):
        if c.get("type") == 0 and c.get("name", "").lower() == want:
            return c["id"]
    die(f"Kanal '#{want}' nicht gefunden – 'setup' schon gelaufen? Rechte?")


def cmd_setup(token, gid):
    existing = guild_channels(token, gid)
    cats = {c["name"]: c["id"] for c in existing if c.get("type") == 4}
    chans = {c["name"].lower() for c in existing if c.get("type") == 0}
    made = 0
    for cat_name, channels in STRUCTURE:
        cid = cats.get(cat_name)
        if not cid:
            cid = api("POST", f"/guilds/{gid}/channels", token,
                      {"name": cat_name, "type": 4})["id"]
            print(f"+ Kategorie {cat_name}"); made += 1
        for ch in channels:
            if ch.lower() in chans:
                print(f"= #{ch} existiert"); continue
            api("POST", f"/guilds/{gid}/channels", token,
                {"name": ch, "type": 0, "parent_id": cid})
            print(f"+ #{ch}"); made += 1
    print(f"Fertig. {made} neu angelegt." if made else "Fertig. Alles war schon da.")


def _multipart(fields, filename, filedata):
    """Minimales multipart/form-data für Datei-Uploads."""
    boundary = "----agentshq" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; '
        f'filename="{os.path.basename(filename)}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
        + filedata + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return "multipart/form-data; boundary=" + boundary, b"".join(parts)


def cmd_post(token, gid, name_or_id, text, attach):
    cid = resolve_channel(token, gid, name_or_id)
    if attach:
        if not os.path.isfile(attach):
            die(f"Datei nicht gefunden: {attach}")
        with open(attach, "rb") as f:
            payload = {"payload_json": json.dumps({"content": text[:2000]})}
            ct, data = _multipart(payload, attach, f.read())
        api("POST", f"/channels/{cid}/messages", token, raw=(ct, data))
    else:
        api("POST", f"/channels/{cid}/messages", token, {"content": text[:2000]})
    print(f"gepostet in {name_or_id}")


def cmd_read(token, gid, name_or_id, limit):
    cid = resolve_channel(token, gid, name_or_id)
    msgs = api("GET", f"/channels/{cid}/messages?limit={limit}", token)
    for m in reversed(msgs):  # älteste zuerst
        author = m.get("author", {}).get("username", "?")
        content = m.get("content", "") or "(kein Textinhalt – Message Content Intent aktiv?)"
        print(f"[{m.get('timestamp','')[:19]}] {author}: {content}")


def main():
    a = sys.argv[1:]
    if not a:
        die("Befehl fehlt (setup|post|read)")
    token, gid = env("DISCORD_BOT_TOKEN"), env("DISCORD_GUILD_ID")
    cmd = a[0]
    if cmd == "setup":
        cmd_setup(token, gid)
    elif cmd == "post":
        if len(a) < 3:
            die("post <kanal> <text> [--attach datei]")
        attach = None
        if "--attach" in a:
            i = a.index("--attach"); attach = a[i + 1]; a = a[:i] + a[i + 2:]
        cmd_post(token, gid, a[1], a[2], attach)
    elif cmd == "read":
        limit = 20
        if "--limit" in a:
            i = a.index("--limit"); limit = int(a[i + 1]); a = a[:i] + a[i + 2:]
        if len(a) < 2:
            die("read <kanal> [--limit N]")
        cmd_read(token, gid, a[1], limit)
    else:
        die(f"unbekannter Befehl: {cmd}")


if __name__ == "__main__":
    main()
