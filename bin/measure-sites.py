#!/usr/bin/env python3
"""
Misst alle Sites aus config/sites.json:
- HTTP-Status, Antwortzeit, TLS-Ablauf
- Content-Check (expect), Assets (images), Health-Endpoint (db)
Gibt JSON mit allen Messwerten aus.
"""

import json
import subprocess
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
import time

CONFIG_PATH = Path(__file__).parent.parent / "config" / "sites.json"


def run_curl_metric(url, timeout=20):
    """
    curl -sS -o /dev/null -w '%{http_code} %{time_total} %{url_effective}'
    Gibt Tupel: (http_code, time_seconds, effective_url) oder (None, None, None) bei Fehler
    """
    try:
        result = subprocess.run(
            [
                "curl", "-sS", "-o", "/dev/null",
                "-w", "%{http_code} %{time_total} %{url_effective}",
                "-L", "--max-time", str(timeout),
                url
            ],
            capture_output=True, text=True, timeout=timeout+5
        )
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            http = int(parts[0])
            time_s = float(parts[1])
            url_eff = parts[2] if len(parts) > 2 else url
            return http, time_s, url_eff
    except Exception as e:
        print(f"ERROR curl_metric {url}: {e}", file=sys.stderr)
    return None, None, None


def get_ssl_days_left(url, timeout=20):
    """
    Extrahiert TLS-Ablaufdatum via openssl s_client.
    Berechne Resttage. Bei Fehler: None
    """
    try:
        # Extrahiere Host und Port aus URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or "localhost"
        port = parsed.port or 443

        # openssl s_client gibt das Zertifikat aus
        result = subprocess.run(
            [
                "openssl", "s_client", "-connect", f"{hostname}:{port}",
                "-servername", hostname
            ],
            capture_output=True, text=True, timeout=timeout+5, stdin=subprocess.DEVNULL
        )

        output = result.stdout + result.stderr

        # Suche nach "NotAfter: ..." Format (das erste ist das Server-Zert)
        # Format: "NotAfter: Aug 12 19:45:53 2026 GMT"
        matches = re.findall(r'NotAfter:\s+(\w+)\s+(\d+)\s+(\d+):(\d+):(\d+)\s+(\d+)\s+GMT', output)

        if matches:
            # Nimm die erste NotAfter (das Server-Zertifikat, nicht das intermediate)
            month_name, day, hour, minute, second, year = matches[0]
            month_map = {'Jan':1, 'Feb':2, 'Mar':3, 'Apr':4, 'May':5, 'Jun':6,
                         'Jul':7, 'Aug':8, 'Sep':9, 'Oct':10, 'Nov':11, 'Dec':12}
            month = month_map.get(month_name, 1)
            expire_date = datetime(int(year), month, int(day), int(hour), int(minute), int(second))
            days_left = (expire_date - datetime.utcnow()).days
            return max(0, days_left)

    except Exception as e:
        print(f"ERROR ssl_days {url}: {e}", file=sys.stderr)

    return None


