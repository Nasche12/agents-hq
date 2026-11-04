---
name: seo-aeo-geo
description: SEO, AEO and GEO playbook (as of Oct 2026) for auditing and implementing client websites – Google, AI Overviews/AI Mode, ChatGPT, Claude, Perplexity, Copilot.
---

<!-- Projekt-Kopie. Herkunft: C:Users.claudeskillsseo-aeo-geoSKILL.md (Playbook v3, Stand 7. Oktober 2026), kopiert am 2026-11-04 unveraendert (nur dieser Kommentar ergaenzt). Aenderungen am Original nachziehen, nicht hier editieren. -->

# SEO · AEO · GEO Playbook v3 (as of 7 October 2026)

Goal: every website we build or maintain should (1) rank in Google, (2) appear as a source in AI Overviews / AI Mode, and (3) be mentioned or cited by ChatGPT, Gemini, Copilot, Perplexity and Claude.

Terms:
- **SEO** – ranking in search engines (Google, Bing).
- **AEO** (Answer Engine Optimization) – building content so it gets used as a direct answer (AI Overviews, snippets, Copilot, voice).
- **GEO** (Generative Engine Optimization) – mentions and citations in generative answers (ChatGPT, Gemini, AI Mode, Perplexity, Claude).

Market context: the agency works mainly for Austrian/DACH clients, so examples use German-language sites, `de-AT`, Austrian directories and Austrian/EU law. Client-facing deliverables are written in the client's language.

## The 10 core truths (read first)

1. **Good SEO is the foundation of GEO.** Google (guide of 2026-05-15): AI Overviews/AI Mode need no special files, no special schema, no Markdown, no chunking, no "AI writing style". A page must be indexed and eligible for snippets.
2. **No GEO trick has been shown to work reliably across platforms** (critical survey of 45 studies, arXiv 2607.14035, July 2026). In an end-to-end test, rewriting content "for AI" even lowered top-10 presence by 16 %. → Never promise clients citations.
3. **Off-site mentions are the strongest predictor** (Ahrefs, 75,000 brands: brand mentions ρ 0.664 vs. backlinks 0.218 – correlation). AI search shows a strong bias toward earned media (Chen et al. 2025).
4. **Schema is not an AI-citation lever** (Ahrefs difference-in-differences experiment, 1,885 pages: no significant effect), but is still needed for rich results, entity clarity and merchant/local data.
5. **llms.txt does nothing for search** (Google: "will neither harm nor help"; SE Ranking, 300,000 domains: no relationship). Only useful for docs/developer tools.
6. **Crawl access is the most common silent killer**: Cloudflare/WAF blocking AI bots, robots.txt disallowing OAI-SearchBot/Claude-SearchBot/PerplexityBot, content only rendered client-side.
7. **AI crawlers (except Googlebot) do not render JavaScript.** Core content must be in the initial HTML.
8. **For local queries, the Google Business Profile itself is the source** in AI Mode/AI Overviews.
9. **AI answers are stochastic**: the same recommendation list repeats in < 1 % of runs (SparkToro 2026). Measure visibility % across many runs, never "positions".
10. **DACH reality**: Google remains by far the largest channel; among chatbots in Austria, ChatGPT ~83 %, Gemini ~10 %, Perplexity ~3 %, Copilot ~3 %, Claude ~1 % (Statcounter, Sep 2026). Priority: Google → Bing/Copilot (Bing also feeds third parties) → ChatGPT → the rest.

## Evidence traffic light (for client conversations)

| Measure | Evidence | Assessment |
|---|---|---|
| Indexing, crawl access, SSR | strong (Google docs, Vercel/MERJ logs) | Mandatory |
| Classic rankings/authority | strong | 38 % of AIO citations come from the top 10, 31 % from positions 11–100 (Ahrefs 2026) |
| Brand mentions / earned media | medium (consistent correlation) | Most important off-site lever |
| Answer/definition early on the page | medium (44 % of ChatGPT citations come from the first third, Indig 2026) | Implement |
| Statistics, sources, quotations in the text | medium (lab, Princeton 2024: +30–41 %) | Implement where genuinely available |
| Headings, lists, tables | weak–medium | Good practice for humans, not forced |
| Freshness | medium, platform-dependent (strong for ChatGPT, minor for AIO) | Real updates, no date faking |
| YouTube presence | medium (YouTube 5.6 % of all AIO citations, 18 % of non-ranking citations) | For suitable clients |
| Schema/JSON-LD for AI | strongly negative (no effect) | Keep using for rich results/entity |
| llms.txt | medium–strongly negative | Docs/SaaS only |
| Keyword stuffing | negative (−8.8 %) | Never |
| Hidden prompts, cloaking for AI bots, fake mentions | spam policy | Never |

---

## 0. Workflow per website

1. **Access**: Google Search Console (incl. the *Search Generative AI performance* report), Bing Webmaster Tools (*AI Performance*), GBP, Apple Business, Bing Places, hosting/CDN, GA4/Matomo.
2. **Blocker check** (sections 1.1–1.3): `geo_audit.py <url> --pages 15 --ua-test --save-baseline baseline.json` (skill **seo-geo-tools**), then manually: CDN/WAF settings, rendered HTML (GSC URL Inspection), GSC setting *Search generative AI* (must be "Include").
3. **Technical** (1.4–1.7): indexing, canonicals, sitemaps, CWV, 2 MB limit, IndexNow.
4. **Entity** (3): Organization/LocalBusiness schema, sameAs, NAP consistency, legal notice (Impressum).
5. **Content** (2): question inventory, answer early, information gain, E-E-A-T.
6. **Off-site** (4): mentions, directories, reviews, YouTube, communities.
7. **Local** (5) or **commerce** (6), if relevant.
8. **Legal** (7): consent, AI Act, accessibility, legal notice.
9. **Monitoring** (8, 13, 17): entity profile + resolution test (15), prompt set with control group, deploy gate, alerts – review monthly.

Priority is always: blockers → indexing → entity → content → off-site → fine-tuning.

### 0.1 Working rules for audits and recommendations

- **Label every number**: *measured* (tool/log/GSC), *client-provided*, *estimated*, *proxy* (e.g. API instead of the real interface). Never present estimates as measurements.
- **Finding format**: issue · impact · evidence (command/source + excerpt) · fix · priority (critical/high/medium/low) · effort (S/M/L). No evidence → "Not checked / out of scope" section, not a finding.
- **Every recommendation also states**: the observation it is based on · dependency (what must be done first) · how we will know it is not working · leading indicator + review date.
- **Scores only for what was measured**; mark unmeasured areas as "not measured", no made-up overall grades.
- **Report structure**: summary (3 sentences) → blockers → action plan in 4 phases (week 1 critical · weeks 2–3 high · month 2 medium · ongoing) → findings list → out of scope → measurement plan (section 13).
- **Overlap with a Google update is a hypothesis, not proof.** Always cross-check the update chronology (9) and your own deploy annotations (GSC).

Do not deploy major URL/structure changes during a core/spam rollout; evaluate no earlier than 1 week after completion.

---

## 1. Technical foundation

