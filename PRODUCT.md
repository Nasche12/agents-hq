# PRODUCT.md — Agent HQ

register: product

## Product Purpose
Persönliches Status-Dashboard (agents.naschberger.info) für Sebastians automatisierte Agenten (Wochenreport, Belege & Buchhaltung, Content-Recherche, Uptime-Wächter, SEO-Audit, Rechnungssteller). Zeigt Live-Status aus `status.json`, die von Cron-Läufen am Server geschrieben wird.

## Users
Genau ein Nutzer: Sebastian. Schaut abends oder zwischendurch kurz rein, meist Desktop, gelegentlich Handy. Will auf einen Blick sehen: Läuft was? Wartet was auf mein Go? Gab es Fehler?

## Brand / Tone
Abgespacete virtuelle Welt: Weltraum, Wireframe-/Linien-Ästhetik (Holo-HUD), verspielt. Die Roboter sind Charaktere: sie arbeiten sichtbar an Stationen, wenn ein Task läuft, und machen Freizeit-Aktivitäten (Kaffee, Arcade, Bank, Sterne gucken), wenn nicht. Die Szene darf spektakulär animiert sein — das Detail-Panel bleibt nüchtern und lesbar.

## Anti-References
- Generisches Admin-Dashboard mit Karten-Grid
- Statische Clipart-Roboter ohne Bewegung
- Comic-Haus mit Räumen (alte Version, explizit abgelehnt)

## Constraints
- Eine einzige statische HTML-Datei (`dashboard/index.html`), kein Build, keine externen Assets/CDNs (Passwortgeschützter Plesk-Docroot).
- Datenvertrag: `status.json` mit `agents.{id}.{name,status,phase,progress,message,last_run,next_run,details,outputs,log_tail}`; Status: running|ok|idle|waiting|error.
- Agent-IDs: wochenreport, belege-buchhaltung, content-recherche, uptime-waechter, seo-audit, rechnungssteller.
- Master: Sonder-ID `master` (Bot an der Kommando-Station, Spot `command`). Sein Status wird im Dashboard LIVE aus den 6 Fach-Agents berechnet (`computeMaster`) – kein status.json-Eintrag nötig; ein echter `master`-Eintrag (Kommandant läuft) überschreibt den Rollup. Auswählen zeigt das Flotten-Overview (`renderMaster`). Der Run-Button startet den Subagent `kommandant`.
- Neuer Agent = neue Station: BOT_IDS/NAME_OF/ROOT_OF/SPRITES/WORK/WAIT + SPOTS in `dashboard/index.html`, AGENTS/REPORT_ROOTS in `server.js`, Eintrag in `status.json`. Arbeits-Spots müssen begehbar & vom Korridor (20,11) per BFS erreichbar sein.
