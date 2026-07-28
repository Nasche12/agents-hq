"""Layer 4 -- brokerage. A thin Alpaca client over requests.
WITHOUT keys it stays a safe offline stub: it reports connected=False and refuses to
place orders, so nothing can hit a real account by accident. When you add paper keys to
.env (ALPACA_PAPER=true), account() and submit_order() go live against paper-api.

Order rules this layer enforces, because Alpaca rejects anything else:
  * crypto (BTC/USD)      -> market order, time_in_force=gtc, fractional qty OK, NO shorts
  * equity regular hours  -> market order, time_in_force=day, fractional qty OK
  * equity extended hours -> LIMIT order + extended_hours=true, WHOLE shares only
"""
import settings
from market_data import is_crypto, pos_symbol

_TRADING_URL = "https://paper-api.alpaca.markets"
EXT_LIMIT_SLIP = 0.003          # 0.3% through the last price so extended limits still fill


class Broker:
    def __init__(self):
        self.key = settings.env("ALPACA_API_KEY")
        self.secret = settings.env("ALPACA_SECRET_KEY")
        self.paper = str(settings.env("ALPACA_PAPER", "true")).lower() == "true"
        # normalize: tolerate a trailing slash or an accidental trailing /v2 in .env
        base = (settings.env("ALPACA_BASE_URL", _TRADING_URL) or _TRADING_URL).rstrip("/")
        if base.endswith("/v2"):
            base = base[:-3]
        self.base = base

    @property
    def connected(self):
        return bool(self.key and self.secret)

    def _headers(self):
        return {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}

    def account(self):
        """Live account snapshot, or an offline stub when no keys are present."""
        if not self.connected:
            return {"status": "offline", "paper": True, "cash": None, "equity": None,
                    "note": "no ALPACA keys in .env -> offline stub"}
        import requests
        r = requests.get(f"{self.base}/v2/account", headers=self._headers(), timeout=20)
        r.raise_for_status()
        a = r.json()
        return {"status": a.get("status"), "paper": self.paper,
                "cash": float(a["cash"]), "equity": float(a["equity"]),
                "buying_power": _f(a.get("buying_power")),
                "last_equity": _f(a.get("last_equity")),
                "long_market_value": _f(a.get("long_market_value")),
                "short_market_value": _f(a.get("short_market_value")),
                "multiplier": _f(a.get("multiplier"))}

    def clock(self):
        """Market clock: {is_open, next_open, next_close}. {} when offline."""
        if not self.connected:
            return {}
        import requests
        r = requests.get(f"{self.base}/v2/clock", headers=self._headers(), timeout=20)
        r.raise_for_status()
        return r.json()

    def list_orders(self, status="all", limit=50):
        """Recent orders on the account, newest first."""
        if not self.connected:
            return []
        import requests
        r = requests.get(f"{self.base}/v2/orders", headers=self._headers(),
                         params={"status": status, "limit": limit, "direction": "desc"}, timeout=20)
        r.raise_for_status()
        return r.json()

    def positions(self):
        """Open positions on the (paper) account. Empty list when offline or none held."""
        if not self.connected:
            return []
        import requests
        r = requests.get(f"{self.base}/v2/positions", headers=self._headers(), timeout=20)
        r.raise_for_status()
        return [{"symbol": p["symbol"], "qty": float(p["qty"]),
                 "market_value": float(p["market_value"]),
                 "unrealized_pl": float(p["unrealized_pl"]),
                 "unrealized_plpc": _f(p.get("unrealized_plpc")),
                 "current_price": _f(p.get("current_price")),
                 "cost_basis": _f(p.get("cost_basis")),
                 "asset_class": p.get("asset_class") or "us_equity",
                 "side": p.get("side") or ("long" if float(p["qty"]) >= 0 else "short"),
                 "avg_entry": float(p["avg_entry_price"])} for p in r.json()]

    def close_position(self, symbol):
        """Flatten the position in `symbol` at market. Returns the closing order or None."""
        if not self.connected:
            raise RuntimeError("Broker offline (no keys).")
        import requests
        r = requests.delete(f"{self.base}/v2/positions/{pos_symbol(symbol)}",
                            headers=self._headers(), timeout=20)
        if r.status_code == 404:
            return None                                 # nothing to close
        _raise_for(r, symbol)
        return r.json()

    def submit_order(self, symbol, qty, side, extended=False, price_ref=None):
        """SAFETY: refuses unless real paper keys are present. Never touches a live
        account by accident. Builds the only order shape Alpaca accepts for the given
        asset class / session (see module docstring)."""
        if not self.connected:
            raise RuntimeError("Broker offline (no keys). Add paper keys to .env first.")
        if not self.paper:
            raise RuntimeError("ALPACA_PAPER is not 'true' -- live trading blocked.")
        import requests
        q = abs(float(qty))
        if q <= 0:
            raise ValueError("qty must be > 0")
        body = {"symbol": symbol, "side": side}

        if is_crypto(symbol):
            # crypto never sleeps and never closes -> gtc, fractional allowed
            body.update({"qty": f"{q:.6f}".rstrip("0").rstrip("."),
                         "type": "market", "time_in_force": "gtc"})
        elif extended:
            # extended hours: limit orders + whole shares only, priced through the market
            whole = int(q)
            if whole < 1:
                raise ValueError("extended-hours orders need at least 1 whole share")
            if not price_ref:
                raise ValueError("extended-hours orders need a reference price")
            slip = 1 + EXT_LIMIT_SLIP if side == "buy" else 1 - EXT_LIMIT_SLIP
            body.update({"qty": str(whole), "type": "limit", "time_in_force": "day",
                         "limit_price": f"{price_ref * slip:.2f}", "extended_hours": True})
        else:
            body.update({"qty": str(int(q)) if q == int(q) else f"{q:.4f}",
                         "type": "market", "time_in_force": "day"})

        r = requests.post(f"{self.base}/v2/orders", headers=self._headers(), json=body, timeout=20)
        _raise_for(r, f"{side} {symbol}")
        return r.json()


def _raise_for(r, ctx=""):
    """Raise with Alpaca's ACTUAL reason (the JSON body), not just '403 Forbidden'. The body
    is where the cause lives -- e.g. 'potential wash trade', 'insufficient buying power'."""
    if r.status_code < 400:
        return
    try:
        body = r.json()
        msg = body.get("message") or body
    except Exception:
        msg = (r.text or "")[:220]
    raise RuntimeError(f"{r.status_code} {ctx}: {msg}")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    b = Broker()
    acct = b.account()
    print("broker:", "connected" if b.connected else "offline stub", "| account:", acct["status"])
    if not b.connected:
        for sym in ("NVDA", "BTC/USD"):
            try:
                b.submit_order(sym, 1, "buy")
                raise AssertionError("offline broker must refuse orders")
            except RuntimeError:
                pass
        print("broker self-check ok (refuses equity AND crypto orders while offline)")