### 1.1 Bots & robots.txt

| Vendor | Training | Search/index (citation-relevant) | User fetch / agent | Verification |
|---|---|---|---|---|
| OpenAI | `GPTBot` | `OAI-SearchBot` | `ChatGPT-User` (robots.txt may not apply), Atlas browser = regular Chrome | openai.com/searchbot.json, gptbot.json, chatgpt-user.json |
| OpenAI Ads | – | `OAI-AdsBot` (checks ad landing pages) | – | openai.com/adsbot.json |
| Anthropic | `ClaudeBot` | `Claude-SearchBot` (web search is based on **Brave Search**) | `Claude-User` | claude.com/crawling/bots.json |
| Perplexity | – | `PerplexityBot` | `Perplexity-User` (generally ignores robots.txt), Comet = Chrome | perplexity.com/perplexitybot.json |
| Google | `Google-Extended` (token only; controls Gemini apps/Vertex training + grounding, **not** AIO/AI Mode) | `Googlebot` (Search, AIO, AI Mode) | `Google-Agent` (user-triggered, ignores robots.txt), `Google-GeminiNotebook` (replaces NotebookLM, 07/2026) | IP ranges since 02/2026 under developers.google.com/crawling/ipranges; docs: developers.google.com/crawling; Web Bot Auth experimental |
| Microsoft | – | `bingbot` (feeds Copilot + third parties) | – | bing.com/toolbox/bingbot.json |
| Apple | `Applebot-Extended` (token only) | `Applebot` | – | Apple JSON (support.apple.com/119829) |
| Meta | `Meta-ExternalAgent` | `Meta-WebIndexer` (Meta AI search) | `Meta-ExternalFetcher` | ASN 32934 |
| Mistral | `MistralAI-Training` | `MistralAI-Index` | `MistralAI-User` | docs.mistral.ai/robots |
| xAI | – | `xAI-SearchBot` (unconfirmed) | – | – |
| Common Crawl | `CCBot` | – | – | – |

Rules:
- Any bot with its own `User-agent` group ignores the `*` group entirely → repeat Disallows in every group.
- Blocking `ClaudeBot` does not block `Claude-SearchBot` (and vice versa). Blocking `GPTBot` does not block `OAI-SearchBot`.
- Outdated tokens (`anthropic-ai`, `Claude-Web`) have no effect → replace them.
- `OAI-SearchBot` blocked ⇒ no citations in ChatGPT search (navigation links only). Takes effect after ~24 h.
- Brave does not crawl what is blocked for Googlebot → blocking Googlebot also costs Claude visibility.
- Never "trust" a bot by user agent – verify via the IP JSON files when something looks off.
- **Cloudflare**: new zones block AI crawlers by default; "Managed robots.txt" prepends Disallows. Check under *AI Crawl Control* / *Bots*. Also check Bot Fight Mode, WAF rules, Plesk Fail2ban/ModSecurity, Wordfence.
- Cloudflare Content-Signals lines in robots.txt can trigger "Syntax not understood" in GSC – harmless.

**Default robots.txt (maximum visibility, default for SMBs/restaurants/SaaS)** – `public/robots.txt`:

```txt
User-agent: *
Allow: /
Disallow: /admin/
Disallow: /api/
Disallow: /cart/
Disallow: /checkout/
Disallow: /*?*sort=

# AI search, index & user fetch
User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: OAI-AdsBot
User-agent: Claude-SearchBot
User-agent: Claude-User
User-agent: PerplexityBot
User-agent: Perplexity-User
User-agent: Meta-WebIndexer
User-agent: Meta-ExternalFetcher
User-agent: MistralAI-Index
User-agent: MistralAI-User
Allow: /
Disallow: /admin/
Disallow: /api/
Disallow: /cart/
Disallow: /checkout/

# Training (allowed → brand ends up in model knowledge)
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
User-agent: Meta-ExternalAgent
User-agent: MistralAI-Training
Allow: /
Disallow: /admin/
Disallow: /api/

Sitemap: https://www.example.com/sitemap.xml
```

Adjust paths to the actual site (e.g. `/warenkorb/` on German-language shops).

**Training opt-out variant (publishers/paid content)** – replace the training group with:

```txt
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: CCBot
User-agent: Google-Extended
User-agent: Applebot-Extended
User-agent: Meta-ExternalAgent
User-agent: MistralAI-Training
User-agent: Bytespider
Disallow: /
```

Record the decision per client in writing.

**Quick check** `ai-bot-check.sh` (full RFC 9309 evaluation, bot matrix and drift comparison: `geo_audit.py` in the seo-geo-tools skill):

```bash
#!/usr/bin/env bash
# Usage: ./ai-bot-check.sh https://www.example.com
set -u
URL="${1:?URL required}"
echo "== robots.txt =="; curl -s "$URL/robots.txt" | head -n 80
echo; echo "== Status codes per bot UA (403/503 = CDN/WAF blocks) =="
for ua in Googlebot bingbot OAI-SearchBot ChatGPT-User GPTBot Claude-SearchBot Claude-User ClaudeBot PerplexityBot Meta-WebIndexer MistralAI-User; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -A "Mozilla/5.0 (compatible; $ua/1.0)" "$URL/")
  printf "%-18s %s\n" "$ua" "$code"
done
echo; echo "== Text in the initial HTML (what an AI crawler sees) =="
curl -s -A "Mozilla/5.0 (compatible; OAI-SearchBot/1.4)" "$URL/" \
 | sed -e 's/<script[^>]*>.*<\/script>//g' -e 's/<[^>]*>/ /g' | tr -s ' \n' | head -c 2500; echo
echo; echo "== HTML size (Googlebot only processes the first 2 MB) =="
curl -s "$URL/" | wc -c
echo; echo "== Robots meta / X-Robots-Tag =="
curl -sI "$URL/" | grep -i x-robots-tag
curl -s "$URL/" | grep -io '<meta[^>]*name="robots"[^>]*>'
echo; echo "== llms.txt (optional) =="; curl -s -o /dev/null -w "%{http_code}\n" "$URL/llms.txt"
```

**Log analysis (Plesk)**:

```bash
LOG=/var/www/vhosts/example.com/logs/access_ssl_log
grep -Eio "Googlebot|bingbot|GPTBot|OAI-SearchBot|ChatGPT-User|OAI-AdsBot|ClaudeBot|Claude-SearchBot|Claude-User|PerplexityBot|Perplexity-User|Meta-WebIndexer|Meta-ExternalAgent|MistralAI-[A-Za-z]+|Applebot" "$LOG" \
 | sort | uniq -c | sort -rn
# 404 share of AI bots (AI crawlers often hit old URLs → check redirects)
grep -E "OAI-SearchBot|Claude-SearchBot|PerplexityBot" "$LOG" | awk '$9==404{print $7}' | sort | uniq -c | sort -rn | head
```

### 1.2 Rendering

