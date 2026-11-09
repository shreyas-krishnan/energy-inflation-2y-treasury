"""Phase 3 runner: Module C (headline CPI scenarios) and Module D (note vs bill)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from . import charts
from . import data_prep as dp
from . import inflation as inf
from . import passthrough as pt
from . import treasury as tr

TABLES = Path("outputs/tables")
FIGS = Path("outputs/figures")
SCEN = ["falling", "stable", "rising"]   # scenarios with probabilities
REF = ["below_eia"]                       # reference path, no probability


# ---------------- Module C ----------------
def run_inflation(cfg: dict, raw: Path) -> dict:
    ci = cfg["inflation"]
    ri = cfg["data"]["relative_importance_dec2025"]
    idx = inf.load_indexes(raw)
    w = inf.rolled_weights(idx, ri)
    r = inf.component_changes(idx, w)
    inf.aggregate_check(idx, w, r, "2026-01-01").to_csv(TABLES / "inflation_aggregation_check.csv")

    last = idx["all"].dropna().index.max()
    months = pd.date_range(last + pd.offsets.MonthBegin(1), periods=ci["horizon_months"], freq="MS")
    nongas, used = inf.nongas_paths(idx, w, r, last, months, ci)

    steo, vintage = inf.steo_monthly(raw / "web" / "eia_steo_table.xlsx", ci["steo_retail_code"])
    weekly = dp.load_fred(raw, "GASREGW").dropna()
    scen, meta = inf.gasoline_scenarios(weekly, steo, months)
    gas_hist = dp.monthly_avg(weekly)

    # Module A estimated model (full sample) for the sensitivity case
    pc = cfg["passthrough"]
    y = dp.dlog(dp.load_fred(raw, pc["y_series"]))
    x = dp.dlog(gas_hist[gas_hist.index >= pc["sample_start"]])
    beta, _ = pt.fit_numpy(y[y.index >= pc["sample_start"]], x[x.index <= last], pc["lags"])

    paths = []
    for method in [ci["passthrough_baseline"], ci["passthrough_sensitivity"]]:
        for s in SCEN + REF:
            g = inf.gas_cpi_mom(scen[s], gas_hist, method, beta, pc["lags"])
            hp = inf.headline_path(idx, w, last, months, g, nongas)
            hp["gas_cpi_mom_pct"] = 100 * g.values
            hp["retail_gas_usd"] = scen[s].values
            hp.insert(0, "scenario", s); hp.insert(1, "passthrough", method)
            paths.append(hp)
    paths = pd.concat(paths).reset_index()
    paths.to_csv(TABLES / "headline_cpi_paths.csv", index=False)

    # Core-pace sensitivity on the baseline / stable gasoline path
    sens = []
    for dpp in (-ci["core_sensitivity_pp"], 0.0, ci["core_sensitivity_pp"]):
        c2 = {**ci, "component_trend_annual_pct": {**ci["component_trend_annual_pct"],
                                                   "core": used["core"]["annual_pct"] + dpp}}
        ng2, _ = inf.nongas_paths(idx, w, r, last, months, c2)
        for s in SCEN:
            g = inf.gas_cpi_mom(scen[s], gas_hist, ci["passthrough_baseline"], beta, pc["lags"])
            hp = inf.headline_path(idx, w, last, months, g, ng2)
            sens.append({"core_annual_pct": used["core"]["annual_pct"] + dpp, "scenario": s,
                         "headline_yoy_end_pct": hp["headline_yoy_pct"].iloc[-1],
                         "end_month": hp.index[-1].date()})
    pd.DataFrame(sens).to_csv(TABLES / "headline_core_sensitivity.csv", index=False)

    assump = [{"item": f"{c} trend (annual %)", "value": v["annual_pct"], "source": v["source"],
               "type": "ASSUMPTION"} for c, v in used.items()]
    assump += [{"item": f"{c} weight at {last:%Y-%m} (%)", "value": w.loc[last, c],
                "source": "BLS Dec-2025 relative importance rolled forward by relative prices", "type": "data"}
               for c in inf.COMPONENTS]
    assump += [{"item": "EIA STEO vintage", "value": vintage, "source": "EIA STEO table 2", "type": "data"},
               {"item": "Retail anchor month", "value": str(meta["anchor_month"]), "source": "EIA weekly (GASREGW)", "type": "data"},
               {"item": "Last weekly retail price ($/gal)", "value": meta["last_weekly_price"],
                "source": f"EIA weekly (GASREGW), week of {meta['last_weekly_date']}", "type": "data"},
               {"item": "Futures-implied gasoline path", "value": "not available",
                "source": "EIA stopped publishing NYMEX futures (file ends 2024-04-05)", "type": "data gap"}]
    pd.DataFrame(assump).to_csv(TABLES / "inflation_assumptions.csv", index=False)
    s_out = scen.copy(); s_out["steo_raw"] = steo.reindex(months).values
    s_out.to_csv(TABLES / "gasoline_scenarios.csv")

    hist_yoy = 100 * (idx["all"] / idx["all"].shift(12) - 1)
    hist_yoy[idx.index.to_series().diff(12).dt.days.gt(366).values] = np.nan
    charts.headline_scenarios(hist_yoy["2024-01-01":], paths, FIGS / "headline_cpi_scenarios.png", vintage)
    return {"paths": paths, "last_cpi": last, "vintage": vintage, "used": used, "meta": meta}


# ---------------- Module D ----------------
def _bday():
    return CustomBusinessDay(calendar=USFederalHolidayCalendar())


def _onrun(records: list[dict], pricing: pd.Timestamp, cusip: str | None) -> dict:
    if cusip:
        return next(r for r in records if r["cusip"] == cusip)
    ok = [r for r in records if pd.Timestamp(r["competitiveAuctionCloseDate"]) <= pricing]
    return max(ok, key=lambda r: r["competitiveAuctionCloseDate"])


def forward_error_history(raw: Path, start: str) -> pd.DataFrame:
    """Realized 1.5y par yield 6 months later minus the curve-implied 6m-forward 1.5y par yield.
    Month-end CMT yields (6m, 1y, 2y); 1.5y = linear interpolation. Descriptive only."""
    y = pd.concat({k: dp.load_fred(raw, s) for k, s in [("y6", "DGS6MO"), ("y1", "DGS1"), ("y2", "DGS2")]}, axis=1)
    m = y.dropna().resample("ME").last()
    m = m[m.index >= start]
    fwd = m.apply(lambda r: tr.curve_forward_par({0.5: r.y6, 1.0: r.y1, 2.0: r.y2}), axis=1)
    realized = (m["y1"] + m["y2"]) / 2
    out = pd.DataFrame({"forward": fwd, "realized_6m_later": realized.shift(-6)})
    out["error_bp"] = 100 * (out["realized_6m_later"] - out["forward"])
    return out.dropna()


def run_treasury(cfg: dict, raw: Path, infl: dict) -> dict:
    tc = cfg["treasury_trade"]
    yr = int(cfg["project"]["as_of_date"][:4])

    def _read(kind):
        parts = [pd.read_csv(f, parse_dates=["Date"]) for y in (yr - 1, yr)
                 if (f := raw / "web" / f"ust_{kind}_{y}.csv").exists() and f.stat().st_size > 0]
        return pd.concat(parts, ignore_index=True).dropna(subset=["Date"])
    curve, bills = _read("par_curve"), _read("bill_rates")
    pricing = pd.Timestamp(tc["pricing_date"]) if tc["pricing_date"] else curve["Date"].max()
    c = curve[curve["Date"] == pricing].iloc[0]
    b = bills[bills["Date"] == pricing].iloc[0]
    settle = pricing + _bday()

    note = _onrun(json.loads((raw / "treasurydirect_notes_2y.json").read_text()), pricing, tc["note_cusip"])
    bill = _onrun(json.loads((raw / "treasurydirect_bills_26w.json").read_text()), pricing, tc["bill_cusip"])
    mat = pd.Timestamp(note["maturityDate"]); cpn = float(note["interestRate"])
    horizon = pd.Timestamp(bill["maturityDate"])
    y0 = float(c["2 Yr"]); d = float(b["26 WEEKS BANK DISCOUNT"])
    days = (horizon - settle).days
    bey = tr.bill_bey(d, days)
    trade = tr.Trade(settle, horizon, cpn, mat, y0, d, bey)

    par = {0.0833: c["1 Mo"], 0.25: c["3 Mo"], 0.5: c["6 Mo"], 1.0: c["1 Yr"], 2.0: c["2 Yr"], 3.0: c["3 Yr"]}
    rem = (mat - horizon).days / 365.25
    y_roll = tr.interp_par(par, rem)
    y_be = trade.breakeven_yield()
    y_fwd = trade.forward_yield()
    y_fwd_curve = tr.curve_forward_par(par)
    rb = trade.bill_return()
    risk = tr.risk_measures(y0, settle, cpn, mat)

    hist = forward_error_history(raw, tc["rate_scenarios"]["history_start"])
    q25, q50, q75 = hist["error_bp"].quantile([.25, .5, .75])
    shift = tc["rate_scenarios"]["shift_bp"]
    shift = float((q75 - q25) / 2) if shift is None else float(shift)
    hist.to_csv(TABLES / "forward_error_history.csv")

    tp = {k: dp.load_fred(raw, k).dropna() for k in ["THREEFYTP1", "THREEFYTP2"]}
    tp_asof = {k: (v[v.index <= pricing].iloc[-1], v[v.index <= pricing].index[-1].date()) for k, v in tp.items()}

    setup = {
        "pricing_date": pricing.date(), "settlement_date": settle.date(), "horizon_date": horizon.date(),
        "holding_days": days, "note_cusip": note["cusip"], "note_coupon_pct": cpn, "note_maturity": mat.date(),
        "note_yield_pct (ASSUMPTION: Treasury 2Y par yield)": y0,
        "note_clean_price": tr.clean_price(y0, settle, cpn, mat), "note_accrued": tr.accrued(settle, cpn, mat),
        "note_dirty_price": trade.start_dirty(), **{f"note_{k}": v for k, v in risk.items() if k != "dirty_price"},
        "bill_cusip": bill["cusip"], "bill_maturity": horizon.date(), "bill_bank_discount_pct": d,
        "bill_price": tr.bill_price(d, days), "bill_bey_pct": bey,
        "treasury_published_26wk_coupon_equiv_pct": float(b["26 WEEKS COUPON EQUIVALENT"]),
        "bill_hpr_pct": 100 * rb, "remaining_maturity_at_horizon_yrs": rem,
        "rolldown_yield_pct (curve unchanged)": y_roll,
        "breakeven_yield_pct": y_be, "forward_yield_pct (note financed at bill)": y_fwd,
        "curve_forward_1p5y_par_pct (bootstrapped par curve)": y_fwd_curve,
        "note_hpr_if_curve_unchanged_pct": 100 * trade.note_return(y_roll),
        "hist_forward_error_bp_q25": q25, "hist_forward_error_bp_median": q50, "hist_forward_error_bp_q75": q75,
        "hist_forward_error_bp_mean": hist["error_bp"].mean(), "hist_forward_error_n_months": len(hist),
        "scenario_shift_bp (ASSUMPTION)": shift,
        "kim_wright_tp_1y_pct": tp_asof["THREEFYTP1"][0], "kim_wright_tp_2y_pct": tp_asof["THREEFYTP2"][0],
        "kim_wright_asof": tp_asof["THREEFYTP2"][1],
        "effr_pct": dp.load_fred(raw, "DFF").dropna().loc[:pricing].iloc[-1],
    }
    pd.Series(setup, name="value").to_csv(TABLES / "treasury_trade_setup.csv", header=True)

    sens = []
    for bp in tc["sensitivity_bp"]:
        ye = y_roll + bp / 100
        rn = trade.note_return(ye)
        sens.append({"yield_change_vs_rolldown_bp": bp, "horizon_yield_pct": ye, "note_hpr_pct": 100 * rn,
                     "bill_hpr_pct": 100 * rb, "excess_pct": 100 * (rn - rb),
                     "excess_annualized_pct": tr.annualize(rn - rb, days)})
    sens = pd.DataFrame(sens)
    sens.to_csv(TABLES / "treasury_sensitivity.csv", index=False)
    # Same calculation on a 5 bp grid, for the interactive explorer on the project website
    curve = []
    for bp in range(-100, 130, 5):
        ye = y_roll + bp / 100
        rn = trade.note_return(ye)
        curve.append({"yield_change_vs_rolldown_bp": bp, "horizon_yield_pct": ye, "note_hpr_pct": 100 * rn,
                      "bill_hpr_pct": 100 * rb, "excess_pct": 100 * (rn - rb)})
    pd.DataFrame(curve).to_csv(TABLES / "treasury_return_curve.csv", index=False)

    probs = tc["probabilities"]
    if abs(sum(probs.values()) - 1) > 1e-6:
        raise ValueError("scenario probabilities must sum to 1")
    paths = infl["paths"]
    base = paths[paths["passthrough"] == cfg["inflation"]["passthrough_baseline"]]
    rows = []
    for mname, mp in tc["rate_scenarios"]["mappings"].items():
        mrows = []
        for s in SCEN + REF:
            ye = y_fwd + mp[s] * shift / 100
            rn = trade.note_return(ye)
            hp = base[base["scenario"] == s]
            mrows.append({"mapping": mname, "scenario": s, "probability": probs.get(s, np.nan),
                          "shift_vs_forward_bp": mp[s] * shift,
                          "headline_yoy_end_pct": hp["headline_yoy_pct"].iloc[-1],
                          "retail_gas_end_usd": hp["retail_gas_usd"].iloc[-1],
                          "horizon_1p5y_yield_pct (ASSUMPTION)": ye, "note_hpr_pct": 100 * rn,
                          "bill_hpr_pct": 100 * rb, "excess_pct": 100 * (rn - rb),
                          "excess_annualized_pct": tr.annualize(rn - rb, days)})
        m = pd.DataFrame(mrows)
        p = m[m["scenario"].isin(SCEN)]
        e_note = (p["probability"] * p["note_hpr_pct"]).sum()
        mrows.append({"mapping": mname, "scenario": "probability-weighted", "probability": 1.0,
                      "note_hpr_pct": e_note, "bill_hpr_pct": 100 * rb, "excess_pct": e_note - 100 * rb,
                      "excess_annualized_pct": (e_note - 100 * rb) * 365 / days})
        # probability on the falling (EIA) path needed for zero expected excess, holding the
        # stable:rising ratio fixed
        ex = p.set_index("scenario")["excess_pct"]
        pr = p.set_index("scenario")["probability"]
        other = pr[["stable", "rising"]] / pr[["stable", "rising"]].sum()
        ex_other = float((other * ex[["stable", "rising"]]).sum())
        q = ex_other / (ex_other - ex["falling"]) if ex_other != ex["falling"] else np.nan
        mrows[-1]["p_falling_for_zero_excess"] = q if 0 <= q <= 1 else np.nan
        rows += mrows
    sc = pd.DataFrame(rows)
    refs = []
    for lab, ye in [("reference: curve unchanged (roll-down)", y_roll),
                    ("reference: forward + historical median error", y_fwd + q50 / 100),
                    ("reference: forward + historical mean error", y_fwd + hist["error_bp"].mean() / 100)]:
        rn = trade.note_return(ye)
        refs.append({"mapping": "reference", "scenario": lab, "horizon_1p5y_yield_pct (ASSUMPTION)": ye, "note_hpr_pct": 100 * rn,
                     "bill_hpr_pct": 100 * rb, "excess_pct": 100 * (rn - rb),
                     "excess_annualized_pct": tr.annualize(rn - rb, days)})
    sc = pd.concat([sc, pd.DataFrame(refs)], ignore_index=True)
    sc.to_csv(TABLES / "treasury_scenarios.csv", index=False)

    # Conditional entry level: the 2-year purchase yield at which the probability-weighted edge
    # under each view reaches the minimum edge, holding that view's scenario horizon yields
    # (absolute levels) and the bill fixed. I.e. "how much cheaper must the note get, with the
    # gasoline outlook unchanged?"
    min_edge = cfg["recommendation"]["min_edge_pct"] / 100
    entry = {}
    for mname, mp in tc["rate_scenarios"]["mappings"].items():
        y_abs = {s: y_fwd + mp[s] * shift / 100 for s in SCEN}

        def edge(y_buy, y_abs=y_abs):
            t2 = tr.Trade(settle, horizon, cpn, mat, y_buy, d, bey)
            return sum(probs[s] * t2.note_return(y_abs[s]) for s in SCEN) - rb - min_edge
        try:
            entry[mname] = tr.brentq(edge, y0 - 3, y0 + 3, xtol=1e-9)
        except ValueError:
            entry[mname] = np.nan
    setup["entry_2y_yield_hypothesis_pct"] = entry.get("hypothesis")
    setup["entry_2y_yield_consensus_pct"] = entry.get("consensus")
    setup["min_edge_pct (ASSUMPTION)"] = 100 * min_edge
    pd.Series(setup, name="value").to_csv(TABLES / "treasury_trade_setup.csv", header=True)

    charts.note_vs_bill(trade, y_roll, y_be, y_fwd, sc, FIGS / "note_vs_bill_by_scenario.png",
                        f"{note['cusip']} {cpn}% {mat:%b %Y} vs 26-week bill {bill['cusip']}; settle {settle:%Y-%m-%d}, horizon {horizon:%Y-%m-%d}")
    return {"setup": setup, "sensitivity": sens, "scenarios": sc}


def run(cfg: dict) -> dict:
    TABLES.mkdir(parents=True, exist_ok=True); FIGS.mkdir(parents=True, exist_ok=True)
    raw = Path(cfg["data"]["raw_dir"])
    infl = run_inflation(cfg, raw)
    treas = run_treasury(cfg, raw, infl)
    return {"inflation": infl, "treasury": treas}
