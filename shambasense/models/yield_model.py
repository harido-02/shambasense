"""Gradient-boosted quantile model of crop yield, with evaluation and explanations.

The target is relative yield (yield divided by the crop's average yield in the
training data), so errors on low-yield crops such as beans count as much as
errors on potatoes. Three quantile models give a 10th, 50th and 90th percentile.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import __version__, config
from . import suitability

log = logging.getLogger(__name__)

NUMERIC = ["rain_mm", "rain_days", "max_dry_spell", "tmean_c", "tmax_c", "tmin_c", "onset_delay_days",
           "ph", "soc_g_kg", "nitrogen_g_kg", "clay_pct", "sand_pct", "cec_cmol_kg", "suitability"]
GROUPS = {
    "rainfall": ["rain_mm", "rain_days", "max_dry_spell", "onset_delay_days"],
    "temperature": ["tmean_c", "tmax_c", "tmin_c"],
    "soil_acidity": ["ph"],
    "soil_fertility": ["soc_g_kg", "nitrogen_g_kg", "cec_cmol_kg"],
    "soil_texture": ["clay_pct", "sand_pct"],
    "crop_fit": ["suitability"],
}
# Local explanations fold the suitability score into the factors it is computed from.
EXPLAIN_GROUPS = {k: v for k, v in GROUPS.items() if k != "crop_fit"}
GROUP_LABELS = {
    "rainfall": {"en": "Rainfall and timing of the rains", "sw": "Mvua na wakati wake"},
    "temperature": {"en": "Temperature", "sw": "Joto"},
    "soil_acidity": {"en": "Soil pH", "sw": "pH ya udongo"},
    "soil_fertility": {"en": "Soil fertility (organic carbon, nitrogen, CEC)", "sw": "Rutuba ya udongo"},
    "soil_texture": {"en": "Soil texture (clay and sand)", "sw": "Aina ya udongo (mfinyanzi na mchanga)"},
    "crop_fit": {"en": "Overall fit to the crop's needs", "sw": "Ufaafu wa jumla kwa zao"},
}
MODEL_FILE = "yield_model.joblib"
META_FILE = "yield_model.json"


class YieldModel:
    def __init__(self, crops: list[str] | None = None, params: dict | None = None,
                 quantiles: tuple[float, ...] | None = None):
        s = config.settings()["model"]
        self.crops = crops or config.crop_ids()
        self.quantiles = tuple(quantiles or s["quantiles"])
        self.params = params or {k: s[k] for k in ("max_iter", "learning_rate", "max_depth",
                                                   "min_samples_leaf", "l2_regularization")}
        self.models: dict[float, HistGradientBoostingRegressor] = {}
        self.crop_mean: dict[str, float] = {}
        self.reference: dict[str, dict] = {}
        self.ranges: dict[str, tuple[float, float]] = {}
        self.interval_scale = 1.0     # widens p10-p90 to hit 80% coverage in cross-validation
        self.meta: dict = {}

    # ---------------------------------------------------------------- design matrix
    def design(self, df: pd.DataFrame) -> np.ndarray:
        num = df.reindex(columns=NUMERIC).astype(float).to_numpy()
        onehot = np.column_stack([(df["crop"] == c).astype(float).to_numpy() for c in self.crops])
        return np.hstack([num, onehot])

    def feature_names(self) -> list[str]:
        return NUMERIC + [f"crop_{c}" for c in self.crops]

    # ---------------------------------------------------------------- fit / predict
    def fit(self, df: pd.DataFrame) -> "YieldModel":
        df = df[df["crop"].isin(self.crops)].reset_index(drop=True)
        self.crop_mean = df.groupby("crop")["yield_t_ha"].mean().to_dict()
        y = (df["yield_t_ha"] / df["crop"].map(self.crop_mean)).to_numpy()
        X = self.design(df)
        self.models = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, random_state=0,
                                                        **self.params).fit(X, y)
                       for q in self.quantiles}
        self.reference = df.groupby("crop")[NUMERIC].median().to_dict("index")
        self.ranges = {c: (float(df[c].quantile(0.02)), float(df[c].quantile(0.98)))
                       for c in NUMERIC if df[c].notna().any()}
        return self

    def predict_relative(self, df: pd.DataFrame) -> np.ndarray:
        X = self.design(df)
        preds = np.column_stack([self.models[q].predict(X) for q in self.quantiles])
        preds.sort(axis=1)               # quantile models can cross; keep p10 <= p50 <= p90
        s = getattr(self, "interval_scale", 1.0)
        mid = preds[:, 1]
        preds[:, 0] = mid - s * (mid - preds[:, 0])
        preds[:, 2] = mid + s * (preds[:, 2] - mid)
        return np.clip(preds, 0, None)

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        rel = self.predict_relative(df)
        scale = df["crop"].map(self.crop_mean).to_numpy(dtype=float)
        out = rel * scale[:, None]
        names = [f"p{int(round(q * 100))}" for q in self.quantiles]
        return pd.DataFrame(out, columns=names, index=df.index)

    def knows(self, crop_id: str) -> bool:
        return crop_id in self.crop_mean

    # ---------------------------------------------------------------- explanations
    def explain(self, row: dict, top: int = 3) -> list[dict]:
        """Effect of each feature group on the median yield, against the crop's typical conditions.

        Each group is swapped for the crop's median training values (and the rule-based
        suitability recomputed, since it derives from rainfall, temperature and pH); the
        change in predicted yield is that group's contribution (positive = helps here).
        """
        crop = row["crop"]
        ref = self.reference.get(crop)
        if ref is None:
            return []

        def with_suit(r: dict) -> dict:
            r = dict(r)
            r["suitability"] = suitability.score(crop, r.get("rain_mm"), r.get("tmean_c"), r.get("ph"))["score"]
            return r

        variants = [with_suit(row)]
        for cols in EXPLAIN_GROUPS.values():
            alt = dict(row)
            for c in cols:
                alt[c] = ref.get(c)
            variants.append(with_suit(alt))
        p50 = self.predict(pd.DataFrame(variants))["p50"].to_numpy()
        effects = [{"group": g, "effect_t_ha": float(p50[0] - p50[i + 1])} for i, g in enumerate(EXPLAIN_GROUPS)]
        effects.sort(key=lambda e: abs(e["effect_t_ha"]), reverse=True)
        floor = max(0.03 * self.crop_mean.get(crop, 1.0), 0.02)
        return [e for e in effects[:top] if abs(e["effect_t_ha"]) >= floor]

    def out_of_range(self, row: dict) -> list[str]:
        out = []
        for c, (lo, hi) in self.ranges.items():
            v = row.get(c)
            if v is not None and not np.isnan(v) and (v < lo - 0.1 * abs(lo) or v > hi + 0.1 * abs(hi)):
                out.append(c)
        return out

    # ---------------------------------------------------------------- persistence
    def save(self, directory: Path | None = None) -> Path:
        directory = directory or config.model_dir()
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, directory / MODEL_FILE)
        (directory / META_FILE).write_text(json.dumps(self.meta, indent=2, default=str))
        return directory / MODEL_FILE

    @staticmethod
    def load(directory: Path | None = None) -> "YieldModel":
        directory = directory or config.model_dir()
        return joblib.load(directory / MODEL_FILE)


# =============================================================================== evaluation

def _baseline(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Average yield of the same crop in the same county (crop average if the county is unseen)."""
    county_crop = train.groupby(["county_id", "crop"])["yield_t_ha"].mean()
    crop = train.groupby("crop")["yield_t_ha"].mean()
    return np.array([county_crop.get((r.county_id, r.crop), crop.get(r.crop, np.nan)) for r in test.itertuples()])