- Main content, prices, opening hours, FAQ answers, tables **in the initial HTML** → SSR/SSG/ISR (Next.js Server Components, Nuxt SSR, Astro). A pure CSR SPA is empty for ChatGPT/Claude/Perplexity.
- No content behind JS-populated tabs/accordions; build FAQs with `<details><summary>`.
- `noindex` in the initial HTML can prevent rendering → removing it via JS is unreliable.
- Do not change the canonical via JS (Google evaluates it before and after rendering).
- Error pages with a status ≠ 200 may not be rendered → return real status codes.
- Agent-friendly (web.dev 2026): real `<button>`/`<a>`, stable layouts, no invisible overlays, a clean accessibility tree.

### 1.3 Snippet and AI controls (Google)

- `nosnippet`, `max-snippet`, `data-nosnippet`, `noindex` also control AI Overviews/AI Mode. **Never set them globally.**
- **Search Console → Settings → Search generative AI** (worldwide since 2026-08-31): excludes a property from AIO, AI Mode and Discover AI (no ranking effect on the rest of Search, takes effect within 1–2 days). Always keep clients on **Include** unless deliberately requested. Check during audits.
- `Google-Extended` does **not** affect AIO/AI Mode.

### 1.4 Indexing & basics

- HTTPS, one host (301), no redirect chains, self-referencing canonicals.
- **Googlebot only processes the first 2 MB of HTML** (incl. headers; PDFs 64 MB) → lean HTML, content/links/canonical early, no huge inline JSON.
- XML sitemap: `lastmod` only on real changes (otherwise Google ignores it); `priority`/`changefreq` are ignored; max. 50 MB/50,000 URLs.
- `noindex` for thank-you, login, filter and internal search pages.
- `hreflang`: `de-AT`, `de-DE`, `en` + `x-default`, reciprocal, absolute URLs. A country code alone is invalid.
- AVIF is officially supported by Google Images.

### 1.5 IndexNow (Bing, Yandex, Naver, Seznam, Yep – **not Google**)

Worth it because of Bing → Copilot and third-party engines.

```bash
KEY=$(openssl rand -hex 16); echo -n "$KEY" > public/$KEY.txt
curl -s -X POST "https://api.indexnow.org/indexnow" -H "Content-Type: application/json; charset=utf-8" -d "{
  \"host\":\"www.example.com\",\"key\":\"$KEY\",\"keyLocation\":\"https://www.example.com/$KEY.txt\",
  \"urlList\":[\"https://www.example.com/new-page\"]}"
```

Next.js: ping after deploy/publish in CI or a CMS webhook. WordPress: Microsoft's "IndexNow" plugin or the Rank Math/Yoast integration.

### 1.6 Core Web Vitals (officially unchanged since 2024-03-12, p75, field data)

| Metric | Good | Poor |
|---|---|---|
| LCP | ≤ 2.5 s | > 4.0 s |
| INP | ≤ 200 ms | > 500 ms |
| CLS | ≤ 0.1 | > 0.25 |

Blog claims about tightened thresholds in 2025/2026 are **false** (no confirmation by web.dev/Chrome).
Fixes: hero image `fetchpriority="high"`, AVIF/WebP, `width/height`, fonts preloaded + `font-display: swap`, third-party scripts async/defer, break up long tasks (`scheduler.yield()`), less client JS, TTFB < 600 ms, CDN.
Mobile counts (mobile-first indexing); INP is the most frequently failed metric. Measure with PageSpeed Insights (field + lab), the GSC CWV report, `web-vitals` npm → GA4/Matomo.
**Cookie banners** can become the LCP element (documented 1.4 s → 3.6 s), cause CLS and worsen INP → use an overlay (fixed), load the script async, never inject it into the layout.

### 1.7 Next.js (currently 16.3) – copy-paste

`app/robots.ts`:
```ts
import type { MetadataRoute } from "next";
const BASE = "https://www.example.com";
const DIS = ["/admin/", "/api/"];
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: DIS },
      { userAgent: ["OAI-SearchBot","ChatGPT-User","OAI-AdsBot","Claude-SearchBot","Claude-User","PerplexityBot","Perplexity-User","Meta-WebIndexer","Meta-ExternalFetcher","MistralAI-Index","MistralAI-User"], allow: "/", disallow: DIS },
      { userAgent: ["GPTBot","ClaudeBot","Google-Extended","Applebot-Extended","Meta-ExternalAgent","MistralAI-Training"], allow: "/", disallow: DIS },
    ],
    sitemap: `${BASE}/sitemap.xml`,
  };
}
```

`app/sitemap.ts`:
```ts
import type { MetadataRoute } from "next";
import { getAllPages } from "@/lib/content"; // { slug, updatedAt }
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const pages = await getAllPages();
  return pages.map((p) => ({
    url: new URL(p.slug, "https://www.example.com/").toString(),
    lastModified: p.updatedAt, // real content changes only
  }));
}
```

`generateMetadata` per page:
```ts
import type { Metadata } from "next";
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const page = await getPage(slug);
  return {
    metadataBase: new URL("https://www.example.com"),
    title: page.seoTitle,                 // ~50–60 chars, topic first, brand last
    description: page.seoDescription,     // ~140–160 chars, concrete answer + benefit
    alternates: { canonical: `/${slug}`, languages: { "de-AT": `/${slug}`, en: `/en/${slug}`, "x-default": `/${slug}` } },
    openGraph: { type: "article", locale: "de_AT", images: [page.ogImage] },
    robots: { index: true, follow: true, "max-image-preview": "large" },
  };
}
```

JSON-LD (Server Component):
```tsx
export function JsonLd({ data }: { data: object | object[] }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }} />;
}
```

Astro 7: static/SSR, ideal for content sites. WordPress: Yoast or Rank Math; their llms.txt generator is optional.

---

## 2. Content (AEO & GEO)

### 2.1 What Google officially wants (guide 2026-05-15, updated 2026-07-10)
- Unique, non-interchangeable content with its own perspective ("non-commodity").
- Good images and videos, semantic HTML, page experience, internal linking.
- Merchant Center and Google Business Profile for products/services.
- **Not needed**: AI text files, Markdown copies, chopping content into tiny pieces, a special AI writing style, special schema. Collecting inauthentic mentions is "not helpful".
- Sullivan (01/2026): do not break content into chunks for LLMs. Mueller: "Write like blogging is alive".

### 2.2 Page structure (built for humans, easy for machines to read)

```
H1: topic/question, phrased the way customers phrase it
Intro (1–3 sentences): direct answer/definition with a concrete fact (price, time, place, number).
Key facts: short list or HTML table when there are real facts.
One H2 per sub-question (fan-out: what / how / cost / duration / comparison / alternatives / mistakes)
  → core sentence first, then depth, examples, own experience.
Own data/photos/case examples (information gain).
Evidence: linked primary sources, numbers with dates.
Author (name, role, photo, link) + visible "Updated on DD.MM.YYYY".
FAQ (<details>) with real customer questions only.
```

