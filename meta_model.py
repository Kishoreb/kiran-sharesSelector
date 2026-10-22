"""
Meta-labeling: a trade-quality filter that sits ON TOP of the rule-based strategies.

The strategies (pullback_trend, breakout) still decide WHETHER a setup exists. The meta-model only answers a
second question: "of the setups that pass, how likely is this one to end as a winner?" It never creates
signals and never changes stops, targets or sizing.

Design choices (and why):
  * Features are price/volume/index data only, computed with bars up to and including the signal day, so they are
    point-in-time. Fundamentals, market cap and news are live snapshots, so they are deliberately NOT used.
  * Training rows = every signal the strategy produced in a backtest run WITHOUT capacity limits (see screener.py
    `train-meta`), so the model learns setup quality, not which trades happened to fit your capital.
  * Probabilities are CALIBRATED (isotonic / Platt, fitted on a later time slice than the model itself), and the
    walk-forward report shows Brier scores and a reliability table, so 'min prob 0.5' means what it says.
  * Model = scikit-learn HistGradientBoostingClassifier, kept shallow. For a few thousand rows of tabular data this
    matches or beats a neural network with far less over-fitting; PyTorch is used where it earns its place
    (FinBERT, text embeddings).
  * Validation is walk-forward only: each fold trains on trades that had already CLOSED before the test window
    starts, then scores the next unseen window. The report compares the plain rules with the rules + filter.

Honest limits: survivorship bias (today's index list) is in the training data, a few hundred to a few thousand
trades is a small sample, and the filter can only be trusted if the walk-forward table says it helps out-of-sample.
"""

import math
import os
import pickle
import time
from typing import List, Optional

import numpy as np
import pandas as pd

from strategies import atr

NAN = float("nan")

FEATURES = [
    "stop_pct", "atr_pct", "ret_5d", "ret_20d", "ret_63d", "rel_strength_63d", "vol_ratio",
    "pct_vs_ema20", "pct_vs_ema50", "pct_vs_sma200", "pct_below_52w_high", "ema50_slope_20d",
    "close_pos_in_range", "log_traded_value_cr", "idx_ret_20d", "idx_bull", "score_frac", "is_breakout",
]


def _num(x) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else NAN
    except (TypeError, ValueError):
        return NAN


def _pct_ratio(a, b) -> float:
    a, b = _num(a), _num(b)
    return (a / b - 1) * 100 if b > 0 and a == a else NAN


def features_at(df: pd.DataFrame, i: int, bench=None, sig=None, strategy_name: str = "") -> dict:
    """Feature dict for bar i using only bars <= i. `sig` (a strategies.Signal) adds stop distance and score."""
    row = df.iloc[i]
    close = _num(row["Close"])
    closes = df["Close"]
    f = {k: NAN for k in FEATURES}

    if sig is not None and sig.entry and sig.stop:
        f["stop_pct"] = (sig.entry - sig.stop) / sig.entry * 100
        if sig.total:
            f["score_frac"] = sig.score / sig.total
    a = atr(df, i)
    f["atr_pct"] = a / close * 100 if a == a and close > 0 else NAN
    for k, n in (("ret_5d", 5), ("ret_20d", 20), ("ret_63d", 63)):
        f[k] = _pct_ratio(close, closes.iloc[i - n]) if i >= n else NAN
    vol_avg = _num(row.get("vol_avg20"))
    f["vol_ratio"] = _num(row["Volume"]) / vol_avg if vol_avg > 0 else NAN
    f["pct_vs_ema20"] = _pct_ratio(close, row.get("ema20"))
    f["pct_vs_ema50"] = _pct_ratio(close, row.get("ema50"))
    f["pct_vs_sma200"] = _pct_ratio(close, row.get("sma200"))
    hi = _num(row.get("high_252"))
    f["pct_below_52w_high"] = (1 - close / hi) * 100 if hi > 0 else NAN
    f["ema50_slope_20d"] = _pct_ratio(df["ema50"].iloc[i], df["ema50"].iloc[i - 20]) if i >= 20 else NAN
    rng = _num(row["High"]) - _num(row["Low"])
    f["close_pos_in_range"] = (close - _num(row["Low"])) / rng if rng > 0 else 0.5
    tv = _num(row.get("avg_value20"))
    f["log_traded_value_cr"] = math.log10(tv / 1e7) if tv > 0 else NAN
    f["is_breakout"] = 1.0 if strategy_name == "breakout" else 0.0

    if bench is not None:
        d = df.index[i].date()
        f["rel_strength_63d"] = _num(bench.relative_strength(df, i))
        if i >= 20:
            f["idx_ret_20d"] = _pct_ratio(bench.close_asof(d), bench.close_asof(df.index[i - 20].date()))
        bull = bench.is_bullish(d)
        f["idx_bull"] = NAN if bull is None else (1.0 if bull else 0.0)
    return f