def fetch_html(url, timeout=20):
    """curl -sS -L --max-time 20 <url> – gibt HTML zurück oder None"""
    try:
        result = subprocess.run(
            ["curl", "-sS", "-L", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout+5
        )
        if result.returncode == 0:
            return result.stdout
    except Exception as e:
        print(f"ERROR fetch_html {url}: {e}", file=sys.stderr)
    return None


def check_expect(html, expect_string):
    """Prüft, ob expect_string im HTML vorkommt. True/False/None"""
    if not expect_string or not html:
        return None
    return expect_string in html


def extract_images_from_html(html, base_url):
    """
    Extrahiert alle <img src="..."> aus HTML.
    Konvertiert relative Pfade zu absoluten URLs.
    Gibt Liste [url1, url2, ...] zurück.
    """
    images = []
    if not html:
        return images

    # Einfaches Regex für <img src="...">
    matches = re.findall(r'<img[^>]+src=["\'](.*?)["\']', html, re.IGNORECASE)
    for src in matches:
        if src.startswith('http'):
            images.append(src)
        elif src.startswith('//'):
            images.append('https:' + src)
        elif src.startswith('/'):
            # Absolute Pfad – anhängen an base_url ohne Pfad
            if base_url.endswith('/'):
                images.append(base_url.rstrip('/') + src)
            else:
                images.append(base_url + src)
        else:
            # Relativer Pfad
            if base_url.endswith('/'):
                images.append(base_url + src)
            else:
                images.append(base_url + '/' + src)

    return images


def check_image(img_url, timeout=20):
    """
    curl -sS -o /dev/null -w '%{http_code} %{content_type} %{size_download}' <img_url>
    OK nur bei: HTTP 200 AND content_type startet mit "image/" AND size_download > 0
    Gibt True (ok) oder False (kaputt) zurück.
    """
    try:
        result = subprocess.run(
            [
                "curl", "-sS", "-o", "/dev/null",
                "-w", "%{http_code} %{content_type} %{size_download}",
                "--max-time", str(timeout),
                img_url
            ],
            capture_output=True, text=True, timeout=timeout+5
        )
        parts = result.stdout.strip().split()
        if len(parts) >= 3:
            http = int(parts[0])
            content_type = parts[1]
            size = int(parts[2])

            if http == 200 and content_type.startswith('image/') and size > 0:
                return True
    except Exception as e:
        print(f"ERROR check_image {img_url}: {e}", file=sys.stderr)

    return False


def check_health(health_url, timeout=20):
    """
    curl -sS -o /dev/null -w '%{http_code}' -L --max-time 20 <health-url>
    OK bei HTTP < 500 (auch 401/403), down bei 5xx/Timeout/DNS-Fehler
    Gibt "ok" oder "down" zurück.
    """
    try:
        result = subprocess.run(
            [
                "curl", "-sS", "-o", "/dev/null",
                "-w", "%{http_code}",
                "-L", "--max-time", str(timeout),
                health_url
            ],
            capture_output=True, text=True, timeout=timeout+5
        )
        try:
            http = int(result.stdout.strip())
            if http < 500:
                return "ok"
            else:
                return "down"
        except ValueError:
            # Keine Zahl – Timeout/DNS-Fehler
            return "down"
    except Exception as e:
        print(f"ERROR check_health {health_url}: {e}", file=sys.stderr)
        return "down"


def measure_site(site_config):
    """
    Misst eine Site vollständig. Gibt Dict mit allen Werten zurück.
    """
    name = site_config.get("name")
    url = site_config.get("url")
    expect_str = site_config.get("expect")
    assets_config = site_config.get("assets")
    health_url = site_config.get("health")

    print(f"Messe {name} ({url})...", file=sys.stderr)

    result = {
        "name": name,
        "url": url,
        "state": "unknown",
        "http": None,
        "ms": None,
        "ssl_days": None,
        "checked": datetime.utcnow().isoformat() + "Z",
        "expect_ok": None,
        "assets": "n/a",
        "db": "n/a",
    }

    # 1. HTTP + Zeit
    http, time_s, url_eff = run_curl_metric(url)
    if http is None:
        # Fehler – Retry nach 10 s
        print(f"  Erste Messung fehlgeschlagen, retry in 10s...", file=sys.stderr)
        time.sleep(10)
        http, time_s, url_eff = run_curl_metric(url)

    if http is None:
        result["state"] = "down"
        result["reason"] = "Startseite nicht erreichbar (HTTP-Fehler/Timeout)"
        print(f"  DOWN: Keine HTTP-Antwort", file=sys.stderr)
        return result

    result["http"] = http
    result["ms"] = int(time_s * 1000)

    # Prüfe HTTP-Status
    if http >= 400:
        result["state"] = "down"
        result["reason"] = f"HTTP {http}"
        print(f"  DOWN: HTTP {http}", file=sys.stderr)
        return result

    # 2. SSL-Tage
    ssl_days = get_ssl_days_left(url)
    result["ssl_days"] = ssl_days
    if ssl_days is not None:
        print(f"  SSL: {ssl_days} Tage", file=sys.stderr)
    else:
        print(f"  SSL: konnte nicht ausgelesen werden", file=sys.stderr)

    # 3. HTML laden
    html = fetch_html(url)
    if html is None:
        result["state"] = "down"
        result["reason"] = "HTML-Fetch fehlgeschlagen"
        print(f"  DOWN: Kein HTML", file=sys.stderr)
        return result

    # 4. Inhalt prüfen (expect)
    if expect_str:
        expect_ok = check_expect(html, expect_str)
        result["expect_ok"] = expect_ok
        if not expect_ok:
            result["state"] = "down"
            result["reason"] = f"expect-String nicht gefunden: '{expect_str}'"
            print(f"  DOWN: expect '{expect_str}' nicht gefunden", file=sys.stderr)
            return result
        print(f"  Inhalt OK: '{expect_str}' gefunden", file=sys.stderr)

    # 5. Bilder prüfen
    if assets_config:
        if assets_config == "auto":
            images = extract_images_from_html(html, url)
            print(f"  {len(images)} Bilder gefunden", file=sys.stderr)
            if len(images) == 0:
                result["assets"] = "n/a"
            else:
                broken_images = []
                for img_url in images:
                    if not check_image(img_url):
                        broken_images.append(img_url)

                if broken_images:
                    result["assets"] = f"{len(broken_images)} kaputt"
                    result["reason"] = f"Kaputte Bilder: {', '.join(broken_images[:3])}"
                    print(f"  WARNING: {len(broken_images)} Bilder kaputt", file=sys.stderr)
                else:
                    result["assets"] = "ok"
                    print(f"  Alle Bilder OK", file=sys.stderr)
        else:
            # Liste von kritischen Pfaden
            if isinstance(assets_config, list):
                broken_images = []
                for path in assets_config:
                    if path.startswith('http'):
                        img_url = path
                    elif path.startswith('/'):
                        img_url = url.rstrip('/') + path
                    else:
                        img_url = url.rstrip('/') + '/' + path

                    if not check_image(img_url):
                        broken_images.append(img_url)

                if broken_images:
                    result["assets"] = f"{len(broken_images)} kaputt"
                    result["reason"] = f"Kaputte Bilder: {', '.join(broken_images)}"
                    print(f"  WARNING: {len(broken_images)} Bilder kaputt", file=sys.stderr)
                else:
                    result["assets"] = "ok"
                    print(f"  Alle kritischen Bilder OK", file=sys.stderr)

    # 6. Health-Endpoint prüfen
    if health_url:
        db_status = check_health(health_url)
        result["db"] = db_status
        print(f"  Backend: {db_status}", file=sys.stderr)
        if db_status == "down":
            result["state"] = "down"
            result["reason"] = "Backend/Health-Endpoint down"
            return result

    # Bestimme finalen Status
    if result["state"] == "down":
        pass  # Bereits gesetzt
    elif result["ms"] and result["ms"] >= 3000:
        result["state"] = "slow"
        print(f"  SLOW: {result['ms']} ms", file=sys.stderr)
    else:
        result["state"] = "ok"
        print(f"  OK", file=sys.stderr)

    # Entferne reason wenn nicht gesetzt
    if "reason" not in result or not result.get("reason"):
        result.pop("reason", None)

    return result


def main():
    if not CONFIG_PATH.exists():
        print(f"ERROR: {CONFIG_PATH} nicht gefunden", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    sites = config.get("sites", [])
    if not sites:
        print("ERROR: Keine Sites in config/sites.json", file=sys.stderr)
        sys.exit(1)

    results = []
    for site in sites:
        measurement = measure_site(site)
        results.append(measurement)

    # Ausgabe als JSON für uptime-record.py
    print(json.dumps(results))


if __name__ == "__main__":
    main()
