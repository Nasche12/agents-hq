"""Layer 4 -- brokerage (Phase 2 boundary). A thin Alpaca client over requests.
WITHOUT keys it stays a safe offline stub: it reports connected=False and refuses to
place orders, so nothing can hit a real account by accident. When you add paper keys to
.env (ALPACA_PAPER=true), account() and submit_order() go live against paper-api.

Full order_executor / position_tracker (bracket orders, reconciliation, retries) are
Phase 2 -- wired here once you have keys and can verify the NVDA test order."""
import settings

_TRADING_URL = "https://paper-api.alpaca.markets"


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
                "cash": float(a["cash"]), "equity": float(a["equity"])}

    def clock(self):
        """Market clock: {is_open, next_open, next_close}. {} when offline."""
        if not self.connected:
            return {}
        import requests
        r = requests.get(f"{self.base}/v2/clock", headers=self._headers(), timeout=20)
        r.raise_for_status()
        return r.json()

    def list_orders(self, status="all", limit=50):
        """Recent orders on the account."""
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
                 "avg_entry": float(p["avg_entry_price"])} for p in r.json()]

    def close_position(self, symbol):
        """Flatten the position in `symbol` at market. Returns the closing order or None."""
        if not self.connected:
            raise RuntimeError("Broker offline (no keys).")
        import requests
        r = requests.delete(f"{self.base}/v2/positions/{symbol}", headers=self._headers(), timeout=20)
        if r.status_code == 404:
            return None                                 # nothing to close
        r.raise_for_status()
        return r.json()

    def submit_order(self, symbol, qty, side):
        """SAFETY: refuses unless real paper keys are present. Never touches a live
        account by accident. Phase 2 extends this with bracket/limit orders + retries."""
        if not self.connected:
            raise RuntimeError("Broker offline (no keys). Add paper keys to .env first.")
        if not self.paper:
            raise RuntimeError("ALPACA_PAPER is not 'true' -- live trading blocked in Phase 1-3.")
        import requests
        q = abs(float(qty))
        qty_str = str(int(q)) if q == int(q) else f"{q:.4f}"   # whole or fractional
        body = {"symbol": symbol, "qty": qty_str, "side": side,
                "type": "market", "time_in_force": "day"}
        r = requests.post(f"{self.base}/v2/orders", headers=self._headers(), json=body, timeout=20)
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    b = Broker()
    acct = b.account()
    print("broker:", "connected" if b.connected else "offline stub", "| account:", acct["status"])
    if not b.connected:
        try:
            b.submit_order("NVDA", 1, "buy")
            raise AssertionError("offline broker must refuse orders")
        except RuntimeError:
            print("broker self-check ok (refuses orders while offline)")
