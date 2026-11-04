# Handoff – Agent HQ

## Session 2026-11-04 (2): Rechte-Haertung vor Deploy (PR #4, gestapelt auf #3)

- **Entscheidung (Sebastian):** Haertung VOR dem Deploy.
- **Perms:** Syntax laut Doku: `//pfad` absolut, `~/` Home, `/pfad` relativ zur Settings-Datei. Alle `Edit/Write(/etc|/root|/usr|/bin|/boot/**)` in allen `.claude/perms/*.json` auf `//` umgestellt. `/var` entfernt (BASE kann unter /var/www liegen, `//var` wuerde alles blockieren).
- **default.json:** Write/Edit nur noch in Output-Ordnern (reports, belege, rechnungen, master, mail, content/videos, content/influencer, trading, config/rechnung.json, config/schedule.json, news_risk.json, candidates.json); Secret-Reads gesperrt; kritische Pfade gedenied.
- **seo-audit.json (LLM-Modus):** auf Niveau seo-tiefenaudit (kein curl/sed/awk/cat, nur date, Write seo/**/*.md).
- **trading-forscher** in AGENT_CHOICES (`forscher`), CHOICE, ALIAS und run-agent.sh; KNOWN_GAPS leer.
- **Test:** `dashboard/perms-paths.test.js`. Nach Deploy einmal `bin/discord-register.py` ausfuehren (neuer Slash-Wert).
- **Offen:** Review-Verdict; Write-Regeln gelten nicht fuer Shell-Umleitungen (Bash bleibt offen in default.json).

## Session 2026-11-04: SEO-Audit ehrlich machen + monatlicher Tiefen-Audit

- **Anlass:** Der Discord-Bot meldete den SEO-Audit KW45. Sebastian: Der Audit soll mehrere SEO-Skills nutzen und ehrlich sein, „SEO ist auf allen Webseiten schlecht“.
- **Entscheidungen (Sebastian):** Alle drei Bausteine umsetzen: (1) einmaligen Tiefen-Audit, (2) den token-freien Bot ausbauen, (3) einen monatlichen Claude-Audit.
- **Gestapelte PRs, alle ready.** Merge-Reihenfolge #1 → #2 → #3:
  - **#1 `fix/seo-audit-fehlalarme`:**
    - PDFs werden nicht mehr als Seiten geprüft.
    - Die URL-Normalisierung behandelt `/` am Ende einheitlich.
    - Weitere Fixes: `href=""`, 4xx-Seiten werden nicht auditiert, Link-Timeouts zählen als „nicht gemessen“, der Same-Site-Abgleich läuft über die Origin.
  - **#2 `feat/seo-audit-tief`:**
    - Bindet `bin/lib/geo_audit.py` ein (gehärtete Kopie aus dem Skill seo-geo-tools) mit Baseline und Drift.
    - Neu: PageSpeed (`PAGESPEED_API_KEY`), GSC optional (`GSC_CREDENTIALS`), Checks für OG, Schema und dünnen Inhalt.
    - Die Ampel ist ehrlich. Neue Abschnitte „Nicht gemessen“ und „Grenzen“.
    - Zeitbudget 1500 s.
    - Doku: `docs/SEO-AUDIT.md`.
  - **#3 `feat/seo-tiefenaudit-monatlich`:**
    - LLM-Agent `seo-tiefenaudit` (Sonnet) mit Cadence `monatlich 1. Mi 07:00`. Er ist `schwer`, startet also erst nach `/ja tiefenaudit` in #freigaben.
    - Strenges Rechteprofil `.claude/perms/seo-tiefenaudit.json`. Projekt-Skill `.claude/skills/seo-aeo-geo/`.
    - Ausgabe nach `seo/monat-JJJJ-MM/`.
    - Geändert für alle Agents: `discord.py --attach` nur noch aus Report-Roots. `/api/file` liefert alles außer PDF mit CSP sandbox und nosniff aus.
- **Review:** Opus-Subagent statt Codex (bis 2026-11-18).
  - #1: HIGH → LOW.
  - #2: HIGH → MEDIUM → LOW. HIGH war eine curl-Option-Injection über `Sitemap:`, gefixt.
  - #3: HIGH → MEDIUM → MEDIUM → keine.
  - Die Verdicts stehen in den PR-Bodies. Das Repo hat kein CI. Tests: `node --test dashboard/*.test.js bin/agents/seo-audit.test.js`.
- **Deploy (Sebastian):**
  1. Auf dem Server `git pull`.
  2. Einmal `bin/discord-register.py` ausführen.
  3. `PAGESPEED_API_KEY` in `.env` setzen. Ohne Key bleibt CWV „nicht gemessen“ und die Ampel nie grün.
  4. Heute (2026-11-04) ist erster Mittwoch: Ein Neustart vor 09:00 Wien fragt sofort in #freigaben.
- **Tiefen-Audits:** `D:\Projects\_seo-audits\2026-11-04\` (naschberger-info, sicherrestaurant-at, ursulakircher-at). Alle drei sind außerhalb von Markensuchen praktisch unsichtbar. ursulakircher.at ist eine reine SPA ohne Prerender.
- **Out of Scope, offen:**
  - `.claude/perms/default.json`: Die Denies für `/etc` und `/root` sind relativ und greifen nicht, Write ist pauschal erlaubt. `seo-audit.json` hat für den LLM-Modus weite Bash-Rechte (curl, sed, awk). Ein Härtungs-PR wurde vorgeschlagen, Sebastians Antwort steht aus.
  - `trading-forscher` (enabled und schwer) fehlt in CHOICE/AGENT_CHOICES, deshalb ist `/ja` nicht wählbar. Im Konsistenz-Test steht er als `KNOWN_GAPS`.
  - Folge-Issue aus #2: Randfälle der Sitemap-Host-Heuristik in `geo_audit.py` (www-Variante, IDN, teilweise verworfene Sitemaps).
  - `ki-influencer`: Anhänge müssen nach `content/influencer/`, sonst bricht `--attach`.
- **Lokale Worktrees:** `D:\Projects\privat\agents-hq` (feat/seo-audit-tief) und `D:\Projects\privat\agents-hq-tiefenaudit` (feat/seo-tiefenaudit-monatlich).
