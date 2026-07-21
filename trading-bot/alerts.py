"""Alerting. Fires on: circuit breaker, emergency lock written, bot start/stop, order
rejected, unhandled error. Transport is configurable via .env (webhook URL); no-ops
silently if unconfigured, so the bot never crashes because alerting failed. Rate-limited
so one bad loop can't send hundreds of messages."""
import json
import time

import settings

_last_sent = {}
_MIN_INTERVAL = 60  # seconds between identical alert keys


def send(key, text):
    """key = dedupe/rate-limit bucket, text = message. Returns True if actually sent."""
    now = time.time()
    if now - _last_sent.get(key, 0) < _MIN_INTERVAL:
        return False
    _last_sent[key] = now
    url = settings.env("ALERT_WEBHOOK_URL")
    if not url:
        return False  # unconfigured -> silent no-op (by design)
    try:
        import requests
        requests.post(url, json={"content": f"[trading-bot] {text}"}, timeout=10)
        return True
    except Exception:
        return False  # alerting must never take the bot down


def log_event(kind, detail=""):
    """Append every alert-worthy event to the journal regardless of transport."""
    line = json.dumps({"ts": time.time(), "type": "alert", "kind": kind, "detail": detail})
    with open(settings.JOURNAL, "a", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    log_event("selftest", "alerts module ok")
    assert not send("selftest", "no webhook configured -> False")
    print("alerts self-check ok (no-op without ALERT_WEBHOOK_URL)")