Rules:
- Core statement early (44 % of ChatGPT citations come from the first third).
- Name unambiguous entities (brand, place, product, person), use definitional sentences ("X is …").
- Real numbers, sources, expert quotes – no invented statistics.
- No promotional tone in informational content (Semrush: promotional −26 % citations).
- Structure paragraphs sensibly, but do not fragment artificially.
- Freshness = real content updates. Only changing the year/date = spam pattern.
- No self-promotional "best X" lists ranking yourself #1 (SaaS sites observed losing 30–50 % after the Dec 2025 update).
- AI-written text is allowed, but: human fact-checked, adds value, titles/metas/alt texts reviewed too. Mass AI pages = scaled content abuse. AI images: IPTC `TrainedAlgorithmicMedia`.
- Build the question inventory from: GSC queries, Bing grounding queries, customer emails/calls, reviews, "People also ask", Reddit/forums, the "What did you ask?" form field (13).
- Service/landing pages also need **negative scoping** ("not suitable for …") and the delivery/service area – this makes the page unambiguous for matching queries.
- Quality-check before publishing with the content rubric (14); decide the page type beforehand via SERP consensus (16.4).

### 2.3 E-E-A-T (DACH)
- Complete legal notice (see 7.5), an about page with real people, qualifications, founding year.
- Author pages with `Person` schema and sameAs.
- Genuine, visible reviews; link certificates, chamber of commerce (WKO) membership, press.
- YMYL (health, legal, finance): name the expert reviewer.

### 2.4 llms.txt
No proven effect on search/citations. Only for SaaS/API/docs (coding agents read it). Otherwise skip it, or generate it via Yoast/Rank Math in 5 minutes.

```md
# BrandName
> One sentence: who, what, for whom, where.

## Docs
- [API reference](https://docs.example.com/api): endpoints, auth
- [Quickstart](https://docs.example.com/start)

## Product
- [Pricing](https://www.example.com/pricing)
```

---

## 3. Structured data & entity

As of 2026:
- **Gone**: FAQ rich results (since 2026-05-07; reports June, API Aug 2026), HowTo (2023), Book Actions, Course Info, ClaimReview, Estimated Salary, Learning Video, Special Announcement, Vehicle Listing (2025), Practice Problem (01/2026). SERP features Nutrition Facts, Nearby Offers and the Events box removed (check the docs for the current Event schema status before relying on it). Dataset is only used by Dataset Search.
- **New/extended**: Loyalty Programs, organization-level shipping policies, DiscussionForum/QAPage properties, `hasAdultConsideration`, merchant `category` + sale date, VideoObject `creator`. Rule against fake/incentivized reviews in review snippets (07/2026).
- FAQPage markup does no harm and helps Google understand the page – optional.
- Schema must reflect visible content. Not an AI-citation lever (see traffic light).

Mandatory set: `Organization`/`LocalBusiness` subtype + `WebSite` (home page), `BreadcrumbList` (subpages), page-specific type (`Product`, `Article`, `Event`, `VideoObject` …).

**Organization + WebSite**:
```json
[{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://www.example.com/#org",
  "name": "BrandName GmbH",
  "url": "https://www.example.com/",
  "logo": "https://www.example.com/logo.png",
  "description": "One precise sentence – identical to the positioning everywhere on the web.",
  "foundingDate": "2020",
  "address": { "@type": "PostalAddress", "streetAddress": "Street 1", "postalCode": "8010", "addressLocality": "Graz", "addressCountry": "AT" },
  "contactPoint": { "@type": "ContactPoint", "telephone": "+43-316-000000", "email": "office@example.com", "contactType": "customer service", "availableLanguage": ["de","en"] },
  "sameAs": ["https://www.linkedin.com/company/xxx","https://www.instagram.com/xxx","https://www.youtube.com/@xxx","https://firmen.wko.at/xxx","https://www.wikidata.org/wiki/Qxxx"]
},{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": "https://www.example.com/#website",
  "url": "https://www.example.com/",
  "name": "BrandName",
  "inLanguage": "de-AT",
  "publisher": { "@id": "https://www.example.com/#org" }
}]
```

**Restaurant** (incl. menu – no rich result, but machine-readable):
```json
{
  "@context": "https://schema.org",
  "@type": "Restaurant",
  "@id": "https://www.example.com/#business",
  "name": "Restaurant Name",
  "image": ["https://www.example.com/img/exterior.jpg"],
  "url": "https://www.example.com/",
  "telephone": "+43-316-000000",
  "priceRange": "€€",
  "servesCuisine": ["Styrian","Austrian"],
  "menu": "https://www.example.com/menu",
  "acceptsReservations": "https://www.example.com/reservations",
  "address": { "@type": "PostalAddress", "streetAddress": "Hauptplatz 1", "postalCode": "8010", "addressLocality": "Graz", "addressRegion": "Steiermark", "addressCountry": "AT" },
  "geo": { "@type": "GeoCoordinates", "latitude": 47.0707, "longitude": 15.4395 },
  "openingHoursSpecification": [
    { "@type": "OpeningHoursSpecification", "dayOfWeek": ["Tuesday","Wednesday","Thursday","Friday","Saturday"], "opens": "11:00", "closes": "22:00" }
  ],
  "hasMenu": {
    "@type": "Menu",
    "hasMenuSection": [{
      "@type": "MenuSection", "name": "Main courses",
      "hasMenuItem": [{ "@type": "MenuItem", "name": "Backhendl (fried chicken)", "offers": { "@type": "Offer", "price": "16.90", "priceCurrency": "EUR" } }]
    }]
  },
  "sameAs": ["https://maps.google.com/?cid=XXXX","https://www.tripadvisor.at/xxx","https://www.falstaff.com/xxx"]
}
```

**BlogPosting**:
```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Title",
  "description": "Summary",
  "image": "https://www.example.com/og/article.png",
  "datePublished": "2026-10-01",
  "dateModified": "2026-10-06",
  "author": { "@type": "Person", "name": "First Last", "url": "https://www.example.com/team/first", "jobTitle": "…", "sameAs": ["https://www.linkedin.com/in/xxx"] },
  "publisher": { "@id": "https://www.example.com/#org" },
  "mainEntityOfPage": "https://www.example.com/blog/article"
}
```

**FAQPage** (optional, visible FAQs only):
```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    { "@type": "Question", "name": "How much does X cost?", "acceptedAnswer": { "@type": "Answer", "text": "X costs from €49 per month …" } }
  ]
}
```

**BreadcrumbList**:
```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://www.example.com/" },
    { "@type": "ListItem", "position": 2, "name": "Services", "item": "https://www.example.com/services" }
  ]
}
```

SaaS: `SoftwareApplication` with `offers` (EUR), `aggregateRating` only with real, visible reviews.
Validate: Rich Results Test, validator.schema.org, GSC reports.

**Entity consistency**: name, positioning sentence, address, phone (NAP) identical across website, GBP, Apple Business, Bing Places, WKO Firmen A–Z, Herold, FirmenABC, LinkedIn, social. Wikidata only when genuinely notable, neutral and sourced.

---

## 4. Off-site / GEO