# ---------------------------------------------------------------- dataset
def build_dataset(trades, symbol_data: dict, bench, strategy, label: str = "win") -> pd.DataFrame:
    """One row per trade: features on the SIGNAL day (the bar before the entry fill) + outcome columns.
    label 'win' = net profit after costs; 'target' = the profit target was hit."""
    pos_cache, rows = {}, []
    for t in trades:
        df = symbol_data.get(t.symbol)
        if df is None:
            continue
        pm = pos_cache.setdefault(t.symbol, {ts.date().isoformat(): k for k, ts in enumerate(df.index)})
        k = pm.get(t.entry_date)
        if k is None or k < 1:
            continue
        i = k - 1                                           # signal bar; the fill was at the next open
        sig = strategy.signal(df, i)
        feats = features_at(df, i, bench, sig, strategy.name)
        y = int(t.exit_reason == "target") if label == "target" else int(t.pnl_rupees > 0)
        rows.append({**feats, "symbol": t.symbol, "entry_date": t.entry_date, "exit_date": t.exit_date,
                     "exit_reason": t.exit_reason, "r_multiple": t.r_multiple, "label": y})
    ds = pd.DataFrame(rows)
    return ds.sort_values("entry_date").reset_index(drop=True) if len(ds) else ds


# ---------------------------------------------------------------- model
def make_model():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=20,
                                          l2_regularization=1.0, random_state=0)


class CalibratedModel:
    """Base model + a probability calibrator fitted on a LATER time slice of the training trades, so that a
    predicted 60% really means roughly 60% of such setups won. method: 'isotonic' (200+ calibration rows),
    'sigmoid' (Platt scaling, 40-199 rows) or 'none' (too few rows: raw probabilities, flagged as such)."""

    def __init__(self, base, calibrator=None, method="none"):
        self.base, self.cal, self.method = base, calibrator, method

    def predict_raw(self, X):
        return self.base.predict_proba(X)[:, 1]

    def _apply(self, p):
        if self.method == "isotonic":
            return np.clip(self.cal.predict(p), 0.0, 1.0)
        if self.method == "sigmoid":
            q = np.clip(p, 1e-4, 1 - 1e-4)
            return self.cal.predict_proba(np.log(q / (1 - q)).reshape(-1, 1))[:, 1]
        return p

    def predict_proba(self, X):
        q = self._apply(self.predict_raw(X))
        return np.column_stack([1 - q, q])


def fit_calibrated(train: pd.DataFrame, calib_frac: float = 0.3, min_calib: int = 40) -> CalibratedModel:
    """Fit the base model on the EARLIER part of the (time-ordered) training trades and the calibrator on the
    LATER part. Falls back to an uncalibrated model when the later part is too small or has one outcome."""
    d = train.sort_values("entry_date")
    n_cal = int(len(d) * calib_frac)
    base_df, cal_df = d.iloc[:len(d) - n_cal], d.iloc[len(d) - n_cal:]
    if n_cal < min_calib or base_df["label"].nunique() < 2 or cal_df["label"].nunique() < 2:
        return CalibratedModel(make_model().fit(d[FEATURES], d["label"]))
    base = make_model().fit(base_df[FEATURES], base_df["label"])
    p = base.predict_proba(cal_df[FEATURES])[:, 1]
    y = cal_df["label"].to_numpy()
    if n_cal >= 200:
        from sklearn.isotonic import IsotonicRegression
        return CalibratedModel(base, IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p, y),
                               "isotonic")
    from sklearn.linear_model import LogisticRegression
    q = np.clip(p, 1e-4, 1 - 1e-4)
    return CalibratedModel(base, LogisticRegression(C=1.0).fit(np.log(q / (1 - q)).reshape(-1, 1), y), "sigmoid")


def _stats(d: pd.DataFrame) -> dict:
    n = len(d)
    if n == 0:
        return {"trades": 0, "win_pct": None, "avg_r": None, "total_r": None}
    return {"trades": n, "win_pct": round(float((d["r_multiple"] > 0).mean() * 100), 1),
            "avg_r": round(float(d["r_multiple"].mean()), 3), "total_r": round(float(d["r_multiple"].sum()), 1)}


