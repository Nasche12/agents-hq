"""Central configuration. Values come from config.json (user-editable, 0 tokens),
secrets ONLY from .env (never in the repo, never in chat). Read-only at runtime."""
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO_ROOT = BASE.parent
# Plesk serves httpdocs/ statically, so the browser fetches trading.json as a FILE there
# (like the other agents mirror status.json). The bot writes this mirror every cycle.
PUBLIC_TRADING = REPO_ROOT / "httpdocs" / "trading.json"
STATE_DIR = BASE / "state"
CACHE_DIR = BASE / "data_cache"
LOG_DIR = BASE / "logs"
for d in (STATE_DIR, CACHE_DIR, LOG_DIR):
    d.mkdir(exist_ok=True)

JOURNAL = STATE_DIR / "journal.jsonl"        # one line per trade/skip (analytics)
RISK_STATE = STATE_DIR / "risk_state.json"   # daily/weekly P&L + peak (survives restart)
POSITIONS = STATE_DIR / "positions.json"     # open positions + pending orders
ORDERS = STATE_DIR / "orders.json"           # recent orders (detail for the trade cards)
SIGNALS = STATE_DIR / "signals.json"         # per-symbol HMM signal + target exposure
HEARTBEAT = STATE_DIR / "heartbeat.json"     # liveness signal for server/dashboard
EQUITY_HISTORY = STATE_DIR / "equity_history.jsonl"  # real account balance snapshots over time
LOCK_FILE = STATE_DIR / "EMERGENCY.lock"     # -10% kill switch: delete by hand to resume
DASHBOARD_EXPORT = STATE_DIR / "dashboard.json"  # what the Node trading tab reads

_REGIME_NAMES = {
    3: ["bear", "neutral", "bull"],
    4: ["crash", "bear", "bull", "euphoria"],
    5: ["crash", "bear", "neutral", "bull", "euphoria"],
    6: ["crash", "bear", "neutral", "bull", "euphoria", "mania"],
    7: ["crash", "bear", "weak", "neutral", "strong", "bull", "euphoria"],
}

# One fixed colour per regime -- identical in the backtester output and the dashboard tab.
REGIME_COLORS = {
    "crash": "#c0392b", "bear": "#e67e22", "weak": "#d4a017",
    "neutral": "#7f8c8d", "strong": "#27ae60", "bull": "#2ecc71",
    "euphoria": "#16a085", "mania": "#8e44ad",
}


def regime_labels(n):
    """Names for n regimes, sorted by mean return (index 0 = weakest)."""
    return _REGIME_NAMES.get(n, [f"r{i}" for i in range(n)])


def load_config():
    with open(BASE / "config.json", encoding="utf-8") as f:
        return json.load(f)


def env(key, default=None):
    """Secret/setting from .env or the process environment. Never logged."""
    _load_dotenv()
    return os.environ.get(key, default)


_DOTENV_LOADED = False


def _load_dotenv():
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    # trading-bot/.env wins; repo-root .env is a fallback so secrets can stay centralized.
    for f in (BASE / ".env", BASE.parent / ".env"):
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'").strip()  # tolerate quoted/padded values
            os.environ.setdefault(k.strip(), v)
