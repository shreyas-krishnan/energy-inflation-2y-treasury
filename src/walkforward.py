"""Module B: expanding-window, real-time walk-forward test of the gasoline CPI forecast.

Forecast origin = each CPI release date. At the origin the forecaster sees gasoline CPI through
the just-released month L and weekly retail gasoline prices through ~2 days before the origin.
Targets: cumulative log change in NSA gasoline CPI from month L to L+h, h = 1..6
(h = 1 is the month in progress, which is partly observed in weekly prices).

Forecasts compared:
  model     : Module A regression, re-estimated at every origin; future retail price held at
              the last observed weekly price (no-change retail assumption).
  no_change : gasoline CPI stays at its last published level (random walk; forecast = 0).
  seasonal  : no change after seasonality: each future month gets the average NSA change for
              that calendar month in the training window.
  retail_1to1 (extra, tougher benchmark): gasoline CPI moves one-for-one with the real-time
              monthly retail average, no estimated coefficients and no seasonal terms.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from . import data_prep as dp
from . import passthrough as pt

FORECASTS = ["model", "no_change", "seasonal", "retail_1to1"]


def forecast_at_origin(info: dp.InfoSet, lags: int, horizons: int, min_train: int,
                       sample_start: str, dummies: bool = True) -> pd.DataFrame | None:
    """All forecasts from one information set. Uses nothing outside `info`."""
    L = info.last_cpi_month
    cpi = info.gas_cpi
    hist_months = pd.date_range(sample_start, L, freq="MS")
    future = pd.date_range(L + pd.offsets.MonthBegin(1), periods=horizons, freq="MS")

    # Retail monthly averages: complete months from data, the rest real-time (partly filled).
    all_months = hist_months.append(future)
    gas_m = dp.realtime_monthly_gas(info.weekly_gas, all_months)
    x = dp.dlog(gas_m)
    y = dp.dlog(cpi)
    y = y[(y.index >= pd.Timestamp(sample_start)) & (y.index <= L)]

    beta, ytrain = pt.fit_numpy(y, x[x.index <= L], lags, dummies)
    if len(ytrain) < min_train:
        return None
    yhat = pt.predict(beta, x, future, lags)
    seas_means = ytrain.groupby(ytrain.index.month).mean()
    seas = pd.Series(seas_means.reindex(future.month).values, index=future)
    out = pd.DataFrame({
        "origin": info.origin, "last_cpi_month": L, "target_month": future,
        "h": np.arange(1, horizons + 1),
        "model": yhat.cumsum().values,
        "no_change": 0.0,
        "seasonal": seas.cumsum().values,
        "retail_1to1": x.reindex(future).cumsum().values,
        "n_train": len(ytrain),
        "max_weekly_date_used": info.weekly_gas.index.max(),
    })
    return out


def run(gas_cpi: pd.Series, weekly: pd.Series, avail: pd.Series, eval_start: str,
        sample_start: str, lags: int, horizons: int, min_train: int, dummies: bool = True) -> pd.DataFrame:
    origins = sorted(set(avail.dropna()[avail.dropna() >= pd.Timestamp(eval_start)]))
    frames = []
    for o in origins:
        info = dp.information_set(o, gas_cpi, avail, weekly)
        f = forecast_at_origin(info, lags, horizons, min_train, sample_start, dummies)
        if f is not None:
            frames.append(f)
    fc = pd.concat(frames, ignore_index=True)
    # Actual cumulative change (evaluation only; never passed to the forecaster).
    lvl = gas_cpi.dropna()
    base = lvl.reindex(fc["last_cpi_month"]).values
    tgt = lvl.reindex(fc["target_month"]).values
    fc["actual"] = 100 * np.log(tgt / base)
    return fc


def dm_test(e_model: np.ndarray, e_bench: np.ndarray, h: int) -> tuple[float, float]:
    """Diebold-Mariano (squared-error loss) with Harvey-Leybourne-Newbold correction.

    Negative statistic = model has lower squared error. Two-sided p-value from t(T-1).
    """
    d = e_model ** 2 - e_bench ** 2
    T = len(d)
    dbar = d.mean()
    dc = d - dbar
    gamma = [np.sum(dc[k:] * dc[:T - k]) / T for k in range(h)]
    var = (gamma[0] + 2 * sum(gamma[1:])) / T
    if var <= 0:  # fall back to Bartlett weights when the truncated estimate is non-positive
        var = (gamma[0] + 2 * sum((1 - k / h) * gamma[k] for k in range(1, h))) / T
    dm = dbar / np.sqrt(var)
    hln = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    stat = dm * hln
    p = 2 * stats.t.sf(abs(stat), df=T - 1)
    return float(stat), float(p)


def evaluate(fc: pd.DataFrame, label: str = "all") -> pd.DataFrame:
    rows = []
    for h, g in fc.dropna(subset=["actual"]).groupby("h"):
        r = {"period": label, "h": h, "n": len(g)}
        errs = {f: (g["actual"] - g[f]).values for f in FORECASTS}
        for f, e in errs.items():
            r[f"rmse_{f}"] = np.sqrt(np.mean(e ** 2))
            r[f"mae_{f}"] = np.mean(np.abs(e))
        for b in ["no_change", "seasonal", "retail_1to1"]:
            r[f"rmse_ratio_vs_{b}"] = r["rmse_model"] / r[f"rmse_{b}"]
            r[f"dm_vs_{b}"], r[f"dm_p_vs_{b}"] = dm_test(errs["model"], errs[b], int(h))
        rows.append(r)
    return pd.DataFrame(rows)