def walk_forward(ds: pd.DataFrame, train_months: int = 24, test_months: int = 6, min_train: int = 100,
                 keep_top: float = 0.5) -> dict:
    """Train on trades CLOSED before each test window, score the window, roll forward."""
    parts, methods = [], {}
    if len(ds):
        t = pd.Timestamp(ds["entry_date"].min()) + pd.DateOffset(months=train_months)
        last = pd.Timestamp(ds["entry_date"].max())
        fold = 0
        while t <= last:
            te_end = t + pd.DateOffset(months=test_months)
            train = ds[ds["exit_date"] < str(t.date())]
            test = ds[(ds["entry_date"] >= str(t.date())) & (ds["entry_date"] < str(te_end.date()))]
            if len(train) >= min_train and train["label"].nunique() == 2 and len(test):
                m = fit_calibrated(train)
                fold += 1
                methods[m.method] = methods.get(m.method, 0) + 1
                parts.append(test.assign(prob=m.predict_proba(test[FEATURES])[:, 1],
                                         prob_raw=m.predict_raw(test[FEATURES]), fold=fold))
            t = te_end
    out = {"folds": len(parts), "oos_trades": 0, "auc": None, "base": _stats(ds.iloc[0:0]), "tiers": [],
           "improved_folds": None, "cutoff": None, "brier": None, "reliability": [], "calib_methods": methods}
    if not parts:
        out["verdict"] = (f"No usable walk-forward folds (need {min_train}+ closed trades before each test window "
                          f"and both outcomes present). Use a longer --period or a wider universe.")
        return out
    oos = pd.concat(parts)
    out["oos_trades"] = len(oos)
    out["base"] = _stats(oos)
    if oos["label"].nunique() == 2:
        from sklearn.metrics import roc_auc_score
        out["auc"] = round(float(roc_auc_score(oos["label"], oos["prob"])), 3)
    from sklearn.metrics import brier_score_loss
    y = oos["label"]
    out["brier"] = {"raw": round(float(brier_score_loss(y, oos["prob_raw"])), 4),
                    "calibrated": round(float(brier_score_loss(y, oos["prob"])), 4),
                    "constant": round(float(brier_score_loss(y, np.full(len(y), y.mean()))), 4)}
    if len(oos) >= 25:
        oos["bucket"] = pd.qcut(oos["prob"].rank(method="first"), 5, labels=False)
        out["reliability"] = [{"bucket": int(b) + 1, "trades": len(g), "mean_pred": round(float(g["prob"].mean()), 3),
                               "actual_win": round(float(g["label"].mean()), 3)}
                              for b, g in oos.groupby("bucket")]
    for keep in (1.0, 0.7, 0.5, 0.3):
        cut = float(oos["prob"].quantile(1 - keep)) if keep < 1 else float(oos["prob"].min())
        s = _stats(oos[oos["prob"] >= cut])
        out["tiers"].append({"keep_top_pct": int(keep * 100), "min_prob": round(cut, 3), **s})
    out["cutoff"] = float(oos["prob"].quantile(1 - keep_top))
    kept = oos[oos["prob"] >= out["cutoff"]]
    better = sum(1 for _, g in oos.groupby("fold")
                 if len(g[g["prob"] >= out["cutoff"]]) and
                 g[g["prob"] >= out["cutoff"]]["r_multiple"].mean() > g["r_multiple"].mean())
    out["improved_folds"] = f"{better} of {out['folds']}"
    b, k = out["base"], _stats(kept)
    if out["oos_trades"] < 100:
        out["verdict"] = f"Only {out['oos_trades']} out-of-sample trades: too few to conclude anything."
    elif out["auc"] is not None and out["auc"] < 0.53:
        out["verdict"] = "No skill: out-of-sample AUC is close to 0.5. Do not use this filter."
    elif k["avg_r"] is None or b["avg_r"] is None or k["avg_r"] <= b["avg_r"]:
        out["verdict"] = "The filter did not raise average R out-of-sample. Do not use it."
    elif better < max(1, math.ceil(out["folds"] / 2)):
        out["verdict"] = ("Average R improved overall but in fewer than half the folds: unstable, treat with "
                          "suspicion.")
    else:
        out["verdict"] = (f"Out-of-sample average R rose from {b['avg_r']} to {k['avg_r']} on the kept "
                          f"top {int(keep_top * 100)}% (improved in {out['improved_folds']} folds). Promising, but "
                          f"survivorship bias and a small sample still apply.")
    return out


def fit_and_save(ds: pd.DataFrame, path: str, strategy: str, label: str, wf: dict) -> "MetaModel":
    m = fit_calibrated(ds)
    threshold = wf["cutoff"] if wf.get("cutoff") is not None else float(ds["label"].mean())
    payload = {"model": m, "features": FEATURES, "threshold": round(float(threshold), 4), "strategy": strategy,
               "label": label, "n_train": len(ds), "created": time.strftime("%Y-%m-%d %H:%M"),
               "oos": {k: wf.get(k) for k in ("folds", "oos_trades", "auc", "base", "tiers", "verdict", "brier", "reliability", "calib_methods")},
               "calibration": m.method, "version": 2}
    with open(path, "wb") as f:
        pickle.dump(payload, f)
    return MetaModel(payload)


class MetaModel:
    def __init__(self, payload: dict):
        self.payload = payload
        self.model = payload["model"]
        self.features: List[str] = payload["features"]
        self.threshold: float = payload["threshold"]
        self.strategy: str = payload["strategy"]

    def predict(self, feats: dict) -> float:
        x = pd.DataFrame([[feats.get(k, NAN) for k in self.features]], columns=self.features)
        return round(float(self.model.predict_proba(x)[0][1]), 3)


def load(path: str) -> MetaModel:
    with open(path, "rb") as f:
        return MetaModel(pickle.load(f))
