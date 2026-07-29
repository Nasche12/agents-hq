"""Central configuration. Values come from config.json (user-editable, 0 tokens),
secrets ONLY from .env (never in the repo, never in chat).

Two layers of config, deliberately separated:
  config.json        the human baseline. Tracked in git -- `git pull` owns this file.
  config.local.json  parameters the research agent learned and promoted. GIT-IGNORED,
                     so the agent can never collide with a deploy pull. Deleting the
                     file is a complete rollback to the human baseline.
A third, in-process layer (config_override) exists purely so the optimizer can evaluate
a candidate parameter set without writing anything to disk."""
import json
import os
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO_ROOT = BASE.parent
# Plesk serves httpdocs/ statically, so the browser fetches trading.json as a FILE there
# (like the other agents mirror status.json). The bot writes this mirror every cycle.
PUBLIC_TRADING = REPO_ROOT / "httpdocs" / "trading.json"
# Per-symbol bars for the trade charts. Kept OUT of trading.json on purpose: the browser
# only needs them when a symbol drawer is opened, and inlining 20 symbols of history
# would roughly triple the payload every dashboard poll.
PUBLIC_PRICES = REPO_ROOT / "httpdocs" / "trading-prices.json"
STATE_DIR = BASE / "state"
CACHE_DIR = BASE / "data_cache"
LOG_DIR = BASE / "logs"
for d in (STATE_DIR, CACHE_DIR, LOG_DIR):
    d.mkdir(exist_ok=True)

CONFIG_FILE = BASE / "config.json"           # human baseline, in git
CONFIG_LOCAL = BASE / "config.local.json"    # agent-promoted overrides, git-ignored
CONFIG_USER = BASE / "config.user.json"      # dashboard/user overrides, git-ignored, HIGHEST wins

JOURNAL = STATE_DIR / "journal.jsonl"        # one line per trade/skip (analytics)
RISK_STATE = STATE_DIR / "risk_state.json"   # daily/weekly P&L + peak (survives restart)
POSITIONS = STATE_DIR / "positions.json"     # open positions + pending orders
ORDERS = STATE_DIR / "orders.json"           # recent orders (detail for the trade cards)
SIGNALS = STATE_DIR / "signals.json"         # per-symbol HMM signal + target exposure
HEARTBEAT = STATE_DIR / "heartbeat.json"     # liveness signal for server/dashboard
EQUITY_HISTORY = STATE_DIR / "equity_history.jsonl"  # real account balance snapshots over time
BOT_STATE = STATE_DIR / "bot_state.json"     # cycles run, trades sent, uptime (24/7 counters)
LOCK_FILE = STATE_DIR / "EMERGENCY.lock"     # -10% kill switch: delete by hand to resume
DASHBOARD_EXPORT = STATE_DIR / "dashboard.json"  # what the Node trading tab reads
PRICES = STATE_DIR / "prices.json"           # per-symbol bars for the trade charts

# --- research / self-improvement loop ---
MEMORY = STATE_DIR / "memory.jsonl"          # every hypothesis ever tested + its verdict
CANDIDATES = STATE_DIR / "candidates.json"   # what the LLM proposed this round (never applied directly)
EVIDENCE = STATE_DIR / "evidence.json"       # the pack the LLM reads (own results, past verdicts)
LEARNING_REPORT = STATE_DIR / "learning_report.json"  # last research run, for the dashboard
NEWS_RISK = STATE_DIR / "news_risk.json"     # market-watch agent verdict: ONE integer 0-3
NEWS_HISTORY = STATE_DIR / "news_history.jsonl"  # step-function log of the external picture (news level + events) over time
INSIGHTS = STATE_DIR / "insights.json"       # current strongest loss/win CONNECTIONS mined from closed trades (24/7)
INSIGHTS_LOG = STATE_DIR / "insights.jsonl"  # dated trail: when each connection first became significant
EXITS_STATE = STATE_DIR / "exits.json"       # per-position peak + cooldown for stop-loss / trailing / scale-out
CONFIG_HISTORY = STATE_DIR / "config_history.jsonl"   # every promotion, with the previous values

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


# ---------------------------------------------------------------- config loading
_FILE_CACHE = {}              # path -> (mtime, parsed)
_RUNTIME_OVERRIDES = {}       # in-process only, set by config_override()


_CACHE_TTL = 1.0          # seconds; backstop against coarse filesystem timestamps


def invalidate_config_cache():
    """Drop the parse cache. MUST be called after writing a config file.

    Reason this is not optional: the cache key includes the file mtime, and many
    filesystems quantise timestamps (often to a millisecond or worse). Two writes inside
    the same tick therefore produce the SAME key, and the second write stays invisible.
    That is not a theoretical race -- promote.apply() reads the current value to record
    it as `before`, so a stale read would log the wrong previous value and corrupt the
    rollback. Caught by the test suite on Linux; Windows timestamps happened to be fine
    enough to hide it."""
    _FILE_CACHE.clear()