AI recommends what others write about a brand.
- **Earned media**: regional press (e.g. Kleine Zeitung, meinbezirk.at), trade media, podcasts, partner/customer sites, independent comparison articles. Unlinked mentions count.
- **Platform bias** (each platform uses different sources; URL overlap only ~11–18 %):
  - ChatGPT: Wikipedia, Reddit, major media, LinkedIn; strong freshness preference.
  - Google AIO/AI Mode: YouTube, Reddit, Facebook, LinkedIn, Yelp, GBP.
  - Perplexity: Reddit, YouTube, LinkedIn, G2.
  - Restaurants/travel in general: Tripadvisor is cited extremely often.
- **YouTube**: explainer/demo/tour videos with chapters and transcripts.
- **Communities**: genuine contributions, no astroturfing (spam policy "inauthentic mentions", applies to AI features since 2026-05-15).
- **Reviews**: collect continuously (no incentives, no staff quotas), reply to all.
- **Own data**: surveys, benchmarks, price overviews → citable primary source.
- **Positioning sentence** identical everywhere.
- **Preferred Sources** (blogs/publishers): add the "Add as preferred source" button (Search Central docs; button since 08/2026).

---

## 5. Local SEO (Austria)

- **GBP = the source in AI Mode/AIO** (google.com via Business Profiles is the second most-cited domain in AI Mode; GBP is the largest single source of local AI answers).
- **GBP changes**: Q&A removed (11/2025) → the AI "Ask" feature in Maps answers from the profile + reviews ⇒ services, description, attributes and reviews must carry the answers. AI description suggestion only after review. Managing GBP in Gemini works only with a personal Gmail account, not Workspace. Video verification: Maps app, ≥ 30 s uncut, showing street/sign/access.
- **GBP checklist**: exact primary category (top factor per Whitespark 2026), secondary categories, description, opening hours incl. holidays, attributes, services/menu with prices, regular real photos (newest are prioritized), posts, reservation link, WhatsApp/contact, replies to all reviews.
- **Reservations**: Reserve with Google in Austria via partners (e.g. Mozrest, TheFork). Agentic booking in AI Mode only in the US/UK, not the EU.
- **EU/DMA**: in the EEA there are separate result units for aggregators (directories with an approved POI feed) and suppliers (supplier unit). Since 2026-09-18 also for **local businesses** (previously hotels, flights, products). Businesses need no data beyond what Google can crawl → keep website + GBP clean, strengthen direct booking.
- **Apple Business** (replaced Business Connect on 2026-04-14) → Apple Maps/Siri (Siri uses Gemini since iOS 27).
- **Bing Places** (new at bing.com/forbusiness, import from Google) → Copilot.
- **Austrian directories**: Herold, WKO Firmen A–Z, FirmenABC (top 3), plus 15–20 listings with identical NAP; restaurants also Tripadvisor, Falstaff, Gault&Millau, Graz Tourismus, TheFork.
- One page per location with NAP, map, directions, local content + LocalBusiness schema.

---

## 6. Commerce & agent readiness

- **Google**: clean Merchant Center (feed + Product schema, shipping/return policies at organization level). UCP (checkout in AI Mode/Gemini, `/.well-known/ucp`) not yet available in DACH → monitor.
- **ChatGPT Shopping**: OpenAI product feed spec (`is_eligible_search`, required fields title, description, url, brand, availability, image_url, price, target_countries …). Shopify merchants are included automatically via Shopify Catalog. Instant Checkout was scaled back in 03/2026 → discovery matters, checkout stays with the shop.
- **ChatGPT Ads**: since 08/2026 also in DE/AT (Free/Go users); OAI-AdsBot crawls landing pages → do not block it if ads are planned.
- **NLWeb, WebMCP, MCP for websites**: no proven benefit for SMBs → monitor, do not sell.
- **Agent UX**: semantic HTML, clear forms with labels, no overlays intercepting clicks, no back-button hijacking (spam policy since 2026-06-15).

---

## 7. Legal (Austria/EU)

1. **Consent Mode v2**: mandatory for Google Ads/remarketing in the EEA. In Austria prefer **Basic** (tags load only after consent).
2. **Analytics**: GA4 carries legal risk (Austrian DSB 2022; the EU-US DPF is being challenged at the CJEU). Low risk: self-hosted Matomo or Plausible (EU), cookieless, IP truncated.
3. **EU AI Act Art. 50** (since 2026-08-02): label chatbots as AI; label deepfakes (AI images/videos of real people/places/events); label AI-generated text on matters of public interest, unless it has been editorially reviewed by a human with named responsibility. Ordinary marketing copy is probably not affected (unconfirmed).
4. **Austrian Accessibility Act (BaFG)** (since 2025-06-28): B2C sites with purchase/booking; micro-enterprises (< 10 employees and ≤ €2 m) are exempt; accessibility statement required; EN 301 549. Side effect: better SEO.
5. **Legal notice (Impressum)**: § 5 ECG (name, address, contact, VAT ID, chamber, supervisory authority, professional rules), § 14 UGB (company register number, register court), § 25 MedienG (disclosure). Template: WKO sample.

Note to clients: not legal advice; when in doubt, consult a lawyer/WKO.

---

## 8. Measurement & monitoring

**Google Search Console**
- "Web" performance report: clicks from AIO/AI Mode are included, mixed in.
- **Search Generative AI performance** (worldwide since 2026-08-31, data from 2026-05-18): impressions only, by page/country/device/time – no clicks, no prompts.
- Branded-query filter, query groups, annotations (log deploys/updates), hourly data, AI-assisted report configuration, "Multimodal" filter (Lens).

**Bing Webmaster Tools → AI Performance**: citations, cited pages, grounding queries (Copilot/Bing AI).

**GA4/Matomo**: dedicated "AI Assistants" channel, referrer regex
`chatgpt\.com|openai|perplexity|claude\.ai|gemini\.google|copilot\.microsoft|bing\.com/chat|meta\.ai|chat\.mistral`

**Prompt tracking (method)**
- 30–100 prompts per client, clustered by intent (brand, category "best X in Graz", problem, comparison, price).
- 5–10 runs per prompt over several days, logged out/no personalization, per platform (ChatGPT, Gemini, AI Mode, Copilot, Perplexity, Claude).
- Metrics: visibility % (mentioned in X of N runs), cited/linked %, correctness, share of voice vs. 3 competitors. No positions.
- Tools (entry price/month, 10/2026): Otterly ~$29, Peec AI ~$99, Scrunch ~$300, Profound ~$499, Ahrefs Brand Radar ~$699, Semrush AI Toolkit ~$745.
- Server logs: AI bot hits and 404 rate monthly (1.1).

**Benchmarks for context**
- CTR position 1 with AIO 1.6 % vs. 3.9 % without (Ahrefs 02/2026).
- Cited as an AIO source: +120 % clicks vs. not cited, but −38 % vs. queries without AIO (Seer 04/2026).
- Pew: with an AI summary 8 % click instead of 15 %.
→ KPIs beyond clicks: impressions in AI features, mentions, conversions from AI referrals, branded search volume.

---

## 9. Google update chronology (for root-cause analysis)

