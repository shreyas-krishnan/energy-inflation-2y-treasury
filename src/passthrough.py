"""Module A: retail gasoline -> CPI gasoline pass-through.

Model (NSA data on both sides, calendar-month dummies):
    y_t = a_{month(t)} + sum_{l=0..L} b_l * x_{t-l} + e_t
    y_t = 100 * dlog(CPI gasoline, all types, NSA)       [BLS CUUR0000SETB01]
    x_t = 100 * dlog(monthly avg of EIA weekly regular retail price)  [GASREGW]

Why NSA + dummies: no SA retail-price series exists, so SA-on-both-sides is impossible
without seasonally adjusting x ourselves; and SA gasoline CPI is revised for five years each
February (up to 15 index points in ALFRED), while NSA CPI and GASREGW are never revised. NSA
keeps the real-time test honest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
from statsmodels.stats.stattools import durbin_watson, jarque_bera


def design(y: pd.Series | None, x: pd.Series, lags: int, dummies: bool = True) -> pd.DataFrame:
    """Regressors: x_t..x_{t-L} plus 11 month dummies (Jan = base) and a constant."""
    x = x.asfreq("MS")  # regular monthly index so shift(l) is a true calendar lag
    X = pd.DataFrame({f"x_lag{l}": x.shift(l) for l in range(lags + 1)}, index=x.index)
    if dummies:
        for k in range(2, 13):  # explicit Feb..Dec dummies (January = base), stable for any span
            X[f"m_{k}"] = (x.index.month == k).astype(float)
    X.insert(0, "const", 1.0)
    if y is not None:
        X = X.join(y.rename("y"), how="inner")
    return X


def fit_ols(y: pd.Series, x: pd.Series, lags: int):
    d = design(y, x, lags).dropna()
    res = sm.OLS(d["y"], d.drop(columns="y")).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    return res, d


def fit_numpy(y: pd.Series, x: pd.Series, lags: int, dummies: bool = True) -> tuple[pd.Series, pd.Series]:
    """Fast point estimates for the walk-forward loop. Returns (coefficients, training y)."""
    d = design(y, x, lags, dummies).dropna()
    Xm = d.drop(columns="y")
    beta, *_ = np.linalg.lstsq(Xm.values, d["y"].values, rcond=None)
    return pd.Series(beta, index=Xm.columns), d["y"]


def predict(beta: pd.Series, x: pd.Series, months: pd.DatetimeIndex, lags: int) -> pd.Series:
    X = design(None, x, lags, dummies=any(c.startswith("m_") for c in beta.index)).reindex(months)
    X = X.reindex(columns=beta.index, fill_value=0.0)
    return X @ beta


def diagnostics(res, d: pd.DataFrame, lags: int) -> dict:
    resid = res.resid
    lb = acorr_ljungbox(resid, lags=[12], return_df=True)
    bp = het_breuschpagan(resid, d.drop(columns="y"))
    jb = jarque_bera(resid)
    xcols = [f"x_lag{l}" for l in range(lags + 1)]
    sum_test = res.t_test(" + ".join(xcols) + " = 1")
    return {
        "lags": lags, "n_obs": int(res.nobs),
        "sample_start": d.index.min().date(), "sample_end": d.index.max().date(),
        "r2": res.rsquared, "adj_r2": res.rsquared_adj, "bic": res.bic,
        "resid_sd_pp": float(np.std(resid, ddof=len(res.params))),
        "sum_x_coefs": float(res.params[xcols].sum()),
        "p_sum_eq_1": float(sum_test.pvalue),
        "durbin_watson": float(durbin_watson(resid)),
        "ljung_box_q12": float(lb["lb_stat"].iloc[0]), "ljung_box_p": float(lb["lb_pvalue"].iloc[0]),
        "breusch_pagan_p": float(bp[1]),
        "jarque_bera": float(jb[0]), "jarque_bera_p": float(jb[1]), "skew": float(jb[2]), "kurtosis": float(jb[3]),
    }


def coef_table(res, label: str) -> pd.DataFrame:
    t = pd.DataFrame({"coef": res.params, "hac_se": res.bse, "t": res.tvalues, "p": res.pvalues})
    t.insert(0, "model", label)
    return t


def updated_weight(ri_dec: float, g: pd.Series, a: pd.Series, base: str = "2025-12-01") -> pd.Series:
    """BLS relative importance updated monthly for relative price change since December base."""
    b = pd.Timestamp(base)
    g, a = g[g.index >= b], a[a.index >= b]
    return ri_dec * (g / g[b]) / (a / a[b])


def contribution_table(ri_dec: float, g_nsa: pd.Series, a_nsa: pd.Series, base: str = "2025-12-01") -> pd.DataFrame:
    """Gasoline contribution (pp) to the NSA headline monthly change, months after the base."""
    w = updated_weight(ri_dec, g_nsa, a_nsa, base)
    rows = []
    months = w.index[1:]
    for m in months:
        prev = m - pd.offsets.MonthBegin(1)
        gch = 100 * (g_nsa[m] / g_nsa[prev] - 1)
        ach = 100 * (a_nsa[m] / a_nsa[prev] - 1) if pd.notna(a_nsa.get(prev)) else np.nan
        rows.append({"month": m.date(), "gas_weight_prev_pct": w[prev], "gas_cpi_nsa_mom_pct": gch,
                     "gas_contribution_pp": w[prev] / 100 * gch, "headline_nsa_mom_pct": ach})
    return pd.DataFrame(rows)
