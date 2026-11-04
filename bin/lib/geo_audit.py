# Herkunft: Kopie von ~/.claude/skills/seo-geo-tools/scripts/geo_audit.py (Skill seo-geo-tools, Stand 2026-10-07, v1.1).
# Lokale Haertung (agents-hq, Opus-Review H1): fetch() nur http/https; Sitemap-/Seiten-URLs nur Site-Host oder www-Variante (same_site). Sonst unveraendert. Aufruf aus bin/agents/seo-audit.js (python3 -I, stdlib, >= 3.9).
#!/usr/bin/env python3
"""
geo_audit.py - dependency-free SEO/AEO/GEO quick audit (Python stdlib only, 3.9+).

Checks what search engines and AI crawlers see in the RAW HTML (no JavaScript):
  * robots.txt per RFC 9309 (group logic per bot token; 4xx = allow all, 5xx = disallow all)
  * status codes per bot user agent (optional, --ua-test; indication only, not real bot traffic)
  * indexability: status, redirects, noindex/nosnippet (meta + X-Robots-Tag), canonical
  * content in raw HTML: word count, SPA-shell suspicion, HTML size (Googlebot: 2 MB)
  * title, description, H1, lang, hreflang, JSON-LD (parseable, types, placeholders)
  * soft 404, sitemap (lastmod quality), llms.txt (info only)
  * deploy gate: --save-baseline / --compare (critical changes -> exit code 2)

Usage:
  python3 geo_audit.py https://www.example.com
  python3 geo_audit.py https://www.example.com --pages 15 --ua-test --json audit.json
  python3 geo_audit.py https://www.example.com --save-baseline baseline.json
  python3 geo_audit.py https://www.example.com --compare baseline.json   # in CI after deploy

Exit codes: 0 = ok, 1 = invocation error, 2 = critical findings (for CI).
All findings are "measured" (raw HTTP). Check rendered HTML (Googlebot) separately:
GSC URL Inspection / Rich Results Test.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import re
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

VERSION = "1.1 (2026-10-07)"
DEFAULT_UA = "Mozilla/5.0 (compatible; geo-audit/1.1; +https://example.invalid/geo-audit)"
MAX_BYTES = 6 * 1024 * 1024
GOOGLEBOT_LIMIT = 2 * 1024 * 1024

# Bot tokens by purpose (as of 10/2026). "search"/"user" = citation-relevant.
BOTS = {
    "search": ["Googlebot", "bingbot", "OAI-SearchBot", "Claude-SearchBot", "PerplexityBot",
               "Meta-WebIndexer", "MistralAI-Index", "Applebot"],
    "user": ["ChatGPT-User", "Claude-User", "Perplexity-User", "MistralAI-User", "Meta-ExternalFetcher"],
    "training": ["GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended", "Meta-ExternalAgent",
                 "MistralAI-Training", "CCBot"],
    "ads": ["OAI-AdsBot"],
}
STALE_TOKENS = {"anthropic-ai": "ClaudeBot / Claude-SearchBot / Claude-User",
                "claude-web": "Claude-User",
                "google-notebooklm": "Google-GeminiNotebook"}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


# ----------------------------------------------------------------------------- HTTP
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # follow redirects manually so we can count them
        return None


_ctx = ssl.create_default_context()
_opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=_ctx))


def same_site(url: str, origin: str) -> bool:
    """Only http(s) and the site host (or its www variant): sitemap entries are untrusted input."""
    a, b = urllib.parse.urlparse(url), urllib.parse.urlparse(origin)
    strip = lambda h: (h or "").lower().removeprefix("www.")
    return a.scheme in ("http", "https") and a.scheme == b.scheme and a.port == b.port and strip(a.hostname) == strip(b.hostname)


def fetch(url: str, ua: str = DEFAULT_UA, follow: bool = True, max_redirects: int = 5, timeout: int = 20):
    """Returns dict(status, url, headers, body, redirects, error, ms)."""
    chain = []
    cur = url
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):   # kein file://, ftp:// (urllib kennt sie)
        return {"status": None, "url": url, "headers": {}, "body": b"", "redirects": [], "error": "blocked scheme", "ms": 0}
    t0 = time.time()
    for _ in range(max_redirects + 1):
        req = urllib.request.Request(cur, headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                                   "Accept-Encoding": "gzip", "Accept-Language": "de-AT,de;q=0.9,en;q=0.5"})
        try:
            resp = _opener.open(req, timeout=timeout)
            status, headers = resp.status, resp.headers
            raw = resp.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            status, headers = e.code, e.headers
            try:
                raw = e.read(MAX_BYTES + 1)
            except Exception:
                raw = b""
        except Exception as e:  # DNS, TLS, timeout
            return {"status": None, "url": cur, "headers": {}, "body": b"", "redirects": chain,
                    "error": f"{type(e).__name__}: {e}", "ms": int((time.time() - t0) * 1000)}
        if status in (301, 302, 303, 307, 308) and follow and headers.get("Location"):
            chain.append((status, cur))
            cur = urllib.parse.urljoin(cur, headers["Location"])
            continue
        if headers.get("Content-Encoding", "").lower() == "gzip":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return {"status": status, "url": cur, "headers": headers, "body": raw, "redirects": chain,
                "error": None, "ms": int((time.time() - t0) * 1000)}
    return {"status": None, "url": cur, "headers": {}, "body": b"", "redirects": chain,
            "error": "Too many redirects", "ms": int((time.time() - t0) * 1000)}


def decode(body: bytes, headers) -> str:
    charset = "utf-8"
    ct = headers.get("Content-Type", "") if headers else ""
    m = re.search(r"charset=([\w-]+)", ct, re.I)
    if m:
        charset = m.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# ----------------------------------------------------------------------------- robots.txt (RFC 9309)
def parse_robots(text: str):
    groups, cur_agents, cur_rules, sitemaps = [], [], [], []
    last_was_agent = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            if not last_was_agent and (cur_agents or cur_rules):
                groups.append((cur_agents, cur_rules))
                cur_agents, cur_rules = [], []
            cur_agents.append(val.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            if cur_agents:
                cur_rules.append((key, val))
            last_was_agent = False
        elif key == "sitemap":
            sitemaps.append(val)
        else:
            last_was_agent = False
    if cur_agents:
        groups.append((cur_agents, cur_rules))
    return groups, sitemaps


def rules_for(groups, token: str):
    """RFC 9309: merge all groups matching the product token, otherwise fall back to '*'."""
    t = token.lower()
    matched = [r for agents, r in groups if t in agents]
    if not matched:
        matched = [r for agents, r in groups if "*" in agents]
        used = "*" if matched else None
    else:
        used = token
    rules = [rule for r in matched for rule in r]
    return rules, used


def _pattern_to_regex(p: str):
    anchored = p.endswith("$")
    if anchored:
        p = p[:-1]
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in p)
    return re.compile("^" + rx + ("$" if anchored else ""))


def is_allowed(rules, path: str) -> bool:
    if path == "/robots.txt":
        return True
    best_len, best_allow = -1, True
    for kind, pat in rules:
        if pat == "":
            continue  # empty Disallow = allowed
        if _pattern_to_regex(pat).match(path):
            ln = len(pat)
            if ln > best_len or (ln == best_len and kind == "allow"):
                best_len, best_allow = ln, (kind == "allow")
    return best_allow


# ----------------------------------------------------------------------------- HTML
class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self._in_title = "", False
        self.metas, self.links = [], []
        self.h1s, self._h1_depth, self._h1_buf = [], 0, []
        self.lang = None
        self.jsonld, self._in_jsonld, self._jsonld_buf = [], False, []
        self._skip = 0
        self.text_parts = []
        self.details = 0
        self.a_internal, self.a_total = 0, 0
        self.base_host = None
        self.root_ids = set()
        self.scripts_src = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif tag == "h1":
            self._h1_depth += 1
            self._h1_buf = []
        elif tag == "details":
            self.details += 1
        elif tag == "a" and a.get("href"):
            self.a_total += 1
            href = a["href"]
            if href.startswith("/") and not href.startswith("//"):
                self.a_internal += 1
            elif self.base_host and urllib.parse.urlparse(href).netloc == self.base_host:
                self.a_internal += 1
        elif tag == "div" and a.get("id") in ("root", "app", "__next", "__nuxt", "svelte"):
            self.root_ids.add(a["id"])
        if tag == "script":
            if a.get("src"):
                self.scripts_src += 1
            if a.get("type", "").lower() == "application/ld+json":
                self._in_jsonld, self._jsonld_buf = True, []
                return
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
            self.h1s.append(" ".join("".join(self._h1_buf).split()))
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append("".join(self._jsonld_buf))
            return
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._in_title:
            self.title += data
        if self._h1_depth:
            self._h1_buf.append(data)
        if not self._skip:
            self.text_parts.append(data)


def jsonld_types(obj, out: set):
    if isinstance(obj, dict):
        t = obj.get("@type")
        if isinstance(t, str):
            out.add(t)
        elif isinstance(t, list):
            out.update(x for x in t if isinstance(x, str))
        for v in obj.values():
            jsonld_types(v, out)
    elif isinstance(obj, list):
        for v in obj:
            jsonld_types(v, out)


PLACEHOLDER_RX = re.compile(r"(xxx|lorem ipsum|example\.(com|at|org)|TODO|\bQxxx\b|\+43-316-000000|BrandName)", re.I)


# ----------------------------------------------------------------------------- Findings
class Report:
    def __init__(self):
        self.findings = []

    def add(self, severity, area, issue, evidence, fix, url=None):
        self.findings.append({"severity": severity, "area": area, "issue": issue,
                              "evidence": evidence, "fix": fix, "url": url, "label": "measured"})

    def sorted(self):
        return sorted(self.findings, key=lambda f: (SEVERITY_ORDER[f["severity"]], f["area"]))

    def has_critical(self):
        return any(f["severity"] == "critical" for f in self.findings)


def analyze_page(url: str, rep: Report, robots_groups, origin_host: str, root_blocked=frozenset()):
    r = fetch(url)
    data = {"url": url, "final_url": r["url"], "status": r["status"], "ms": r["ms"],
            "redirects": len(r["redirects"]), "error": r["error"]}
    if r["error"]:
        rep.add("critical", "Reachability", "Page not reachable", r["error"], "Check server/DNS/TLS", url)
        return data
    if r["redirects"]:
        hops = " → ".join(f"{s}:{u}" for s, u in r["redirects"]) + f" → {r['url']}"
        sev = "medium" if len(r["redirects"]) > 1 else "info"
        rep.add(sev, "Redirects", f"{len(r['redirects'])} redirect(s)", hops,
                "Point internal links/sitemap directly at the final URL; avoid chains", url)
    if r["status"] != 200:
        rep.add("critical" if r["status"] and r["status"] >= 400 else "high", "Reachability",
                f"HTTP {r['status']}", f"GET {r['url']}", "Page must return 200 (or be intentionally removed)", url)
    body = r["body"]
    size = len(body)
    data["html_bytes"] = size
    if size > GOOGLEBOT_LIMIT:
        rep.add("high", "Technical", "HTML larger than 2 MB", f"{size:,} bytes",
                "Googlebot only processes the first 2 MB: move inline JSON/SVG/CSS out", url)
    ct = r["headers"].get("Content-Type", "")
    if "html" not in ct.lower():
        data["content_type"] = ct
        return data
    html = decode(body, r["headers"])
    p = PageParser()
    p.base_host = urllib.parse.urlparse(r["url"]).netloc
    try:
        p.feed(html)
    except Exception as e:
        rep.add("medium", "HTML", "HTML parser error", str(e), "Validate the HTML", url)

    # Robots / snippet controls
    xrt = (r["headers"].get("X-Robots-Tag") or "").lower()
    meta_robots = " ".join(m.get("content", "").lower() for m in p.metas
                           if m.get("name", "").lower() in ("robots", "googlebot"))
    data["x_robots"], data["meta_robots"] = xrt, meta_robots
    for src, val in (("X-Robots-Tag", xrt), ("meta robots", meta_robots)):
        if "noindex" in val or "none" in val.split(","):
            rep.add("critical", "Indexing", f"noindex via {src}", val,
                    "Remove noindex if the page should rank", url)
        if "nosnippet" in val:
            rep.add("high", "AI visibility", f"nosnippet via {src}", val,
                    "nosnippet also excludes AI Overviews/AI Mode - use only deliberately", url)
        m = re.search(r"max-snippet:\s*(-?\d+)", val)
        if m and int(m.group(1)) >= 0 and int(m.group(1)) < 50:
            rep.add("medium", "AI visibility", f"max-snippet:{m.group(1)} via {src}", val,
                    "Very small snippet limits restrict AI features", url)

    # Canonical
    canon = [l.get("href") for l in p.links if "canonical" in l.get("rel", "").lower().split()]
    data["canonical"] = canon[0] if canon else None
    if not canon:
        rep.add("medium", "Indexing", "No canonical in raw HTML", "<link rel=canonical> missing",
                "Output a self-referencing canonical server-side", url)
    elif len(set(canon)) > 1:
        rep.add("high", "Indexing", "Multiple different canonicals", ", ".join(canon),
                "Exactly one canonical", url)
    else:
        c_abs = urllib.parse.urljoin(r["url"], canon[0])
        if c_abs.rstrip("/") != r["url"].rstrip("/"):
            rep.add("info", "Indexing", "Canonical points to another URL", f"{r['url']} → {c_abs}",
                    "Check whether intended (duplicate) - otherwise self-referencing", url)

    # Text / rendering
    text = " ".join(" ".join(p.text_parts).split())
    words = len(re.findall(r"\w{2,}", text))
    data["words"] = words
    data["text_hash"] = hashlib.sha256(text.encode()).hexdigest()[:16]
    is_next = "__NEXT_DATA__" in html or "self.__next_f" in html
    data["framework"] = "nextjs" if is_next else ("nuxt" if "__NUXT__" in html else
                                                  ("wordpress" if "wp-content" in html else None))
    if words < 120:
        sev = "critical" if (p.root_ids or p.scripts_src >= 3) else "high"
        rep.add(sev, "Rendering", f"Only {words} word(s) in raw HTML",
                f"App root: {', '.join(p.root_ids) or '-'}; external scripts: {p.scripts_src}",
                "AI crawlers (except Googlebot) do not run JS → serve content via SSR/SSG", url)

    # Title / description / H1 / lang
    title = " ".join(p.title.split())
    desc = next((m.get("content", "") for m in p.metas if m.get("name", "").lower() == "description"), "")
    data.update(title=title, description=desc, h1=p.h1s, lang=p.lang)
    if not title:
        rep.add("high", "On-page", "Title missing", "<title> empty", "Set a unique title", url)
    elif len(title) > 65:
        rep.add("low", "On-page", f"Long title ({len(title)} chars)", title,
                "Most important first; Google truncates around 60 chars (not a ranking factor)", url)
    if not desc:
        rep.add("low", "On-page", "Meta description missing", "-", "Concrete answer + benefit (~140-160 chars)", url)
    elif desc.lower().startswith(title.lower()[:30]) and len(title) > 20:
        rep.add("low", "On-page", "Description repeats title (template suspicion)", desc[:120],
                "Write a distinct description per page", url)
    if len(p.h1s) == 0:
        rep.add("medium", "On-page", "No H1 in raw HTML", "-", "One H1 stating the page topic", url)
    elif len(p.h1s) > 1:
        rep.add("low", "On-page", f"{len(p.h1s)} H1 headings", " | ".join(p.h1s)[:200],
                "Usually one H1", url)
    if not p.lang:
        rep.add("low", "Language", "<html lang> missing", "-", 'lang="de-AT" (or the page language)', url)

    # hreflang
    hl = [(l.get("hreflang"), l.get("href")) for l in p.links
          if "alternate" in l.get("rel", "").lower() and l.get("hreflang")]
    data["hreflang"] = hl
    if hl:
        codes = [h for h, _ in hl]
        bad = [h for h in codes if not re.fullmatch(r"(x-default|[a-z]{2,3}(-[A-Za-z]{2}|-[A-Za-z]{4})?)", h or "")]
        if bad:
            rep.add("high", "hreflang", "Invalid hreflang codes", ", ".join(bad),
                    "Format language[-region], e.g. de-AT; a country code alone is invalid", url)
        if "x-default" not in codes:
            rep.add("low", "hreflang", "x-default missing", ", ".join(codes), "Add x-default", url)
        if not any(urllib.parse.urljoin(r["url"], h).rstrip("/") == r["url"].rstrip("/") for _, h in hl):
            rep.add("medium", "hreflang", "No self-reference in hreflang", ", ".join(codes),
                    "Every language version must list itself", url)

    # JSON-LD
    types, errors = set(), []
    for block in p.jsonld:
        try:
            obj = json.loads(block)
            jsonld_types(obj, types)
            if isinstance(obj, (dict, list)) and "@context" not in json.dumps(obj)[:2000]:
                errors.append("@context missing")
        except json.JSONDecodeError as e:
            errors.append(f"JSON error: {e.msg} (line {e.lineno})")
        if PLACEHOLDER_RX.search(block):
            rep.add("high", "Schema", "Placeholder in JSON-LD", PLACEHOLDER_RX.search(block).group(0),
                    "Insert real data", url)
    data["jsonld_types"] = sorted(types)
    data["jsonld_hash"] = hashlib.sha256("".join(p.jsonld).encode()).hexdigest()[:16]
    for e in errors:
        rep.add("high", "Schema", "Invalid JSON-LD", e, "Validate JSON-LD (validator.schema.org)", url)
    if not p.jsonld and is_next:
        rep.add("info", "Schema", "No JSON-LD in raw HTML (Next.js)", "-",
                "Render JSON-LD in a Server Component, not injected client-side", url)
    if "FAQPage" in types:
        rep.add("info", "Schema", "FAQPage present", "FAQ rich results no longer exist since 2026-05-07",
                "Optional to keep (harmless); do not promise rich results", url)
    if "HowTo" in types:
        rep.add("info", "Schema", "HowTo present", "No rich result since 2023", "Optional", url)

    # robots.txt view of this URL for citation-relevant bots
    path = urllib.parse.urlparse(r["url"]).path or "/"
    blocked = []
    for cat in ("search", "user"):
        for bot in BOTS[cat]:
            rules, _ = rules_for(robots_groups, bot)
            if not is_allowed(rules, path):
                blocked.append(bot)
    data["robots_blocked_for"] = blocked
    extra = [b for b in blocked if b not in root_blocked]  # root-level blocks are reported once site-wide
    if extra:
        rep.add("critical" if "Googlebot" in extra or "OAI-SearchBot" in extra else "high",
                "AI crawlers", "URL blocked by robots.txt for citation-relevant bots", ", ".join(extra),
                "Remove Disallow for search/user bots (repeat Disallows per group)", url)
    data["internal_links"] = p.a_internal
    if p.a_internal == 0 and words >= 120:
        rep.add("medium", "Internal links", "No internal links in raw HTML", "-",
                "Render navigation/links server-side; otherwise the page links nowhere", url)
    data["details_blocks"] = p.details
    data["modified"] = next((m.get("content") for m in p.metas
                             if m.get("property", "").lower() == "article:modified_time"), None)
    return data


# ----------------------------------------------------------------------------- Site checks
def check_robots(origin: str, rep: Report):
    r = fetch(origin + "/robots.txt")
    info = {"status": r["status"], "groups": [], "sitemaps": [], "matrix": {}}
    if r["error"] or (r["status"] and r["status"] >= 500):
        rep.add("critical", "robots.txt", "robots.txt unreachable / 5xx",
                r["error"] or f"HTTP {r['status']}", "5xx/timeout = crawlers treat the whole site as disallowed", origin)
        info["mode"] = "disallow-all"
        return [(["*"], [("disallow", "/")])], info
    if r["status"] and 400 <= r["status"] < 500:
        rep.add("info", "robots.txt", f"robots.txt returns {r['status']}", "4xx = no restrictions",
                "Optionally add a robots.txt with a Sitemap line", origin)
        info["mode"] = "allow-all"
        return [], info
    text = decode(r["body"], r["headers"])
    if "<html" in text[:500].lower():
        rep.add("high", "robots.txt", "robots.txt returns HTML (catch-all?)", text[:80],
                "Serve a real text file", origin)
    groups, sitemaps = parse_robots(text)
    info["groups"], info["sitemaps"] = [a for a, _ in groups], sitemaps
    all_agents = {a for ag, _ in groups for a in ag}
    for stale, repl in STALE_TOKENS.items():
        if stale in all_agents:
            rep.add("low", "robots.txt", f"Outdated token '{stale}'", "no longer has any effect",
                    f"Replace with {repl}", origin)
    if "content-signal:" in text.lower():
        rep.add("info", "robots.txt", "Content-Signal lines found (Cloudflare?)", "may trigger a GSC warning",
                "Harmless; check whether Cloudflare 'Managed robots.txt' prepends Disallows", origin)
    for cat, bots in BOTS.items():
        for bot in bots:
            rules, used = rules_for(groups, bot)
            ok = is_allowed(rules, "/")
            info["matrix"][bot] = {"category": cat, "group": used, "root_allowed": ok}
            if not ok and cat in ("search", "user"):
                rep.add("critical" if bot in ("Googlebot", "bingbot", "OAI-SearchBot") else "high",
                        "AI crawlers", f"{bot} blocked for '/'", f"Group: {used}",
                        "Allow search/user bots (citation-relevant)", origin)
    if not sitemaps:
        rep.add("low", "Sitemap", "No Sitemap line in robots.txt", "-", "Add Sitemap: https://…/sitemap.xml", origin)
    return groups, info


def check_sitemap(origin: str, sitemaps: list, rep: Report, limit_children: int = 5):
    urls, lastmods, checked = [], [], []
    queue = list(sitemaps) or [origin + "/sitemap.xml"]
    while queue and len(checked) < limit_children + 1:
        sm = queue.pop(0)
        if not same_site(sm, origin):
            continue
        checked.append(sm)
        r = fetch(sm)
        if r["status"] != 200:
            rep.add("medium", "Sitemap", f"Sitemap not retrievable ({r['status'] or r['error']})", sm,
                    "Check the sitemap URL", origin)
            continue
        try:
            root = ET.fromstring(r["body"])
        except ET.ParseError as e:
            rep.add("high", "Sitemap", "Sitemap is not valid XML", f"{sm}: {e}", "Fix the XML", origin)
            continue
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        if root.tag.endswith("sitemapindex"):
            queue.extend(loc.text.strip() for loc in root.findall("s:sitemap/s:loc", ns) if loc.text and same_site(loc.text.strip(), origin))
        for u in root.findall("s:url", ns):
            loc = u.find("s:loc", ns)
            lm = u.find("s:lastmod", ns)
            if loc is not None and loc.text and same_site(loc.text.strip(), origin):
                urls.append(loc.text.strip())
                lastmods.append(lm.text.strip() if lm is not None and lm.text else None)
    info = {"checked": checked, "url_count": len(urls)}
    if urls:
        with_lm = [x for x in lastmods if x]
        info["lastmod_share"] = round(len(with_lm) / len(urls), 2)
        if with_lm and len(set(with_lm)) == 1 and len(with_lm) > 5:
            rep.add("medium", "Sitemap", "All lastmod values identical", with_lm[0],
                    "Set lastmod only on real content changes, otherwise Google ignores it", origin)
        foreign = [u for u in urls if urllib.parse.urlparse(u).netloc != urllib.parse.urlparse(origin).netloc]
        if foreign:
            rep.add("high", "Sitemap", f"{len(foreign)} URLs on a different host", foreign[0],
                    "List canonical-host URLs only", origin)
    return urls, info


def check_soft404(origin: str, rep: Report):
    probe = f"{origin}/geo-audit-404-{secrets.token_hex(4)}"
    r = fetch(probe)
    if r["status"] == 200:
        rep.add("high", "Indexing", "Soft 404: unknown URL returns 200", probe,
                "Non-existent URLs must return 404/410", origin)
    return r["status"]


def check_llms(origin: str, rep: Report):
    r = fetch(origin + "/llms.txt", follow=False)
    st = r["status"]
    if st == 200:
        t = decode(r["body"], r["headers"])
        if "<html" in t[:300].lower():
            rep.add("low", "llms.txt", "llms.txt returns HTML (catch-all 200)", "-",
                    "Either a real Markdown file or 404 (no ranking effect)", origin)
        elif not t.lstrip().startswith("# "):
            rep.add("info", "llms.txt", "llms.txt without H1", t[:60], "Optional: '# Name' + short description", origin)
    return st


def ua_test(origin: str, rep: Report):
    res = {}
    base = fetch(origin + "/")
    for cat in ("search", "user", "training"):
        for bot in BOTS[cat]:
            if bot in ("Google-Extended", "Applebot-Extended"):
                continue  # control tokens only, no crawler of their own
            r = fetch(origin + "/", ua=f"Mozilla/5.0 (compatible; {bot}/1.0)")
            res[bot] = r["status"]
            if base["status"] == 200 and r["status"] in (401, 403, 429, 503):
                rep.add("high" if cat != "training" else "medium", "CDN/WAF",
                        f"{bot} UA gets {r['status']}", "UA test (unverified, not from bot IP)",
                        "Check Cloudflare AI Crawl Control / Bot Fight Mode / WAF / Fail2ban", origin)
    return res


# ----------------------------------------------------------------------------- Baseline / compare
def compare(base: dict, cur: dict, rep: Report):
    bpages = {p["url"]: p for p in base.get("pages", [])}
    bm, cm = base.get("robots", {}).get("matrix", {}), cur.get("robots", {}).get("matrix", {})
    root_new = {bot for bot, v in cm.items() if bm.get(bot, {}).get("root_allowed") and not v.get("root_allowed")}
    for p in cur.get("pages", []):
        b = bpages.get(p["url"])
        if not b:
            continue
        u = p["url"]
        if (b.get("status") or 0) < 400 <= (p.get("status") or 0):
            rep.add("critical", "Drift", "Status is now an error", f"{b.get('status')} → {p.get('status')}", "Check the deploy", u)
        for f in ("meta_robots", "x_robots"):
            if "noindex" in (p.get(f) or "") and "noindex" not in (b.get(f) or ""):
                rep.add("critical", "Drift", f"New noindex ({f})", p.get(f), "Revert immediately if unintended", u)
        if b.get("canonical") != p.get("canonical"):
            rep.add("critical", "Drift", "Canonical changed", f"{b.get('canonical')} → {p.get('canonical')}", "Check intent", u)
        newly_blocked = set(p.get("robots_blocked_for") or []) - set(b.get("robots_blocked_for") or []) - root_new
        if newly_blocked:
            rep.add("critical", "Drift", "Newly blocked bots (robots.txt)", ", ".join(sorted(newly_blocked)), "Check robots.txt", u)
        lost = set(b.get("jsonld_types") or []) - set(p.get("jsonld_types") or [])
        if lost:
            rep.add("high", "Drift", "Schema types removed", ", ".join(sorted(lost)), "Check JSON-LD", u)
        bw, cw = b.get("words") or 0, p.get("words") or 0
        if bw >= 150 and cw < bw * 0.7:
            rep.add("high", "Drift", "Raw-HTML text dropped by >30 %", f"{bw} → {cw} words",
                    "Check rendering (SSR) and content", u)
        bh, ch = " ".join(b.get("h1") or []), " ".join(p.get("h1") or [])
        if bh and difflib.SequenceMatcher(None, bh, ch).ratio() < 0.5:
            rep.add("high", "Drift", "H1 changed substantially", f"'{bh[:60]}' → '{ch[:60]}'", "Check intent", u)
        if b.get("title") != p.get("title"):
            rep.add("low", "Drift", "Title changed", f"'{(b.get('title') or '')[:60]}' → '{(p.get('title') or '')[:60]}'", "-", u)
    for bot in sorted(root_new):
        v = cm[bot]
        rep.add("critical" if v["category"] in ("search", "user") else "medium", "Drift",
                f"{bot} newly blocked", f"Group {v.get('group')}", "Check robots.txt", None)


# ----------------------------------------------------------------------------- Output
def render_md(result: dict, rep: Report) -> str:
    out = [f"# GEO/SEO audit: {result['origin']}",
           f"_geo_audit.py {VERSION} · {result['date']} · {len(result['pages'])} page(s) · raw HTML without JS_", ""]
    counts = {s: 0 for s in SEVERITY_ORDER}
    for f in rep.findings:
        counts[f["severity"]] += 1
    out.append("**Findings:** " + " · ".join(f"{k}: {v}" for k, v in counts.items()))
    out.append("")
    m = result.get("robots", {}).get("matrix", {})
    if m:
        out += ["## Bot matrix (robots.txt, path /)", "", "| Bot | Purpose | Group | Allowed | UA test |", "|---|---|---|---|---|"]
        ua = result.get("ua_test", {})
        for bot, v in m.items():
            out.append(f"| {bot} | {v['category']} | {v['group'] or '-'} | {'yes' if v['root_allowed'] else '**NO**'} | {ua.get(bot, '-')} |")
        out.append("")
    out += ["## Pages", "", "| URL | Status | Words (raw) | H1 | Canonical | JSON-LD | Framework |", "|---|---|---|---|---|---|---|"]
    for p in result["pages"]:
        out.append(f"| {p['url']} | {p.get('status')} | {p.get('words', '-')} | {len(p.get('h1') or [])} | "
                   f"{'yes' if p.get('canonical') else 'no'} | {', '.join(p.get('jsonld_types') or []) or '-'} | {p.get('framework') or '-'} |")
    out += ["", "## Findings (issue · evidence · fix)", ""]
    for f in rep.sorted():
        out.append(f"- **[{f['severity']}] {f['area']}: {f['issue']}**" + (f" — {f['url']}" if f['url'] else ""))
        out.append(f"  - Evidence ({f['label']}): `{str(f['evidence'])[:300]}`")
        out.append(f"  - Fix: {f['fix']}")
    out += ["", "## Not checked (out of scope)", "",
            "- Rendered HTML / Googlebot view → GSC URL Inspection, Rich Results Test",
            "- Core Web Vitals (field data) → PageSpeed Insights / CrUX",
            "- Real bot access → server logs (the UA test is only an indication)",
            "- GSC setting 'Search generative AI' (must be Include), GBP, off-site signals"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="SEO/AEO/GEO quick audit (raw HTML, no JS)")
    ap.add_argument("url")
    ap.add_argument("--pages", type=int, default=5, help="Number of sitemap pages (in addition to the start URL)")
    ap.add_argument("--urls", nargs="*", default=[], help="Additional specific URLs")
    ap.add_argument("--ua-test", action="store_true", help="Test status codes per bot user agent (indication)")
    ap.add_argument("--json", help="Save result as JSON")
    ap.add_argument("--md", help="Save report as Markdown (otherwise stdout)")
    ap.add_argument("--save-baseline", help="Save result as baseline")
    ap.add_argument("--compare", help="Compare against a baseline (drift rules)")
    a = ap.parse_args()

    start = a.url if a.url.startswith("http") else "https://" + a.url
    pu = urllib.parse.urlparse(start)
    origin = f"{pu.scheme}://{pu.netloc}"
    rep = Report()
    result = {"origin": origin, "date": time.strftime("%Y-%m-%d %H:%M"), "version": VERSION}

    groups, rinfo = check_robots(origin, rep)
    result["robots"] = rinfo
    urls, sinfo = check_sitemap(origin, rinfo.get("sitemaps", []), rep)
    result["sitemap"] = sinfo
    result["soft404_status"] = check_soft404(origin, rep)
    result["llms_txt_status"] = check_llms(origin, rep)
    if a.ua_test:
        result["ua_test"] = ua_test(origin, rep)

    targets = [start] + a.urls
    base = None
    if a.compare:
        with open(a.compare, encoding="utf-8") as fh:
            base = json.load(fh)
        targets += [p["url"] for p in base.get("pages", [])]
    step = max(1, len(urls) // max(1, a.pages)) if urls else 1
    targets += urls[::step][: a.pages]
    root_blocked = frozenset(b for b, v in rinfo.get("matrix", {}).items() if not v["root_allowed"])
    seen, pages = set(), []
    for u in targets:
        if u in seen:
            continue
        seen.add(u)
        pages.append(analyze_page(u, rep, groups, pu.netloc, root_blocked))
        time.sleep(0.3)
    result["pages"] = pages

    if base is not None:
        compare(base, result, rep)
    result["findings"] = rep.sorted()
    md = render_md(result, rep)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    else:
        print(md)
    for path in (a.json, a.save_baseline):
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2, default=str)
    sys.exit(2 if rep.has_critical() else 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