def _sk_model(kind: str, crops: list[str]):
    if kind == "ridge":
        est = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0))
    else:
        est = make_pipeline(SimpleImputer(strategy="median"),
                            RandomForestRegressor(n_estimators=300, min_samples_leaf=3, random_state=0, n_jobs=-1))
    return est


def _fit_predict_sk(kind: str, train: pd.DataFrame, test: pd.DataFrame, crops: list[str]) -> np.ndarray:
    helper = YieldModel(crops)
    mean = train.groupby("crop")["yield_t_ha"].mean()
    y = train["yield_t_ha"] / train["crop"].map(mean)
    est = _sk_model(kind, crops).fit(helper.design(train), y)
    return np.clip(est.predict(helper.design(test)), 0, None) * test["crop"].map(mean).to_numpy(dtype=float)


def _metrics(actual: np.ndarray, pred: np.ndarray, crop_mean: np.ndarray) -> dict:
    err = pred - actual
    rel_a, rel_p = actual / crop_mean, pred / crop_mean
    ss_res = np.sum((rel_a - rel_p) ** 2)
    ss_tot = np.sum((rel_a - rel_a.mean()) ** 2)
    return {
        "mae_t_ha": float(np.mean(np.abs(err))),
        "rmse_t_ha": float(np.sqrt(np.mean(err ** 2))),
        "mape_pct": float(np.mean(np.abs(err) / np.maximum(actual, 1e-6)) * 100),
        "r2_relative": float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
    }


