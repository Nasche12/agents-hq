"""Layer 3 -- safety. Circuit breakers that shut things down on losses. The most
important layer, and it works COMPLETELY INDEPENDENTLY of the HMM.

Circuit breakers:
  down day_halve_pct in a day   -> halve all position sizes
  down day_flat_pct in a day    -> close all positions
  down week_resize_pct in a week-> resize down
  down kill_from_peak_pct from peak -> stop the whole system + write EMERGENCY.lock
                                       (must be deleted by hand to resume)
Per-trade risk capped at per_trade_pct of the portfolio. On startup the lock file is
checked and the system refuses to run if it is present. State (daily/weekly P&L, peak
equity) is persisted so limits survive restarts -- a bot that forgets its daily loss
after a reboot can blow through its own breaker."""
import json
from datetime import date

import numpy as np

import settings


def _today():
    return date.today().isoformat()


def _iso_week():
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


class RiskManager:
    def __init__(self, equity=None):
        cfg = settings.load_config()
        self.cfg = cfg["risk"]
        self.state = self._load(equity if equity is not None else cfg["starting_equity"])

    # ---------- persisted state (survives restarts) ----------
    def _load(self, equity):
        if settings.RISK_STATE.exists():
            try:
                s = json.loads(settings.RISK_STATE.read_text(encoding="utf-8"))
                # roll day/week counters forward if the calendar advanced
                if s.get("day") != _today():
                    s["day"], s["day_start_equity"] = _today(), s.get("equity", equity)
                if s.get("week") != _iso_week():
                    s["week"], s["week_start_equity"] = _iso_week(), s.get("equity", equity)
                return s
            except Exception:
                pass
        return {
            "day": _today(), "week": _iso_week(),
            "equity": equity, "peak_equity": equity,
            "day_start_equity": equity, "week_start_equity": equity,
            "size_multiplier": 1.0, "killed": False,
        }

    def _save(self):
        settings.RISK_STATE.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    # ---------- startup gate ----------
    @staticmethod
    def locked():
        return settings.LOCK_FILE.exists()

    def require_unlocked(self):
        """Call on startup. Raises if the emergency lock is present."""
        if self.locked():
            raise SystemExit(f"EMERGENCY lock present ({settings.LOCK_FILE}). "
                             f"Investigate, then delete the file by hand to resume.")

    def _arm_kill(self, reason):
        settings.LOCK_FILE.write_text(
            f"Killed {_today()}: {reason}\nDelete this file by hand to resume.\n",
            encoding="utf-8")
        self.state["killed"] = True

    # ---------- per-cycle update ----------
    def update_equity(self, equity):
        """Feed the latest equity. Returns a dict describing which breakers fired and
        the resulting size multiplier (0.0 = flat/killed)."""
        s = self.state
        # calendar roll (a fresh day/week resets its counter to the new open)
        if s["day"] != _today():
            s["day"], s["day_start_equity"] = _today(), equity
        if s["week"] != _iso_week():
            s["week"], s["week_start_equity"] = _iso_week(), equity

        s["equity"] = equity
        s["peak_equity"] = max(s["peak_equity"], equity)

        day_dd = equity / s["day_start_equity"] - 1
        week_dd = equity / s["week_start_equity"] - 1
        peak_dd = equity / s["peak_equity"] - 1

        mult, breakers = 1.0, []
        if -peak_dd >= self.cfg["kill_from_peak_pct"]:
            self._arm_kill(f"-{-peak_dd:.1%} from peak")
            mult, breakers = 0.0, ["kill_switch"]
        elif -day_dd >= self.cfg["day_flat_pct"]:
            mult, breakers = 0.0, ["day_flat"]              # close everything today
        else:
            if -day_dd >= self.cfg["day_halve_pct"]:
                mult = min(mult, 0.5); breakers.append("day_halve")
            if -week_dd >= self.cfg["week_resize_pct"]:
                mult = min(mult, 0.5); breakers.append("week_resize")

        s["size_multiplier"] = 0.0 if s["killed"] else mult
        self._save()
        return {
            "multiplier": s["size_multiplier"], "breakers": breakers, "killed": s["killed"],
            "day_dd": round(day_dd, 4), "week_dd": round(week_dd, 4), "peak_dd": round(peak_dd, 4),
        }

    # ---------- order validation ----------
    def validate_order(self, target_alloc, target_leverage, new_symbol=None,
                       corr_with_existing=None):
        """Applies the size multiplier, leverage cap, per-trade cap and correlation
        block. Returns (approved_alloc, approved_leverage, reasons[])."""
        reasons = []
        if self.state["killed"] or self.locked():
            return 0.0, 0.0, ["system killed / locked"]

        alloc = target_alloc * self.state["size_multiplier"]
        if self.state["size_multiplier"] < 1.0:
            reasons.append(f"size x{self.state['size_multiplier']}")

        lev = min(target_leverage, self.cfg["max_leverage"])
        if lev < target_leverage:
            reasons.append(f"leverage capped {self.cfg['max_leverage']}x")

        # correlation check: block new positions correlated above the threshold
        if corr_with_existing is not None and corr_with_existing > self.cfg["max_correlation"]:
            return 0.0, 0.0, [f"corr {corr_with_existing:.2f} > {self.cfg['max_correlation']}"]

        return round(max(0.0, min(1.0, alloc)), 4), round(lev, 3), reasons

    def per_trade_cap(self):
        """Max fraction of the portfolio to risk on a single trade."""
        return self.cfg["per_trade_pct"]


def correlation(a, b):
    """Pearson correlation of two return series (for the correlation block)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[-n:], b[-n:]
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


if __name__ == "__main__":
    # isolated state for the self-check
    settings.RISK_STATE.unlink(missing_ok=True)
    settings.LOCK_FILE.unlink(missing_ok=True)
    rm = RiskManager(equity=100_000)
    assert rm.update_equity(100_000)["multiplier"] == 1.0
    assert "day_halve" in rm.update_equity(97_500)["breakers"]      # -2.5% day
    assert rm.update_equity(96_500)["multiplier"] == 0.0            # -3.5% day -> flat
    res = rm.update_equity(89_000)                                  # -11% from peak
    assert res["killed"] and RiskManager.locked(), "kill switch must arm"
    a, _, why = rm.validate_order(0.95, 1.25)
    assert a == 0.0, "no orders after kill"
    settings.RISK_STATE.unlink(missing_ok=True)
    settings.LOCK_FILE.unlink(missing_ok=True)
    print("risk self-check ok:", res, why)
