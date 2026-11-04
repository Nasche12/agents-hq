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
