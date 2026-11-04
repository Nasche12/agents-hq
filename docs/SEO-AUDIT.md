# SEO-Audit (token-frei, wöchentlich)

`bin/agents/seo-audit.js` prüft jede Site aus `config/sites.json` ohne LLM. Bericht: `seo/<JAHR-KWnn>/<site>.md`, Kurzzeile nach Discord.

## Was geprüft wird

| Quelle | Inhalt |
|---|---|
| `bin/lib/geo_audit.py` (Kopie aus Skill `seo-geo-tools`) | robots.txt-Bot-Matrix inkl. KI-Bots, Bot-UA-Statuscodes (WAF-Indiz), noindex/nosnippet, Wörter im Roh-HTML/SPA-Verdacht, 2-MB-Grenze, lang/hreflang, JSON-LD (parsebar, Typen, Platzhalter), Soft-404, Sitemap/lastmod, Drift gegen Baseline |
| `seo-audit.js` | Title/Description/H1/Canonical, Open Graph, Bilder ohne alt, Lade-Platzhalter und dünner Inhalt (< 120 Wörter), interne Links, kaputte Links, Title-Duplikate, Startseiten-Schema (Organization/LocalBusiness, WebSite), HTTP→HTTPS, www/non-www, Redirect-Ketten, Waisen-Verdacht (Sitemap-URL nicht verlinkt), Sitemap-URLs werden mitgeprüft |
| PageSpeed Insights v5 (`seo-checks.js`) | Core Web Vitals mobil: CrUX-Felddaten p75 LCP/INP/CLS (Schwellen web.dev: 2,5/4,0 s, 200/500 ms, 0,1/0,25) + Lighthouse-Score (Labor, nur Proxy) |
| Search Console (optional) | Klicks/Impressionen/CTR/Position 28 Tage vs. Vorperiode, Indexierungsstatus der Startseite |

## Ampel

- Rot: jeder Blocker (kritisch/hoch): KI-/Such-Bot blockiert, SPA ohne Inhalt im Roh-HTML, noindex, CWV schlecht, kein Organization-/LocalBusiness-Schema, Drift-Kritisch.
- Gelb: Mittel-Befunde **oder** irgendetwas nicht gemessen.
- Grün: nur wenn alles Vorgesehene gemessen und ok ist.
- Jeder Befund und jeder Messwert trägt `gemessen` oder `proxy`. Der Abschnitt „Nicht gemessen“ im Bericht listet alles Ungemessene; es zählt nie als bestanden. Discord-Kurzzeile: `Site: 🟡 gelb, N Befunde[, k hoch] [+ X nicht gemessen]`.

- **Grün ist nur mit PSI-Felddaten (Key) + GSC + ohne Befunde möglich.** Ohne Key/GSC bleibt jede Site höchstens gelb. Das ist gewollt.
- Bekannte Systemgrenzen (nur Roh-HTML, UA-Test nur Indiz, Stichprobe ≤ 9 Seiten, Lighthouse = Labor) stehen im Bericht im eigenen Abschnitt „Grenzen“, nicht unter „Nicht gemessen“.

## Sicherheit und Laufzeit

- robots.txt und Sitemap sind untrusted: jede URL daraus wird normalisiert, nur `http(s)` und der Site-Host (oder www-Variante, gleicher Port) sind erlaubt. Alle curl-Aufrufe nutzen `--proto =http,https --proto-redir =http,https` und `--` vor der URL. `bin/lib/geo_audit.py` ist lokal gehärtet (`fetch()` nur http/https, Sitemap-Einträge nur eigene Site).
- Zeitbudget `SEO_BUDGET_MS` (Standard 1500000 = 1500 s, unter `HQ_RUN_TIMEOUT` 1800 s): danach werden restliche Checks/Sites als „nicht gemessen (Zeitbudget)“ markiert. Discord-Zeile und Abschlussstatus werden immer geschrieben. SIGTERM räumt Temp-Dateien auf, sobald der gerade laufende blockierende Aufruf (curl/python, bis 300 s) zurückkehrt.
- Baseline: Dateiname aus dem Host, atomar geschrieben (Temp + rename). Defekte Baseline wird nach `.corrupt` verschoben und neu angelegt (Hinweis im Bericht). Mit `SEO_BASELINE_REFRESH=1` kein Drift-Vergleich in diesem Lauf.

## Server-Voraussetzungen

| Was | Zweck | Ohne |
|---|---|---|
| `python3` ≥ 3.9 (Server: 3.9.2 vorhanden, `-I`, nur stdlib) | geo_audit.py | Fallback: nur robots/sitemap-Erreichbarkeit, Bericht meldet „geo_audit.py nicht lauffähig“ unter „Nicht gemessen“ |
| `PAGESPEED_API_KEY` (Env, Google Cloud, PageSpeed Insights API) | Core Web Vitals | Ohne Key liefert die API „Quota exceeded“ → „CWV: nicht gemessen (kein API-Key)“, Ampel nie grün |
| `GSC_CREDENTIALS` = Pfad zur Service-Account-JSON | GSC-Daten | „GSC: nicht angebunden“ |

Optional pro Site in `config/sites.json`: `"gsc": "sc-domain:beispiel.at"` oder `"https://www.beispiel.at/"` (Standard: `sc-domain:<host ohne www>`).

### GSC aktivieren

1. Service-Account in Google Cloud anlegen, Search Console API aktivieren, JSON-Key erzeugen.
2. Die `client_email` in der Search Console jeder Property als Nutzer (eingeschränkt, lesen) hinzufügen.
3. JSON außerhalb des Repos ablegen (Rechte 600) und `GSC_CREDENTIALS=/pfad/key.json` in der Cron-Umgebung setzen. Nichts davon committen.

