"""Layer 1 -- the brain. A Gaussian HMM that picks the NUMBER of regimes by BIC
(min..max), sorts regimes by mean return (0 = weakest) and labels them.

TWO things that decide whether the backtest is honest:
1. FORWARD-ONLY inference. We do NOT use model.predict (Viterbi over the whole
   sequence -> sees the future). Instead: per-bar emission log-prob (that bar only)
   plus a forward recursion (past only). The filtered state at t uses only data up to
   t. No look-ahead.
2. FIXED SEED. random_state pinned -> training reproducible, regime labels stable.

Plus a stability filter: a regime must persist for >=N bars before acting; if it
flickers >K times in 20 bars, warn and cut position sizes."""
import logging
import warnings

import numpy as np
from hmmlearn.hmm import GaussianHMM

# hmmlearn logs "Model is not converging" / zero-sum transmat via logging, not warnings.
# We test several regime counts and pick by BIC, so non-convergence of some is expected.
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

import settings
from feature_engineering import build_features, FEATURE_COLS


class RegimeModel:
    def __init__(self, model, order, labels, n_regimes):
        self.model = model              # fitted GaussianHMM (diag)
        self.order = order              # raw HMM state -> rank by return (0=weakest)
        self.labels = labels            # rank -> name ("crash".."euphoria")
        self.n_regimes = n_regimes

    # ---- per-bar emission log-prob, independent (no temporal coupling) ----
    def _emission_logprob(self, X):
        m = self.model
        means, covars = m.means_, m.covars_
        if covars.ndim == 3:                        # full/diag -> take the diagonal
            covars = np.array([np.diag(c) for c in covars])
        out = np.empty((X.shape[0], m.n_components))
        for k in range(m.n_components):
            var = covars[k]
            diff = X - means[k]
            out[:, k] = -0.5 * (np.sum(diff * diff / var, axis=1)
                                + np.sum(np.log(2 * np.pi * var)))
        return out

    def filter_states(self, X):
        """Forward filtering. Returns (regime_rank[t], confidence[t]) -- both from data
        up to t only. confidence = filtered posterior probability."""
        elog = self._emission_logprob(X)
        n, k = elog.shape
        log_start = np.log(self.model.startprob_ + 1e-12)
        log_trans = np.log(self.model.transmat_ + 1e-12)
        filtered = np.empty((n, k))
        alpha = log_start + elog[0]
        filtered[0] = _softmax(alpha)
        for t in range(1, n):
            # predictive step (past only) + update with the emission at t
            prev = _logsumexp_axis(alpha[:, None] + log_trans)   # over previous states
            alpha = prev + elog[t]
            alpha -= alpha.max()                                 # numerically stable
            filtered[t] = _softmax(alpha)
        raw = filtered.argmax(axis=1)
        # map raw HMM states onto rank (sorted by return)
        rank = np.array([self.order[s] for s in raw])
        conf = filtered.max(axis=1)
        return rank, conf

    def latest(self, df):
        """Current regime + confidence + stability info for the live loop."""
        feats = build_features(df)
        X = feats[FEATURE_COLS].values
        rank, conf = self.filter_states(X)
        cfg = settings.load_config()["hmm"]
        stab = _stability(rank, cfg["stability_min_bars"], cfg["flicker_max_in_20"])
        r = int(rank[-1])
        return {
            "regime": self.labels[r],
            "regime_rank": r,
            "n_regimes": self.n_regimes,
            "confidence": round(float(conf[-1]), 4),
            "stable": stab["stable"],
            "flickering": stab["flickering"],
            "index": feats.index[-1],
        }


def _softmax(logv):
    e = np.exp(logv - logv.max())
    return e / e.sum()


def _logsumexp_axis(mat):
    m = mat.max(axis=0)
    return m + np.log(np.exp(mat - m).sum(axis=0))


def _stability(rank, min_bars, flicker_max):
    """stable = the last min_bars bars share the same regime. flickering = >flicker_max
    switches in the last 20 bars (then cut position sizes)."""
    stable = len(rank) >= min_bars and len(set(rank[-min_bars:])) == 1
    last20 = rank[-20:]
    changes = int(np.sum(last20[1:] != last20[:-1])) if len(last20) > 1 else 0
    return {"stable": bool(stable), "flickering": changes > flicker_max, "changes_20": changes}


def _bic(model, X):
    """BIC = -2*logL + k*ln(N). Lower is better. k = free parameters (diag)."""
    n, d = X.shape
    c = model.n_components
    k = (c - 1) + c * (c - 1) + c * d + c * d   # start + trans + means + diag covars
    logL = model.score(X)
    return -2 * logL + k * np.log(n)


def train(df, min_regimes=None, max_regimes=None, random_state=None):
    """Trains HMMs from min..max regimes, picks by BIC, labels by return.
    Reproducible thanks to a fixed random_state."""
    cfg = settings.load_config()["hmm"]
    min_r = min_regimes or cfg["min_regimes"]
    max_r = max_regimes or cfg["max_regimes"]
    seed = cfg["random_state"] if random_state is None else random_state

    feats = build_features(df)
    X = feats[FEATURE_COLS].values
    if len(X) < 60:
        raise ValueError(f"Too few bars for HMM training: {len(X)}")

    best, best_bic = None, np.inf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for n in range(min_r, max_r + 1):
            try:
                m = GaussianHMM(n_components=n, covariance_type="diag",
                                n_iter=200, random_state=seed, tol=1e-3)
                m.fit(X)
                if not np.all(np.isfinite(m.means_)):
                    continue
                b = _bic(m, X)
                if b < best_bic:
                    best, best_bic = m, b
            except Exception:
                continue
    if best is None:
        raise RuntimeError("No HMM converged")

    # sort regimes by mean log_return (column 0) -> rank 0 = weakest
    mean_ret = best.means_[:, 0]
    ranked_states = np.argsort(mean_ret)              # raw state in rank order
    order = np.empty(best.n_components, dtype=int)
    for rank_i, state in enumerate(ranked_states):
        order[state] = rank_i
    labels = settings.regime_labels(best.n_components)
    return RegimeModel(best, order, labels, best.n_components)


if __name__ == "__main__":
    import market_data
    df = market_data.get_daily_bars("SPY", days=600, force_synthetic=True)
    rm = train(df)
    info = rm.latest(df)
    print(f"chosen: {rm.n_regimes} regimes | now: {info['regime']} "
          f"(conf {info['confidence']}, stable={info['stable']})")

    # reproducibility: same seed -> same labeling
    rm2 = train(df)
    assert rm2.n_regimes == rm.n_regimes and rm2.labels == rm.labels, "not reproducible"

    # look-ahead: filtered state at t must not change when later bars are missing
    feats = build_features(df)
    X = feats[FEATURE_COLS].values
    full_rank, _ = rm.filter_states(X)
    part_rank, _ = rm.filter_states(X[:len(X) - 30])
    assert np.array_equal(full_rank[:len(part_rank)], part_rank), \
        "LOOK-AHEAD: filtered state depends on the future"
    print("hmm self-check ok (reproducible + forward-only)")
