"""Single source of truth for every number the memo, deck and resume bullets use.

`collect` reads the model's output tables and returns a flat dict. `snapshot` stores it under
outputs/history/ and writes outputs/changes_since_last_run.md against the previous snapshot.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

T = Path("outputs/tables")
HIST = Path("outputs/history")


def _f(x):
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    try:
        v = float(x)
        return None if np.isnan(v) else v
    except (TypeError, ValueError):
        return x


def recommend(edge_consensus_pct: float, min_edge_pct: float) -> tuple[str, str]:
    """Buy only if the probability-weighted edge clears the minimum under the conservative view
    that the market has already priced EIA's gasoline forecast."""
    if edge_consensus_pct >= min_edge_pct:
        return "BUY", "Buy the 2-year note"
    return "NO_TRADE", "No trade at current prices"


def collect(cfg: dict, p3: dict) -> dict:
    k: dict = {"as_of": cfg["project"]["as_of_date"],
               "generated_at": dt.datetime.now().isoformat(timespec="seconds")}

    # ---- latest CPI facts (BLS NSA, 12-month) ----
    from . import data_prep as dp
    raw = Path(cfg["data"]["raw_dir"])
    a = dp.load_fred(raw, "CPIAUCNS").dropna()
    core = dp.load_fred(raw, "CPILFENS").dropna()
    en = dp.load_fred(raw, "CPIENGNS").dropna()
    last = a.index.max()
    ya = last - pd.DateOffset(years=1)
    k["latest_cpi_month"] = last.strftime("%Y-%m")
    k["headline_yoy_latest"] = 100 * (a[last] / a.get(ya, np.nan) - 1)
    k["core_yoy_latest"] = 100 * (core[last] / core.get(ya, np.nan) - 1)
    k["energy_yoy_latest"] = 100 * (en[last] / en.get(ya, np.nan) - 1)
    # largest monthly CPI gasoline (NSA) change in the 12 months to the latest CPI month
    gnsa = dp.load_fred(raw, "CUUR0000SETB01").dropna()
    gch = (100 * gnsa.pct_change(fill_method=None))[last - pd.DateOffset(months=11):last]
    k["gas_spike_month"] = gch.idxmax().strftime("%B %Y")
    k["gas_spike_pct"] = gch.max()
    # late-2025 base: core NSA change Sep->Nov 2025 vs the same two months a year earlier
    k["core_sep_nov_2025"] = 100 * (core[pd.Timestamp("2025-11-01")] / core[pd.Timestamp("2025-09-01")] - 1)
    k["core_sep_nov_2024"] = 100 * (core[pd.Timestamp("2024-11-01")] / core[pd.Timestamp("2024-09-01")] - 1)
    csa = dp.load_fred(raw, "CPILFESL").dropna()
    k["core_3m_ann_sa"] = 100 * ((csa.iloc[-1] / csa.iloc[-4]) ** 4 - 1)
    k["core_3m_ann_trigger"] = None  # filled below once the assumption is known

    # ---- Module A ----
    co = pd.read_csv(T / "passthrough_coefficients.csv")
    co = co[co["model"] == f"lags={cfg['passthrough']['lags']}"].set_index("term")
    dg = pd.read_csv(T / "passthrough_diagnostics.csv").set_index("lags").loc[cfg["passthrough"]["lags"]]
    for l in range(cfg["passthrough"]["lags"] + 1):
        k[f"pt_b{l}"] = co.loc[f"x_lag{l}", "coef"]
        k[f"pt_b{l}_se"] = co.loc[f"x_lag{l}", "hac_se"]
    k.update({"pt_sum": dg["sum_x_coefs"], "pt_p_sum_eq_1": dg["p_sum_eq_1"], "pt_r2": dg["r2"],
              "pt_resid_sd": dg["resid_sd_pp"], "pt_n": int(dg["n_obs"]), "pt_start": str(dg["sample_start"])[:7],
              "pt_end": str(dg["sample_end"])[:7], "pt_dw": dg["durbin_watson"], "pt_lb_p": dg["ljung_box_p"],
              "pt_bp_p": dg["breusch_pagan_p"], "pt_kurtosis": dg["kurtosis"]})
    sub = pd.read_csv(T / "passthrough_subsamples.csv").set_index("subsample")
    for lab, r in sub.iterrows():
        k[f"pt_b0_{lab}"] = r["b0"]

    # ---- Module B ----
    m = pd.read_csv(T / "walkforward_metrics.csv")
    ma = m[m["period"] == "all"].set_index("h")
    fc = pd.read_csv(T / "walkforward_forecasts.csv", parse_dates=["origin"])
    k["wf_n_origins"] = int(ma.loc[1, "n"])
    k["wf_first_origin"] = fc["origin"].min().strftime("%Y-%m")
    k["wf_last_eval_origin"] = fc.dropna(subset=["actual"])["origin"].max().strftime("%Y-%m")
    for h in (1, 2, 3, 6):
        for b in ("model", "no_change", "seasonal", "retail_1to1"):
            k[f"wf_rmse_{b}_h{h}"] = ma.loc[h, f"rmse_{b}"]
        for b in ("no_change", "seasonal", "retail_1to1"):
            k[f"wf_ratio_{b}_h{h}"] = ma.loc[h, f"rmse_ratio_vs_{b}"]
            k[f"wf_dmp_{b}_h{h}"] = ma.loc[h, f"dm_p_vs_{b}"]
    k["wf_pct_cut_vs_no_change_h1"] = 100 * (1 - ma.loc[1, "rmse_ratio_vs_no_change"])
    worst = pd.read_csv(T / "walkforward_worst_errors.csv", parse_dates=["origin", "target_month"])
    w3 = worst[worst["h"] == 3].head(3)
    k["wf_worst_h3"] = [{"target": r.target_month.strftime("%b %Y"), "error": r.err_model} for r in w3.itertuples()]
    now = pd.read_csv(T / "nowcast_asof.csv", parse_dates=["target_month"]).iloc[0]
    k["nowcast_month"] = now["target_month"].strftime("%B %Y")
    k["nowcast_gas_1to1"] = now["retail_1to1_mom_pct"]
    k["nowcast_gas_model"] = now["model_mom_pct"]
    k["nowcast_weekly_through"] = str(now["weekly_data_through"])

    # ---- Module C ----
    infl = p3["inflation"]
    k["steo_vintage"] = infl["vintage"]
    k["last_weekly_gas_date"] = str(infl["meta"]["last_weekly_date"])
    k["last_weekly_gas"] = infl["meta"]["last_weekly_price"]
    k["anchor_month"] = pd.Timestamp(infl["meta"]["anchor_month"]).strftime("%B %Y")
    k["anchor_actual_gas"] = infl["meta"]["anchor_actual_avg"]
    k["anchor_steo_gas"] = infl["meta"]["anchor_steo"]
    for c, v in infl["used"].items():
        k[f"assume_{c}_pct"] = v["annual_pct"]
    k["core_3m_ann_trigger"] = k["assume_core_pct"] + cfg["triggers"]["core_3m_ann_excess_pp"]
    paths = infl["paths"]
    base = paths[paths["passthrough"] == cfg["inflation"]["passthrough_baseline"]]
    mod = paths[paths["passthrough"] == cfg["inflation"]["passthrough_sensitivity"]]
    end = pd.Timestamp(base["month"].max())
    k["path_end_month"] = end.strftime("%B %Y")
    k["path_first_month"] = pd.Timestamp(base["month"].min()).strftime("%B %Y")
    for s in ["falling", "stable", "rising", "below_eia"]:
        b = base[base["scenario"] == s].set_index("month")
        k[f"gas_end_{s}"] = b["retail_gas_usd"].iloc[-1]
        k[f"yoy_end_{s}"] = b["headline_yoy_pct"].iloc[-1]
        k[f"yoy_peak_{s}"] = b["headline_yoy_pct"].max()
        k[f"yoy_peak_month_{s}"] = pd.Timestamp(b["headline_yoy_pct"].idxmax()).strftime("%B %Y")
        mm = mod[mod["scenario"] == s]["headline_yoy_pct"].values
        k[f"model_vs_1to1_max_pp_{s}"] = float(np.nanmax(np.abs(mm - b["headline_yoy_pct"].values)))
    k["gas_weight_pct"] = float(base["gas_weight_pct"].iloc[0])
    k["gas_10pct_headline_pp"] = k["gas_weight_pct"] / 100 * 10
    k["gas_drop_eia_pct"] = 100 * (k["gas_end_falling"] / k["anchor_actual_gas"] - 1)
    cs = pd.read_csv(T / "headline_core_sensitivity.csv")
    for s in ["falling", "stable", "rising"]:
        v = cs[cs["scenario"] == s]["headline_yoy_end_pct"]
        k[f"yoy_end_{s}_core_lo"], k[f"yoy_end_{s}_core_hi"] = v.min(), v.max()
    k["core_sens_pp"] = cfg["inflation"]["core_sensitivity_pp"]

    # ---- Module D ----
    st = pd.read_csv(T / "treasury_trade_setup.csv", index_col=0)["value"]
    g = lambda key: _f(st[key])  # noqa: E731
    k.update({
        "pricing_date": st["pricing_date"], "settlement_date": st["settlement_date"],
        "horizon_date": st["horizon_date"], "holding_days": int(float(st["holding_days"])),
        "note_cusip": st["note_cusip"], "note_coupon": g("note_coupon_pct"), "note_maturity": st["note_maturity"],
        "y0": g("note_yield_pct (ASSUMPTION: Treasury 2Y par yield)"), "note_clean": g("note_clean_price"),
        "note_dirty": g("note_dirty_price"), "mod_dur": g("note_modified_duration"), "convexity": g("note_convexity"),
        "bill_cusip": st["bill_cusip"], "bill_discount": g("bill_bank_discount_pct"), "bill_bey": g("bill_bey_pct"),
        "bill_bey_published": g("treasury_published_26wk_coupon_equiv_pct"), "bill_hpr": g("bill_hpr_pct"),
        "breakeven": g("breakeven_yield_pct"), "forward": g("forward_yield_pct (note financed at bill)"),
        "curve_forward": g("curve_forward_1p5y_par_pct (bootstrapped par curve)"),
        "rolldown": g("rolldown_yield_pct (curve unchanged)"), "note_hpr_unchanged": g("note_hpr_if_curve_unchanged_pct"),
        "hist_err_q25": g("hist_forward_error_bp_q25"), "hist_err_med": g("hist_forward_error_bp_median"),
        "hist_err_q75": g("hist_forward_error_bp_q75"), "hist_err_mean": g("hist_forward_error_bp_mean"),
        "hist_err_n": int(float(st["hist_forward_error_n_months"])), "shift_bp": g("scenario_shift_bp (ASSUMPTION)"),
        "tp1": g("kim_wright_tp_1y_pct"), "tp2": g("kim_wright_tp_2y_pct"), "tp_asof": st["kim_wright_asof"],
        "effr": g("effr_pct"), "entry_hyp": g("entry_2y_yield_hypothesis_pct"),
        "entry_cons": g("entry_2y_yield_consensus_pct"), "min_edge": g("min_edge_pct (ASSUMPTION)"),
    })
    k["priced_rise_bp"] = 100 * (k["forward"] - k["rolldown"])
    k["unchanged_excess"] = k["note_hpr_unchanged"] - k["bill_hpr"]
    sc = pd.read_csv(T / "treasury_scenarios.csv")
    for _, r in sc.iterrows():
        tag = {"hypothesis": "hyp", "consensus": "cons"}.get(r["mapping"])
        if tag:
            key = r["scenario"].replace("probability-weighted", "expected")
            k[f"x_{tag}_{key}"] = r["excess_pct"]
            if key == "expected":
                k[f"x_{tag}_expected_ann"] = r["excess_annualized_pct"]
                k[f"note_hpr_{tag}_expected"] = r["note_hpr_pct"]
            else:
                k[f"y_{tag}_{key}"] = r["horizon_1p5y_yield_pct (ASSUMPTION)"]
        elif "historical mean" in str(r["scenario"]):
            k["x_hist_mean"] = r["excess_pct"]
        elif "historical median" in str(r["scenario"]):
            k["x_hist_median"] = r["excess_pct"]
    k["probabilities"] = cfg["treasury_trade"]["probabilities"]
    sens = pd.read_csv(T / "treasury_sensitivity.csv")
    k["sens_per_25bp"] = float(abs(sens["note_hpr_pct"].diff().mean()))

    k["rec_code"], k["rec_short"] = recommend(k["x_cons_expected"], k["min_edge"])
    return {key: _f(v) if not isinstance(v, (list, dict, str)) else v for key, v in k.items()}


