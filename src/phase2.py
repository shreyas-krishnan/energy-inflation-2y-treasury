"""Phase 2 runner: Module A (pass-through) and Module B (walk-forward test)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import charts
from . import data_prep as dp
from . import download
from . import passthrough as pt
from . import walkforward as wf

TABLES = Path("outputs/tables")
FIGS = Path("outputs/figures")


def run(cfg: dict, offline: bool = False) -> dict:
    TABLES.mkdir(parents=True, exist_ok=True); FIGS.mkdir(parents=True, exist_ok=True)
    raw = Path(cfg["data"]["raw_dir"])
    pc, wc = cfg["passthrough"], cfg["walkforward"]
    dp.WEEKLY_LAG_DAYS = wc["weekly_availability_lag_days"]

    gas_cpi = dp.load_fred(raw, pc["y_series"])
    weekly = dp.load_fred(raw, pc["x_series"]).dropna()
    headline_nsa = dp.load_fred(raw, "CPIAUCNS")
    releases = dp.load_release_dates(raw)
    months = pd.date_range("1990-01-01", gas_cpi.dropna().index.max(), freq="MS")
    avail = dp.cpi_availability(months, releases)

    # --- Real-time integrity checks (network) ---
    if not offline:
        rev = download.revision_check(raw, [pc["y_series"], pc["x_series"], "CUSR0000SETB01"], wc["revision_vintages"])
        rev.to_csv(TABLES / "phase2_revision_check.csv", index=False)
        ac = download.availability_check(raw, avail, wc["availability_spot_checks"])
        ac.to_csv(TABLES / "phase2_availability_check.csv", index=False)
        if (ac["ok"] == False).any():  # noqa: E712  (None = vintage unavailable)
            raise RuntimeError(f"CPI availability rule failed ALFRED check:\n{ac}")

    # --- Module A ---
    start = pd.Timestamp(pc["sample_start"])
    gas_m = dp.monthly_avg(weekly)
    gas_m = gas_m[gas_m.index >= start]
    last_cpi = gas_cpi.dropna().index.max()
    x = dp.dlog(gas_m)
    x = x[x.index <= last_cpi]
    y = dp.dlog(gas_cpi)
    y = y[y.index >= start]

    diags, coefs = [], []
    fits = {}
    for L in (0, 1, 2):
        res, d = pt.fit_ols(y, x, L)
        fits[L] = (res, d)
        diags.append(pt.diagnostics(res, d, L))
        coefs.append(pt.coef_table(res, f"lags={L}"))
    pd.DataFrame(diags).to_csv(TABLES / "passthrough_diagnostics.csv", index=False)
    pd.concat(coefs).rename_axis("term").reset_index().to_csv(TABLES / "passthrough_coefficients.csv", index=False)

    L = pc["lags"]
    sub = []
    for lab, (a, b) in {"1990-2007": ("1990-01-01", "2007-12-31"), "2008-2019": ("2008-01-01", "2019-12-31"),
                        "2020-2026": ("2020-01-01", "2026-12-31")}.items():
        r, d = pt.fit_ols(y[a:b], x, L)
        row = {"subsample": lab, "n": int(r.nobs), "r2": r.rsquared,
               "resid_sd_pp": float(r.resid.std())}
        for l in range(L + 1):
            row[f"b{l}"] = r.params[f"x_lag{l}"]; row[f"se_b{l}"] = r.bse[f"x_lag{l}"]
        row["sum_b"] = sum(r.params[f"x_lag{l}"] for l in range(L + 1))
        sub.append(row)
    pd.DataFrame(sub).to_csv(TABLES / "passthrough_subsamples.csv", index=False)

    ri = cfg["data"]["relative_importance_dec2025"]["gasoline_all_types"]
    contrib = pt.contribution_table(ri, gas_cpi, headline_nsa)
    contrib.to_csv(TABLES / "gasoline_contribution_2026.csv", index=False)

    res, d = fits[L]
    charts.gas_vs_cpi(gas_m, gas_cpi, FIGS / "gasoline_vs_cpi_gasoline.png")
    charts.passthrough_fit(d["y"], res.fittedvalues, res.rsquared,
                           {f"b{l} (lag {l})": res.params[f'x_lag{l}'] for l in range(L + 1)},
                           FIGS / "passthrough_fit.png")

    # --- Module B ---
    fc = wf.run(gas_cpi, weekly, avail, wc["eval_start"], pc["sample_start"], L, wc["horizons"], wc["min_train_months"])
    fc.to_csv(TABLES / "walkforward_forecasts.csv", index=False)
    mets = [wf.evaluate(fc, "all")]
    for lab, (a, b) in wc["subperiods"].items():
        mets.append(wf.evaluate(fc[(fc["origin"] >= a) & (fc["origin"] <= b)], lab))
    metrics = pd.concat(mets, ignore_index=True)
    metrics.to_csv(TABLES / "walkforward_metrics.csv", index=False)

    ev = fc.dropna(subset=["actual"]).copy()
    ev["err_model"] = ev["actual"] - ev["model"]
    worst = ev.loc[ev["err_model"].abs().sort_values(ascending=False).index]
    worst = worst[worst["h"].isin([1, 3])].groupby("h").head(8)
    worst[["origin", "last_cpi_month", "target_month", "h", "actual", "model", "retail_1to1", "err_model"]] \
        .to_csv(TABLES / "walkforward_worst_errors.csv", index=False)
    charts.forecast_errors(metrics, FIGS / "forecast_errors_vs_benchmarks.png")

    # Post-hoc diagnostic (NOT used to choose the model): same test without month dummies,
    # to see whether the seasonal terms explain the gap to the retail 1:1 rule.
    fc_nd = wf.run(gas_cpi, weekly, avail, wc["eval_start"], pc["sample_start"], L, wc["horizons"],
                   wc["min_train_months"], dummies=False)
    m_nd = wf.evaluate(fc_nd, "all")
    diag = metrics[metrics["period"] == "all"][["h", "rmse_model", "rmse_retail_1to1"]].merge(
        m_nd[["h", "rmse_model"]].rename(columns={"rmse_model": "rmse_model_no_dummies"}), on="h")
    # in-sample bias check at h=1: mean error of each forecast
    ev1 = fc[fc["h"] == 1].dropna(subset=["actual"])
    ev1nd = fc_nd[fc_nd["h"] == 1].dropna(subset=["actual"])
    diag["note"] = "post-hoc diagnostic; not used for model selection"
    diag.to_csv(TABLES / "walkforward_posthoc_no_dummies.csv", index=False)
    bias = pd.DataFrame({"forecast": ["model", "model_no_dummies", "retail_1to1"],
                         "mean_error_h1_pp": [(ev1["actual"] - ev1["model"]).mean(),
                                              (ev1nd["actual"] - ev1nd["model"]).mean(),
                                              (ev1["actual"] - ev1["retail_1to1"]).mean()]})
    bias.to_csv(TABLES / "walkforward_bias_h1.csv", index=False)
    # Live nowcast as of the project date: a falsifiable call on the next CPI release.
    asof = pd.Timestamp(cfg["project"]["as_of_date"])
    info = dp.information_set(asof, gas_cpi, avail, weekly)
    now = wf.forecast_at_origin(info, L, wc["horizons"], wc["min_train_months"], pc["sample_start"])
    w_last = pt.updated_weight(ri, gas_cpi, headline_nsa).dropna().iloc[-1]
    now = now[["origin", "last_cpi_month", "target_month", "h", "model", "retail_1to1", "seasonal"]].copy()
    now["model_mom_pct"] = 100 * (np.exp(now["model"].diff().fillna(now["model"]) / 100) - 1)
    now["retail_1to1_mom_pct"] = 100 * (np.exp(now["retail_1to1"].diff().fillna(now["retail_1to1"]) / 100) - 1)
    now["approx_headline_contribution_pp_model"] = w_last / 100 * now["model_mom_pct"]
    now["weekly_data_through"] = info.weekly_gas.index.max().date()
    now["gas_weight_used_pct"] = w_last
    now.head(2).to_csv(TABLES / "nowcast_asof.csv", index=False)

    return {"metrics": metrics, "diagnostics": pd.DataFrame(diags), "subsamples": pd.DataFrame(sub),
            "contribution": contrib, "forecasts": fc}