| Update | Period |
|---|---|
| Core | 2025-03-13 – 2025-03-27 |
| Core | 2025-06-30 – 2025-07-17 |
| Spam | 2025-08-26 – 2025-09-22 |
| Core | 2025-12-11 – 2025-12-29 (since then, officially also small, unannounced core updates) |
| Discover core (EN/US first) | 2026-02-05 – 2026-02-27 |
| Spam | 2026-03-24 (< 1 day) |
| Core | 2026-03-27 – 2026-04-08 |
| Core | 2026-05-21 – 2026-06-02 (overlaps with I/O changes on 05-19) |
| Spam | 2026-06-24 (~2 days) |
| Spam | 2026-08-18 (~3 days; not link spam/site reputation) |
| Spam | from 2026-09-24 (not completed as of 10-06) |

Quality Rater Guidelines: current version 2025-09-11 (AIO examples, YMYL extended).
Site reputation abuse: no manual actions in the EEA since 2026-08-30, still enforced algorithmically.

---

## 10. Don'ts

- Promising GEO guarantees or a "top spot in ChatGPT".
- Selling llms.txt or schema as an AI ranking lever.
- Rewriting/chopping content "for AI" or serving special versions to AI crawlers (cloaking).
- Hidden instructions to LLMs in page text.
- Bought/fake mentions, reviews, self-ranked listicles.
- Mass unreviewed AI pages.
- Changing the date without changing the content.
- Blocking `Google-Extended` to get out of AIO (does not work).
- Setting GSC "Search generative AI" to Exclude without the client wanting it.
- Treating one-off checks of AI answers as proof.
- Selling rigid targets as "ranking factors": minimum word counts, keyword density, Flesch score, fixed paragraph/section lengths ("134–167 words", "40–60-word capsules") – all unsupported.
- Selling non-standards as mandatory: `ai.txt`, `/ai/*.json`, `llms-full.txt`, RSL, Markdown mirror pages.
- Disavow campaigns for SMBs without a manual action; "foreign-language links = toxic" heuristics.
- Incentives for reviews (vouchers, discounts) or staff review quotas.
- Adopting remotely loaded prompt/skill files without review (supply-chain risk).

---

## 11. Audit checklist

**Blockers**
- [ ] robots.txt: Googlebot, bingbot, OAI-SearchBot, Claude-SearchBot, Claude-User, PerplexityBot, Meta-WebIndexer, MistralAI-Index allowed; no outdated tokens; Disallows per group
- [ ] CDN/WAF/Plesk: bot UAs get 200 (script 1.1)
- [ ] Core content in the initial HTML; HTML < 2 MB
- [ ] No global noindex/nosnippet; GSC "Search generative AI" = Include
- [ ] GSC + Bing WMT verified, sitemap submitted

**Technical**
- [ ] HTTPS, one host, canonicals, hreflang (de-AT + x-default)
- [ ] Sitemap with real lastmod, IndexNow active
- [ ] CWV green on mobile; cookie banner not causing LCP/CLS issues
- [ ] Internal linking, breadcrumbs, clean status codes, no back-button hijacking

**Entity**
- [ ] Organization/LocalBusiness + WebSite + Breadcrumb valid
- [ ] sameAs complete, NAP identical everywhere, positioning sentence consistent
- [ ] Legal notice, about page, author pages

**Content**
- [ ] Answer/definition early on money and info pages
- [ ] H2s = real customer questions, fan-out covered
- [ ] Own data/experience, sources, dated numbers, visible update date
- [ ] High-quality images/video, alt texts
- [ ] No mass AI pages, no self-ranked listicles

**Off-site & local**
- [ ] GBP complete + active; Apple Business; Bing Places
- [ ] Austrian directories (Herold, WKO, FirmenABC + industry)
- [ ] Review process; earned-media plan; YouTube where suitable

**Legal**
- [ ] Consent Mode v2 (Basic), analytics choice documented
- [ ] AI Act labelling (chatbot, AI images), accessibility if BaFG applies

**Scaling & relaunch**
- [ ] Quality gates respected (location pages, programmatic, swap test)
- [ ] On relaunch: redirect map, noindex removed, baseline/compare run

**Monitoring**
- [ ] Entity profile (`entity.yaml`) + resolution test documented
- [ ] Form field "How did you hear about us?" with an AI option
- [ ] Deploy gate (`geo_audit.py --compare`) in CI/systemd
- [ ] Prompt set + baseline (5–10 runs), competitors and control group defined
- [ ] GA4/Matomo "AI Assistants" channel
- [ ] GSC GenAI report + Bing AI Performance monthly
- [ ] Bot logs monthly

---

## 12. Tools & tool stack

**Own scripts** (skill **seo-geo-tools**, Python stdlib only):
- `geo_audit.py` – raw-HTML audit: robots.txt per RFC 9309 (bot matrix per token, 4xx = allow all, 5xx = disallow all), UA status codes (indication of CDN/WAF blocks), noindex/nosnippet/max-snippet, canonical, raw-HTML word count + SPA suspicion, 2 MB limit, title/description/H1/lang/hreflang, JSON-LD (parseable, types, placeholders), soft 404, sitemap lastmod, llms.txt (info only). **Deploy gate**: `--save-baseline` / `--compare` → exit 2 on critical drift (new noindex, canonical changed, bots newly blocked, status ≥ 400).
- `prompt_report.py` – analysis of prompt-tracking CSVs: mentioned/cited/recommended/advised against per platform and cluster with 95 % intervals, share of voice, most-cited domains, before/after and difference-in-differences against a control group.

**Second opinion / CI**: `geolint` (open source, MIT; 52 rules, 51 crawler tokens, SARIF output for GitHub code scanning) – treat its llms.txt findings as warnings only. Lighthouse "Agentic Browsing" category as an agent-UX lab value (no ranking/citation relevance).

**Data connections (MCP)**:
| Purpose | Tool | Note |
|---|---|---|
| Search Console | `mcp-gsc` (open source) | Quick wins (pos. 4–20, many impressions, low CTR), cannibalization, batch URL inspection. **Requesting indexing is not possible via API** (Indexing API only for JobPosting/BroadcastEvent). |
| Bing | Bing Webmaster MCP | Sitemaps, IndexNow, crawl stats. The AI Performance report (Copilot citations) currently has no API → export manually. |
| Keywords/SERP | DataForSEO MCP (official) | **Austria: location_code 2040, language `de`**; Germany for comparison: 2276. Pay per query → get budget approval first. |
| AI visibility | Peec AI (Berlin, DACH-ready, MCP), Otterly (cheap) | For clients with budget; otherwise own tracking (section 13). |

License note when borrowing from open-source skills: claude-seo (MIT), marketingskills (MIT), seo-geo-claude-skills (Apache-2.0), FLOW prompts (CC BY 4.0, attribution) – only ideas were adopted, no text.

---

## 13. Measurement protocol & prompt tracking

**Four levels with different latency** – report each separately:
1. **Crawl access** (checkable immediately): robots/WAF/rendering → `geo_audit.py`, server logs.
2. **Retrievability** (minutes; proxy only): live fetch with the page URL in the prompt. Only counts if a `Claude-User`/`Perplexity-User`/`ChatGPT-User` hit appears in the log.
3. **Appearing without the URL in the prompt** (days–weeks): prompt tracking.
4. **Rankings/traffic/leads** (weeks–months): GSC, Bing, analytics, CRM.