DATA_KEYS = ["latest_cpi_month", "steo_vintage", "last_weekly_gas_date", "pricing_date", "tp_asof"]
WATCH = {  # key: (label, threshold for "material" change)
    "rec_short": ("Recommendation", None), "headline_yoy_latest": ("Latest headline CPI y/y, %", 0.05),
    "nowcast_gas_1to1": ("Next CPI gasoline nowcast (1:1), % m/m", 0.5), "last_weekly_gas": ("Latest weekly gasoline, $", 0.03),
    "gas_end_falling": ("EIA-path gasoline at path end, $", 0.03), "yoy_end_falling": ("Headline y/y at path end, falling, %", 0.05),
    "yoy_end_stable": ("Headline y/y at path end, stable, %", 0.05), "y0": ("2-year yield, %", 0.02),
    "breakeven": ("Breakeven = forward, %", 0.02), "bill_hpr": ("Bill 6-month return, %", 0.02),
    "priced_rise_bp": ("Rise priced vs unchanged curve, bp", 3), "x_hyp_expected": ("Expected edge, flat-gas view, %", 0.05),
    "x_cons_expected": ("Expected edge, EIA-priced view, %", 0.05), "entry_cons": ("Entry 2-year yield, EIA-priced view, %", 0.03),
}


def snapshot(k: dict) -> str:
    HIST.mkdir(parents=True, exist_ok=True)
    prev_files = sorted(HIST.glob("key_numbers_*.json"))
    prev = json.loads(prev_files[-1].read_text()) if prev_files else None
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    (HIST / f"key_numbers_{stamp}.json").write_text(json.dumps(k, indent=1, default=str))
    Path("outputs/key_numbers.json").write_text(json.dumps(k, indent=1, default=str))

    lines = [f"# Changes since last run", "", f"Run: {k['generated_at']} (data as of {k['as_of']})", ""]
    if prev is None:
        lines += ["First snapshot - nothing to compare yet."]
    else:
        lines += [f"Previous run: {prev.get('generated_at')}", "", "## New data", ""]
        new = [f"- {key}: {prev.get(key)} -> {k.get(key)}" for key in DATA_KEYS if prev.get(key) != k.get(key)]
        lines += new or ["- No new releases since the previous run."]
        lines += ["", "## Material changes in results", ""]
        ch = []
        for key, (lab, thr) in WATCH.items():
            a, b = prev.get(key), k.get(key)
            if thr is None:
                if a != b:
                    ch.append(f"- **{lab}: {a} -> {b}**")
            elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(b - a) >= thr:
                ch.append(f"- {lab}: {a:.3f} -> {b:.3f} ({b - a:+.3f})")
        lines += ch or ["- None above the thresholds in src/key_numbers.py (WATCH)."]
    txt = "\n".join(lines) + "\n"
    Path("outputs/changes_since_last_run.md").write_text(txt)
    return txt