def _read_json_cached(path):
    """Parse a config file, re-reading only when it changes. The backtester calls
    load_config() thousands of times per candidate; re-parsing every time made the
    optimizer disk-bound for no reason.

    Three layers guard against a stale read: mtime AND size in the key, an explicit
    invalidation on our own writes, and a one-second TTL so any staleness self-heals."""
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    hit = _FILE_CACHE.get(path)
    if hit and hit[0] == stamp and (time.monotonic() - hit[2]) < _CACHE_TTL:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            parsed = json.load(f)
    except Exception:
        parsed = {}
    _FILE_CACHE[path] = (stamp, parsed, time.monotonic())
    return parsed


def _deep_merge(base, over):
    """Recursive merge returning a NEW structure -- callers may mutate the result freely."""
    out = deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def load_config():
    """Effective config, lowest to highest precedence:
        config.json        human baseline, in git
        config.local.json  what the research agent learned and promoted
        config.user.json   what YOU set in the dashboard -- beats the agent, so a manual
                           choice is never silently overridden by the auto-tuner
        _RUNTIME_OVERRIDES in-process only (backtester isolation), always on top"""
    cfg = _deep_merge(_read_json_cached(CONFIG_FILE), _read_json_cached(CONFIG_LOCAL))
    cfg = _deep_merge(cfg, _read_json_cached(CONFIG_USER))
    return _deep_merge(cfg, _RUNTIME_OVERRIDES)


def load_baseline():
    """config.json alone -- what a `git pull` controls, without the agent's overrides."""
    return deepcopy(_read_json_cached(CONFIG_FILE))


def load_local_overrides():
    """Only what the research agent has promoted so far ({} when it never has)."""
    return deepcopy(_read_json_cached(CONFIG_LOCAL))


def expand_flat(flat):
    """{'allocation.min_change_threshold': 0.02} -> {'allocation': {'min_change_threshold': 0.02}}"""
    out = {}
    for key, value in (flat or {}).items():
        node = out
        parts = str(key).split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    return out


def flatten(nested, prefix=""):
    """Inverse of expand_flat -- used to diff and log promotions."""
    out = {}
    for k, v in (nested or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def flat_get(cfg, dotted, default=None):
    node = cfg
    for p in str(dotted).split("."):
        if not isinstance(node, dict) or p not in node:
            return default
        node = node[p]
    return node


@contextmanager
def config_override(flat):
    """Evaluate a candidate parameter set in-process. Nothing is written to disk, and
    every module that calls load_config() sees the candidate for the duration."""
    global _RUNTIME_OVERRIDES
    previous = _RUNTIME_OVERRIDES
    _RUNTIME_OVERRIDES = _deep_merge(previous, expand_flat(flat))
    try:
        yield load_config()
    finally:
        _RUNTIME_OVERRIDES = previous


def fee_bps_per_side(symbol, cfg=None):
    """Trading cost in basis points PER SIDE for one symbol -- the SINGLE source every layer
    reads so net P&L, the optimizer and the churn brake all price the same cost. Crypto pays a
    real taker fee on Alpaca; US equities are commission-free. A round-trip pays this twice, so
    at 25bps/side a crypto trade must move >0.5% just to break even. is_crypto is the trivial
    slash test (BTC/USD), inlined so this low-level module needs no market_data import."""
    f = (cfg or load_config()).get("fees", {})
    crypto = "/" in str(symbol)
    return float(f.get("crypto_bps_per_side", 25) if crypto else f.get("equity_bps_per_side", 0))


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


if __name__ == "__main__":
    cfg = load_config()
    assert cfg["watchlist"], "watchlist missing"
    thr = cfg["allocation"]["min_change_threshold"]
    with config_override({"allocation.min_change_threshold": 0.077}) as c:
        assert c["allocation"]["min_change_threshold"] == 0.077
        assert load_config()["allocation"]["min_change_threshold"] == 0.077, "override not visible"
    assert load_config()["allocation"]["min_change_threshold"] == thr, "override leaked"
    assert flat_get(cfg, "execution.cycle_seconds") == cfg["execution"]["cycle_seconds"]
    assert fee_bps_per_side("BTC/USD", cfg) > 0, "crypto must carry a fee"
    assert fee_bps_per_side("SPY", cfg) == 0, "commission-free equities"
    assert expand_flat({"a.b": 1}) == {"a": {"b": 1}}
    assert flatten({"a": {"b": 1}}) == {"a.b": 1}
    print(f"settings self-check ok · local overrides active: {bool(load_local_overrides())}")