**Rules**
- Prompt set: 30–100 prompts per client, clustered by intent (brand, category, problem, comparison, price, local). Phrase them like real customers (in the customers' language, e.g. Austrian German).
- 3–10 runs per prompt × platform, over several days, logged out. State the method (real interface vs. API with web search = *proxy*).
- **Control group**: also measure prompts/pages without the intervention; report the difference (difference-in-differences, `prompt_report.py --split`).
- **One intervention per measurement window**, window fixed in advance (e.g. 4 weeks). Interpret only from ≥ 30 runs per group and period.
- **Visibility ladder** instead of one number: retrieved → cited → mentioned → **recommended** – plus **advised against** and sentiment; additionally the *correctness* of facts about the brand.
- CSV columns: `date, platform, prompt_id, cluster, group, run, mentioned, cited, recommended, against, sentiment, correct, cited_urls, competitors`.

**Close the attribution gap**: only a fraction of AI-influenced visits arrive as recognizable referrals. Add a required field **"How did you hear about us?"** with the option "AI assistant (ChatGPT, Gemini …)" and an optional free-text **"What did you ask?"** to contact/booking forms → this yields real prompts for the prompt set.

**Format volatility**: platforms change source preferences abruptly. Example (Peec AI, single analysis, weak evidence): after GPT-5.6 (08/2026), the share of retrieved listicles fell from 15.5 % to 8.2 % while product pages rose (ChatGPT increasingly uses `site:` searches on manufacturer domains). → Keep your own product, pricing, service and specification pages complete, crawlable and factual; do not bet on one content format.

---

## 14. Content rubric (own, evidence-oriented)

Score per item: **pass 2 · partial 1 · fail 0**. Score = weighted sum / maximum × 100. **Veto items (V)**: on fail, score capped at 60; 2 or more vetoes = "blocked". A quality-assurance heuristic, **not a ranking factor**.

| ID | Item | Check |
|---|---|---|
| A1 | Core statement early | Answer/definition within the first ~100 words, self-explanatory |
| A2 | Coverage | What · for whom · how · price/cost · area/availability · **who it is not for** · process · alternatives |
| A3 | Information gain | Own data, photos, experiences, examples – not interchangeable |
| A4 | Sourced numbers | Every statistic with source + year; own numbers with collection date |
| A5 (V) | Consistency | No contradictory details (prices, hours, facts) across page/site/GBP |
| A6 | Real freshness | Visible update date matches an actual content change |
| S1 | Structure | H1 = topic; H2s = real customer questions/subtopics; logical hierarchy |
| S2 | Data as table/list | Comparisons/facts presented as HTML tables/lists |
| S3 (V) | In raw HTML | Main content visible without JS (`geo_audit.py`) |
| S4 | Linking | ≥ 3 internal links to important pages; onward links from the page |
| T1 | Named responsibility | Author/business with qualifications, photo, contact |
| T2 | Legal | Legal notice, privacy policy, accessibility statement if required |
| T3 (V) | Disclosure | Advertising/affiliate/sponsorship labelled (§ 26 MedienG), AI labelling where required (AI Act Art. 50) |
| T4 | Proof of quality | Genuine reviews, references, certificates, press |
| T5 | Tone | Informational content factual, not promotional |
| T6 (V) | No clickbait | Title/H1 deliver what they promise |

Weights per page type (factor per item; unlisted = 1):
- **Service/local page**: A1 ×2, A2 ×2, T1 ×1.5, T4 ×1.5
- **Restaurant**: A2 ×2 (menu, prices, hours, reservations, location), A5 ×2, T4 ×1.5, A3 ×1.5 (photos)
- **Guide/blog**: A3 ×2, A4 ×2, A1 ×1.5, A6 ×1.5
- **SaaS/product**: A2 ×2 (incl. pricing, integrations, limitations), A4 ×1.5, S2 ×1.5

---

## 15. Entity profile & consensus

**Client entity profile** (store per client at `kunden/<client>/entity.yaml`):
```yaml
name: "Restaurant Example"
legal_name: "Example Gastronomie GmbH"
also_known_as: ["Gasthaus Example", "Example Graz"]
positioning: "Styrian inn in Graz-Lend with regional cuisine and a beer garden."  # identical everywhere
description_short: "…"          # max. 160 characters
category: "Restaurant"            # = GBP primary category
nap: { street: "…", zip: "8020", city: "Graz", phone: "+43 316 …" }
website: "https://www.example.com"
same_as: [GBP-URL, Apple-Business, Bing-Places, Herold, WKO, Tripadvisor, Falstaff, Instagram, Facebook]
not_for: ["Catering for large events"]   # negative scoping
ai_resolution:                    # result of the resolution test
  chatgpt: { status: partial, last_verified: 2026-10-07, note: "confused with …" }
  gemini:  { status: recognized, last_verified: 2026-10-07 }
  aimode:  { status: recognized, last_verified: 2026-10-07 }
  perplexity: { status: unrecognized, last_verified: 2026-10-07 }
```

**Entity resolution test** (quarterly, 3 runs per platform; ask in the customers' language): "What is {brand}?", "Who is behind {brand}?", "Where is {brand} and when is it open?", "{brand} reviews", "{brand} or {competitor}?", "Best {category} in {city}". Status: *recognized* / *partial* / *unrecognized* / *confused*. Wrong facts → find the source of the misinformation (often outdated directory data) and correct it there.

**Consensus workflow**: all profiles (website, GBP, Apple, Bing, WKO, Herold, LinkedIn, industry portals) describe the same segment with the same positioning sentence. When repositioning, update **off-site first**, then the website. Do not suppress criticism in aggregators/reviews; reply factually and fix the cause.

---

## 16. Playbooks

### 16.1 AI Overview recovery (CTR drop with stable impressions)
1. GSC: queries with CTR down 20 % or more while impressions are down at most 10 % (28 days vs. previous period or previous year). Cross-check with the GSC "Search Generative AI performance" report (impressions per page).
2. Check each query's SERP manually (logged out, Austria) and segment:
   - **A** AIO cites us → sharpen snippet/title around the reason to click, strengthen the brand; accept the rest.
   - **B** AIO cites others, not us → compare the cited pages: coverage (A2), information gain, freshness, authority, rendering.
   - **C** Competitors/aggregators cited → off-site (mentions, directories, reviews).
   - **D** Intent has shifted → change page type (16.4).
3. One intervention per segment, review after 7 / 14 / 28 days. Goal: clicks/leads, not just CTR.

### 16.2 Content decay & refresh
Decay score (0–100) = traffic loss 30 % + position loss 25 % + CTR loss 15 % + age since last real update 15 % + displacement by competitors 15 %.
0–20 healthy · 21–40 watch · 41–60 refresh this month · 61–80 major rework · 81–100 rewrite, merge or remove.
**Date rule**: > 50 % new content → new publication date; 20–50 % → "Updated on"; < 20 % → keep the date.
**Removal matrix**: topic relevant + a better page exists → 301 + merge · useful but no search value → keep, `noindex` · outdated, worthless, no links → 410 · has backlinks → 301 to the closest related page.

### 16.3 Internal linking
Structure score: 100 − 10 per orphan page − 5 per important page deeper than 3 clicks. Targets: 0 orphans, important pages ≤ 3 clicks, new content linked within 48 h, every important page ≥ 3 incoming internal links.
Link brief per suggestion: target page · source page · exact location (paragraph) · anchor text · ready-to-insert sentence.

### 16.4 SXO & cannibalization
- **Page-type consensus**: classify the top 10 for the target query by page type (service page, guide, list, product, directory, tool). > 60 % one type = clear intent → build that type; 40–60 % mixed; a mismatch is the most common cause of "good content doesn't rank".
- **SERP overlap clustering** (identical URLs in the top 10 of two keywords): 7–10 → one page · 4–6 → cluster (pillar + subpages) · 2–3 → separate pages, cross-linked · 0–1 → independent.
- Pillar ≤ 2 clicks from the home page.

### 16.5 Quality gates when scaling
- **Location/city pages**: warning from 30, stop at 50, unless every page has ≥ 60 % unique content with real local substance (team, references, directions, local prices). **Swap test**: swap the city name – if the page still makes sense, it is a doorway page.
- **Programmatic SEO**: warning from 100, stop at 500 pages without sign-off; < 40 % unique content = thin; publish in batches of 50–100 with an indexing check; 5–10 % human sampling. Data quality: own data > product data > user data > licensed > public data.

### 16.6 Relaunch / migration
1. Crawl the old site (all URLs, titles, canonicals, status), export GSC top pages and pages with backlinks; `geo_audit.py --save-baseline`.
2. 1:1 redirect map (301), no blanket redirects to the home page; avoid chains.
3. Staging with `noindex` + password; **remove noindex/robots block at launch** (most common relaunch accident).
4. Launch: spot-check redirects, resubmit sitemaps (GSC + Bing + IndexNow), add a GSC annotation; use the Change of Address tool for domain moves.
5. `geo_audit.py --compare` against the baseline; check GSC daily for 2 weeks (indexing, 404s, clicks), then weekly. Canonical re-evaluation can take up to ~2 weeks.

### 16.7 Comparison & alternative pages
Formats: "{competitor} alternative", "{A} vs {B}", "Alternatives to {X}". Rules: facts with a date ("as of DD.MM.YYYY"), "not stated/not listed" instead of "doesn't have it", facts separated from assessment, name your own weaknesses fairly. **No self-ranked "best X" lists** with yourself at #1. Austria: comparative advertising is only permitted if objective, verifiable and not misleading (§ 2a UWG) – get legal review when in doubt.

### 16.8 GBP score (local)
Per field 0 (missing) / 1 (present) / 2 (complete, current): primary category · secondary categories · name without keyword stuffing · address/service area · phone · website link (matching page, with UTM) · opening hours · special hours/holidays · description · opening date · attributes · services/products with prices · menu · booking/reservation link · photos (exterior, interior, team, products; continuously new) · logo/cover · videos · posts (last 30 days) · review count · review average · review reply rate · reply time · messaging/WhatsApp · consistency with website/directories.
Restaurant: menu ×2, photos/reservations/attributes ×1.5. Bands: ≥ 90 % very good · 75–89 good · 50–74 gaps · < 50 critical. (Q&A no longer exists.)

### 16.9 YouTube (where it fits the client)
Title as a concrete question/task · corrected subtitles (not just auto-generated) · chapters · description with the key message in the first 2 lines + links · pinned comment with a summary · embed the video on the matching website page (+ `VideoObject`, transcript as text).

### 16.10 Directory tracker (CSV)
`directory, listing_url, status (open/submitted/live), nap_identical (yes/no), category, link (dofollow/nofollow/none), last_checked, note` – Austrian starter set: Google, Apple Business, Bing Places, Herold, WKO Firmen A–Z, FirmenABC, industry association; restaurants also Tripadvisor, Falstaff, TheFork, Graz Tourismus. Get client sign-off before every submission.

---

## 17. Monitoring alerts & deploy gate

| Signal | Warning | Critical | Emergency |
|---|---|---|---|
| Organic non-brand sessions (week over week) | −20 % | −35 % | −50 % |
| Important keywords (top 10) | −3 positions | −5 / out of top 10 | out of top 20 |
| Indexed pages (GSC) | −10 % | −25 % | −50 % |
| 5xx errors per day (logs) | > 1 | > 5 | > 20 |
| AI bot hits/month (logs) | −30 % | −60 % | 0 |
| AI visibility (prompt set, "mentioned") | −10 pp | −20 pp | – |
| `geo_audit.py --compare` | – | exit 2 | – |

Suppression: 24 h cooldown per alert, weekends/holidays +20 % tolerance, recalibrate for 2–4 weeks after Google updates.
**Deploy gate**: baseline before every deploy, comparison after the deploy (CI templates in the seo-geo-tools skill). Exit 2 → check/roll back the deploy.

---

## 18. Keeping current

Before every major audit, check via web search: status.search.google.com, developers.google.com/search/updates (docs changelog), Search Central Blog, OpenAI/Anthropic/Perplexity/Meta/Mistral bot docs, Bing Webmaster Blog, Search Engine Roundtable. Update this playbook when things change.

Primary sources:
- https://developers.google.com/search/docs/fundamentals/ai-optimization-guide
- https://developers.google.com/search/docs/appearance/ai-features
- https://developers.google.com/search/updates
- https://developers.google.com/search/docs/essentials/spam-policies
- https://developers.google.com/search/docs/fundamentals/using-gen-ai-content
- https://support.google.com/webmasters/answer/16908024 (Search generative AI control)
- https://developers.google.com/search/blog/2026/06/gen-ai-performance-reports
- https://developers.google.com/crawling/docs/changelog
- https://status.search.google.com
- https://developers.openai.com/api/docs/bots
- https://developers.openai.com/commerce/product-feeds/spec
- https://support.claude.com/en/articles/8896518
- https://developers.facebook.com/docs/sharing/webmasters/web-crawlers
- https://docs.mistral.ai/robots
- https://www.bing.com/webmasters
- https://web.dev/articles/vitals
- https://web.dev/articles/ai-agent-site-ux
- https://arxiv.org/abs/2607.14035 (GEO survey, lead evidence source)
- https://arxiv.org/abs/2311.09735 (Princeton GEO)
- https://whitespark.ca/local-search-ranking-factors/
- https://www.wko.at/oe/internetrecht/das-korrekte-website-impressum-eu.pdf

Cross-checked against public skill collections (2026-10-07; only ideas adopted, outdated claims discarded): AgriciDaniel/claude-seo (MIT), coreyhaines31/marketingskills (MIT), aaron-he-zhu/seo-geo-claude-skills (Apache-2.0), Bright Data seo-audit (MIT), infrasity-labs/dev-gtm-claude-skills, geolint, Auriti-Labs/geo-optimizer-skill, seo-skills/seo-audit-skill (SEOmator).