def cross_validate(table: pd.DataFrame, scheme: str = "year") -> tuple[dict, pd.DataFrame]:
    """Leave-one-year-out (scheme='year') or leave-one-county-out (scheme='county')."""
    key = "year" if scheme == "year" else "county_id"
    crops = sorted(table["crop"].unique())
    parts = []
    for held_out in sorted(table[key].unique()):
        train, test = table[table[key] != held_out], table[table[key] == held_out]
        test = test[test["crop"].isin(train["crop"].unique())]
        if len(train) < 30 or test.empty:
            continue
        ours = YieldModel(crops).fit(train)
        q = ours.predict(test)
        part = test[["county_id", "year", "crop", "yield_t_ha"]].copy()
        part["crop_mean"] = test["crop"].map(train.groupby("crop")["yield_t_ha"].mean()).to_numpy()
        part["baseline"] = _baseline(train, test)
        part["ridge"] = _fit_predict_sk("ridge", train, test, crops)
        part["random_forest"] = _fit_predict_sk("rf", train, test, crops)
        part["shambasense"] = q["p50"].to_numpy()
        part["p10"], part["p90"] = q["p10"].to_numpy(), q["p90"].to_numpy()
        part["fold"] = held_out
        parts.append(part)
    if not parts:
        raise RuntimeError(f"not enough data for {scheme} cross-validation")
    preds = pd.concat(parts, ignore_index=True)

    results = {}
    for name in ("baseline", "ridge", "random_forest", "shambasense"):
        results[name] = _metrics(preds["yield_t_ha"].to_numpy(), preds[name].to_numpy(), preds["crop_mean"].to_numpy())
    inside = (preds["yield_t_ha"] >= preds["p10"]) & (preds["yield_t_ha"] <= preds["p90"])
    results["shambasense"]["p10_p90_coverage_pct"] = float(inside.mean() * 100)

    # Does the model order crops correctly within each county-year? (what a recommendation needs)
    rhos = []
    for _, g in preds.groupby(["county_id", "year"]):
        if len(g) >= 3:
            rho = spearmanr(g["shambasense"] / g["crop_mean"], g["yield_t_ha"] / g["crop_mean"]).statistic
            if not np.isnan(rho):
                rhos.append(rho)
    results["shambasense"]["crop_rank_spearman"] = float(np.mean(rhos)) if rhos else float("nan")
    base_mae = results["baseline"]["mae_t_ha"]
    results["shambasense"]["mae_skill_vs_baseline_pct"] = float((1 - results["shambasense"]["mae_t_ha"] / base_mae) * 100)
    results["folds"] = int(preds["fold"].nunique())
    results["rows"] = int(len(preds))
    return results, preds


def _coverage(preds: pd.DataFrame, scale: float) -> float:
    mid = preds["shambasense"]
    lo = mid - scale * (mid - preds["p10"])
    hi = mid + scale * (preds["p90"] - mid)
    return float(((preds["yield_t_ha"] >= lo) & (preds["yield_t_ha"] <= hi)).mean() * 100)


def calibrate_interval(preds: pd.DataFrame, target_pct: float = 80.0) -> float:
    """Smallest widening factor (>= 1) that brings p10-p90 coverage up to the target."""
    for scale in np.arange(1.0, 4.01, 0.05):
        if _coverage(preds, float(scale)) >= target_pct:
            return round(float(scale), 2)
    return 4.0


def group_importance(model: YieldModel, table: pd.DataFrame, repeats: int = 20) -> dict:
    """Permutation importance of the median model, summed into feature groups."""
    df = table[table["crop"].isin(model.crop_mean)].reset_index(drop=True)
    X = model.design(df)
    y = (df["yield_t_ha"] / df["crop"].map(model.crop_mean)).to_numpy()
    est = model.models[0.5]
    res = permutation_importance(est, X, y, n_repeats=repeats, random_state=0,
                                 scoring="neg_mean_absolute_error")
    names = model.feature_names()
    per_feature = dict(zip(names, res.importances_mean.tolist()))
    groups = {g: float(sum(per_feature[c] for c in cols)) for g, cols in GROUPS.items()}
    groups["crop_type"] = float(sum(v for k, v in per_feature.items() if k.startswith("crop_")))
    return {"by_group": groups, "by_feature": per_feature}