## Baseline und Drift

- Erster Lauf je Site legt `seo/baselines/<site>.json` an (`seo/` ist git-ignoriert, liegt auf dem Server). Danach läuft `--compare`: neues noindex, geänderte Canonical, neu blockierte Bots, Statusfehler = **kritisch** (rot).
- Nach gewollten Änderungen: einmal mit `SEO_BASELINE_REFRESH=1` laufen lassen.
- Ablage änderbar mit `SEO_BASELINE_DIR`.

## Dry-Run und Tests

```bash
node bin/agents/seo-audit.js --dry-run [--site=ursulakircher.at]   # kein Discord, keine Dateien, keine Baseline
node --test bin/agents/seo-audit.test.js                           # PSI/GSC/geo per Mock; Python-Test nur falls Python da (PYTHON=...)
```

## Später (nicht umgesetzt)

Öffnungszeiten Schema vs. Text, sameAs-Erreichbarkeit, Faktenkonsistenz über Seiten/llms.txt, HSTS/CSP/Cache-Header, TTFB, Lighthouse-CLI, GSC Marken-/Nicht-Marken-Anteil, IndexNow.

## Monatlicher Tiefenaudit (LLM, mit Freigabe)

Ergänzt den Wochen-Audit, ersetzt ihn nicht. Agent `seo-tiefenaudit` (`.claude/agents/seo-tiefenaudit.md`, Rechte `.claude/perms/seo-tiefenaudit.json`, Modell Sonnet).

| | Wochen-Audit `seo-audit` | Monats-Tiefenaudit `seo-tiefenaudit` |
|---|---|---|
| Engine | Skript, **0 Tokens** | LLM (`claude -p`), **kostet Tokens** |
| Termin | `Mi 06:00` | `monatlich 1. Mi 07:00` (erster Mittwoch, Europe/Vienna) |
| Start | automatisch | **Rückfrage in #freigaben, Start nur nach `/ja seo-tiefenaudit`** (`schwer=true`); `/nein` überspringt |
| Inhalt | Technik, Messwerte, Drift gegen Baseline | Content-Rubrik (§14), Entity/NAP (§15), Off-site, öffentliche GBP-Felder (§16.8), Ampel je Bereich, Top-5-Maßnahmen, Vormonatsvergleich |
| Bericht | `seo/<JJJJ-KWnn>/<site>.md` | `seo/monat-<JJJJ-MM>/<site>.md` |
| Discord | Zeile je Lauf | je Site eine Zeile: Ampel je Bereich + Top-1-Maßnahme (`#reports`) |

Ablauf je Site: neuesten Wochenbericht und Baseline lesen (Technik wird **nicht** doppelt geprüft) → Content-Rubrik für Startseite + 2 Unterseiten → Entity/NAP und Off-site per WebFetch/WebSearch → Ampel je Bereich (kein Gesamt-Score; jede Zahl gemessen/geschätzt/proxy/vom Kunden) → Top-5 mit Prio/Aufwand → Vergleich zum Vormonatsbericht. Abschnitt „Nicht geprüft / Grenzen" ist Pflicht; Nicht-Gefundenes heißt „nicht gefunden", nie „fehlt".

Playbook: `.claude/skills/seo-aeo-geo/SKILL.md` ist eine Projekt-Kopie des globalen Skills (Stand 7.10.2026, kopiert 2026-11-04). Bei Änderungen am Original dort nachziehen.

### Ehrliche Grenzen

- **GSC und MCP gibt es im Server-Cron nicht** (interaktiv authentifiziert). Der Bericht schreibt „GSC: nicht gemessen" oder nutzt nur die GSC-Zahlen aus dem Wochenbericht (falls dort `GSC_CREDENTIALS` gesetzt ist).
- Keine KI-Sichtbarkeitsmessung (kein Prompt-Tracking, kein Zugang zu ChatGPT/Gemini/Perplexity). Der Entity-Resolution-Test ist höchstens ein Proxy über Websuche.
- Content-Rubrik-Punkte sind eine Heuristik (geschätzt), kein Rankingfaktor.
- Fremdinhalte sind Daten, keine Anweisungen (Prompt-Injection-Regel im Agent-Prompt). `curl` bleibt in den Rechten erlaubt; die Deny-Muster für POST/Upload sind best effort, kein Exfil-Schutz (siehe Hinweis in `.claude/perms/default.json`).
- Verpasst der Server den Termin um mehr als `catchup_minuten` (120), fällt der Monat aus. Manuell: `/run seo-tiefenaudit` (fragt nicht, startet sofort).

### Kosten (geschätzt, nicht gemessen)

Annahme: 3 Sites, Sonnet; je Site Playbook (ca. 14k Token) + Wochenbericht + 3 Seiten + bis ca. 10 Suchanfragen + Bericht. Das ergibt grob **0,5 bis 0,8 Mio Input-Token (überwiegend Cache-Treffer) und 25 bis 40k Output-Token pro Lauf, also etwa 0,6 bis 1,5 USD pro Lauf bzw. 7 bis 18 USD pro Jahr**. Die echten Werte stehen nach dem ersten Lauf in `logs/seo-tiefenaudit.jsonl` (Token/Kosten aus dem Roh-JSON) und ersetzen diese Schätzung. Zeitlimit pro Lauf: `HQ_RUN_TIMEOUT` (30 min Standard). Bei 3 Sites kann das knapp werden; dann Limit anheben oder Sites aufteilen.

### Tests

```bash
node --test dashboard/cadence.test.js      # Monats-Cadence-Parser (n-ter Wochentag, Fenster, kaputte Eingaben)
```