def train_and_evaluate(table: pd.DataFrame, figures_dir: Path | None = None) -> YieldModel:
    from ..features.dataset import describe_table

    info = describe_table(table)
    if info["rows"] < 40:
        log.warning("only %d training rows; results will be unstable", info["rows"])
    evaluation, year_preds = {}, None
    for step, scheme in enumerate(("year", "county"), start=1):
        log.info("Training %d/3: testing the model on %s it has not seen…", step,
                 "years" if scheme == "year" else "counties")
        try:
            metrics, preds = cross_validate(table, scheme)
            evaluation[scheme] = metrics
            if scheme == "year":
                year_preds = preds
            if figures_dir:
                _figures(preds, metrics, scheme, figures_dir)
                preds.to_csv(figures_dir.parent / f"cv_predictions_{scheme}.csv", index=False)
        except RuntimeError as exc:
            evaluation[scheme] = {"error": str(exc)}
    log.info("Training 3/3: fitting the final model on all %d rows…", len(table))
    model = YieldModel(sorted(table["crop"].unique())).fit(table)
    if year_preds is not None:
        model.interval_scale = calibrate_interval(year_preds)
        evaluation["interval_calibration"] = {
            "scale": model.interval_scale,
            "coverage_before_pct": _coverage(year_preds, 1.0),
            "coverage_after_pct": _coverage(year_preds, model.interval_scale),
            "note": "p10-p90 widened so 80% of leave-one-year-out outcomes fall inside (calibrated on the same folds)",
        }
    importance = group_importance(model, table)
    model.meta = {
        "version": __version__,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_data": info,
        "data_quality": info["data_quality"],
        "crop_mean_t_ha": {k: round(v, 3) for k, v in model.crop_mean.items()},
        "evaluation": evaluation,
        "importance_by_group": importance["by_group"],
        "params": model.params,
    }
    if figures_dir:
        _importance_figure(importance["by_group"], figures_dir)
    return model


# =============================================================================== figures

def _figures(preds: pd.DataFrame, metrics: dict, scheme: str, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    title = "leave-one-year-out" if scheme == "year" else "leave-one-county-out"

    fig, ax = plt.subplots(figsize=(6, 5.5), dpi=150)
    for crop, g in preds.groupby("crop"):
        ax.scatter(g["yield_t_ha"] / g["crop_mean"], g["shambasense"] / g["crop_mean"], s=18, alpha=0.75, label=crop)
    lim = [0, max(2.0, float((preds["yield_t_ha"] / preds["crop_mean"]).max()) * 1.05)]
    ax.plot(lim, lim, color="#888", lw=1, ls="--")
    ax.set(xlim=lim, ylim=lim, xlabel="Actual relative yield (yield / crop average)",
           ylabel="Predicted relative yield", title=f"Predicted vs actual, {title}")
    ax.legend(fontsize=8, frameon=False)
    m = metrics["shambasense"]
    ax.text(0.03, 0.97, f"R² {m['r2_relative']:.2f} · MAE {m['mae_t_ha']:.2f} t/ha", transform=ax.transAxes,
            va="top", fontsize=9)
    fig.tight_layout()
    fig.savefig(out / f"pred_vs_actual_{scheme}.png")
    plt.close(fig)

    names = ["baseline", "ridge", "random_forest", "shambasense"]
    labels = ["County-crop\naverage", "Ridge\nregression", "Random\nforest", "ShambaSense\n(gradient boosting)"]
    vals = [metrics[n]["mape_pct"] for n in names]
    fig, ax = plt.subplots(figsize=(6.5, 4), dpi=150)
    bars = ax.bar(labels, vals, color=["#9aa5b1", "#9aa5b1", "#9aa5b1", "#2f7d4f"])
    ax.bar_label(bars, fmt="%.1f%%", fontsize=9)
    ax.set(ylabel="Mean absolute percentage error (%)", title=f"Model comparison, {title}")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / f"model_comparison_{scheme}.png")
    plt.close(fig)


def _importance_figure(groups: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    items = sorted(groups.items(), key=lambda kv: kv[1])
    fig, ax = plt.subplots(figsize=(6.5, 4), dpi=150)
    ax.barh([k.replace("_", " ") for k, _ in items], [v for _, v in items], color="#2f7d4f")
    ax.set(xlabel="Increase in error when shuffled (relative yield MAE)", title="What drives the yield predictions")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "feature_importance.png")
    plt.close(fig)


def metadata(directory: Path | None = None) -> dict | None:
    path = (directory or config.model_dir()) / META_FILE
    return json.loads(path.read_text()) if path.exists() else None
