"""Phase 4 content: memo, deck and resume bullets built ONLY from outputs/key_numbers.json and
the model's output tables. Node scripts in reports/ lay the content out as .docx and .pptx.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pandas as pd
from PIL import Image

T = Path("outputs/tables")
F = Path("outputs/figures")
BUILD = Path("outputs/build")


# ---------------- formatting ----------------
def n(x, d=2):
    return f"{x:.{d}f}"


def sg(x, d=2):
    return f"{x:+.{d}f}"


def usd(x):
    return f"${x:.2f}"


def dlong(s):
    return pd.Timestamp(s).strftime("%B %-d, %Y")


def img(path: Path, width_in: float) -> dict:
    w, h = Image.open(path).size
    return {"type": "image", "path": str(path.resolve()), "width_in": width_in, "height_in": width_in * h / w}


def view_names():
    return {"hyp": "market prices flat gasoline", "cons": "market prices EIA's forecast"}


# ---------------- memo ----------------
def memo_blocks(k: dict, cfg: dict) -> list[dict]:
    B: list[dict] = []
    P = lambda *runs: B.append({"type": "p", "runs": [r if isinstance(r, list) else [r, False] for r in runs]})  # noqa: E731
    H1 = lambda t: B.append({"type": "h1", "text": t})  # noqa: E731
    BUL = lambda items: B.append({"type": "bullets", "items": items})  # noqa: E731
    tc = cfg["triggers"]
    hz = pd.Timestamp(k["horizon_date"])
    pr = k["probabilities"]
    eq = len(set(round(v, 3) for v in pr.values())) == 1

    B.append({"type": "title", "text": "Energy Inflation and the Two-Year Treasury"})
    B.append({"type": "subtitle", "text": f"Investment memo | Data as of {dlong(k['as_of'])} | Market prices as of "
                                          f"{dlong(k['pricing_date'])} | Generated from model run {k['generated_at']}"})

    # 1
    H1("1. Recommendation and key numbers")
    B.append({"type": "callout", "title": f"Recommendation: {k['rec_short']}",
              "text": (f"Buying the 2-year note ({k['note_cusip']}, {n(k['note_coupon'], 3)}% due {dlong(k['note_maturity'])}) "
                       f"instead of the 6-month bill does not offer an attractive edge at current prices."
                       if k["rec_code"] == "NO_TRADE" else
                       f"Buy the 2-year note ({k['note_cusip']}) instead of the 6-month bill: the expected edge clears the "
                       f"{n(k['min_edge'])}% minimum even if EIA's gasoline forecast is already priced in.")})
    P(f"Held for {k['holding_days']} days from {dlong(k['settlement_date'])} to {dlong(k['horizon_date'])}, the bill returns "
      f"{n(k['bill_hpr'])}%. The note beats it only if the 1.5-year Treasury yield on {dlong(k['horizon_date'])} is below "
      f"{n(k['breakeven'])}%, which is the market's own forward rate. If the market has already priced EIA's gasoline "
      f"forecast, the probability-weighted edge is {sg(k['x_cons_expected'])}% ({sg(k['x_cons_expected_ann'])}% annualized). "
      f"Even if the market prices flat gasoline, it is {sg(k['x_hyp_expected'])}%.")
    if k["rec_code"] == "NO_TRADE":
        P(["Conditional entry. ", True], "Switch from the bill to the note if either of these happens:")
        BUL([f"The 2-year yield rises to {n(k['entry_cons'])}% or higher (now {n(k['y0'])}%) with the gasoline outlook "
             f"unchanged. At that price the expected edge reaches the {n(k['min_edge'])}% minimum even if EIA's forecast "
             f"is priced in.",
             f"Retail gasoline averages at least {tc['gas_below_eia_pct']}% below EIA's path for a full month while the "
             f"2-year yield has not fallen. That is evidence for the below-EIA path, where the note beats the bill by "
             f"{sg(k['x_cons_below_eia'])}% under the same view."])
    rows = [
        ["6-month bill return", f"{n(k['bill_hpr'])}%", f"Bill {k['bill_cusip']}: {n(k['bill_discount'])}% discount, "
                                                         f"{n(k['bill_bey'])}% bond-equivalent"],
        [f"Breakeven 1.5-year yield, {hz:%b %Y}", f"{n(k['breakeven'])}%",
         f"Equals the market forward ({n(k['curve_forward'])}% from the full curve)"],
        ["1.5-year yield if the curve does not move", f"{n(k['rolldown'])}%",
         f"Market prices the yield {n(k['priced_rise_bp'], 0)} bp above this"],
        ["Expected edge vs bill, EIA forecast priced", f"{sg(k['x_cons_expected'])}%",
         "Equal scenario probabilities (placeholder)" if eq else "Scenario probabilities from config.yaml"],
        ["Expected edge vs bill, flat gasoline priced", f"{sg(k['x_hyp_expected'])}%", "Same probabilities"],
        ["Entry 2-year yield (EIA forecast priced)", f"{n(k['entry_cons'])}%", f"Now {n(k['y0'])}%"],
        [f"Headline CPI y/y, {k['path_end_month']}",
         f"{n(k['yoy_end_falling'], 1)} / {n(k['yoy_end_stable'], 1)} / {n(k['yoy_end_rising'], 1)}%",
         f"Falling / stable / rising gasoline (latest: {n(k['headline_yoy_latest'], 1)}%)"],
        ["1-month CPI gasoline forecast error", f"{n(k['wf_rmse_model_h1'])} pp",
         f"vs {n(k['wf_rmse_no_change_h1'])} pp for no change; {k['wf_n_origins']} real-time forecasts"],
    ]
    B.append({"type": "table", "header": ["Measure", "Value", "Note"], "rows": rows, "widths": [0.38, 0.17, 0.45]})

    # 2
    H1("2. Thesis: gasoline inflation is fading, but slowly in the data")
    P(f"Pump prices are already falling. The {k['anchor_month']} average retail price was {usd(k['anchor_actual_gas'])}, "
      f"below EIA's {usd(k['anchor_steo_gas'])} forecast for that month, and the latest weekly price is "
      f"{usd(k['last_weekly_gas'])} ({dlong(k['last_weekly_gas_date'])}). EIA's {k['steo_vintage']} outlook takes the monthly "
      f"average to {usd(k['gas_end_falling'])} by {k['path_end_month']}, a {n(abs(k['gas_drop_eia_pct']), 0)}% decline.")
    P(f"Gasoline now weighs {n(k['gas_weight_pct'])}% of the CPI, so a 10% move in pump prices moves headline inflation by "
      f"about {n(k['gas_10pct_headline_pp'])} pp. Holding core at its trailing pace of {n(k['assume_core_pct'])}%, food at "
      f"{n(k['assume_food_pct'])}% and other energy at {n(k['assume_other_energy_pct'])}% (assumptions), headline inflation "
      f"reaches {n(k['yoy_end_falling'], 1)}% by {k['path_end_month']} if gasoline follows EIA, {n(k['yoy_end_stable'], 1)}% "
      f"if it holds at today's price and {n(k['yoy_end_rising'], 1)}% if it rises as much as EIA expects it to fall. The latest "
      f"reading is {n(k['headline_yoy_latest'], 1)}% for {pd.Timestamp(k['latest_cpi_month']):%B %Y}.")
    P(f"The decline shows up late. In the stable case, year-over-year inflation peaks at {n(k['yoy_peak_stable'], 1)}% in "
      f"{k['yoy_peak_month_stable']} and falls only in {k['path_end_month']}, largely because the {k['gas_spike_month']} gasoline "
      f"jump (+{n(k['gas_spike_pct'], 1)}% in one month) drops out of the comparison. That base effect is public, so the "
      f"market sees it too. A data caveat pushes the same way: BLS never published October 2025 CPI, and core prices "
      f"changed {sg(k['core_sep_nov_2025'])}% from September to November 2025 against {sg(k['core_sep_nov_2024'])}% over "
      f"the same months a year earlier, a low base that lifts measured year-over-year inflation.")
    B.append(img(F / "headline_cpi_scenarios.png", 5.9))

    # 3
    H1("3. What the market has priced in")
    P(f"The forward rate is the market's price for the 1.5-year yield on {dlong(k['horizon_date'])}. Buying the note and "
      f"financing it at the bill rate locks in {n(k['forward'])}%, so the note beats the bill exactly when the realized yield "
      f"ends below that level: the breakeven and the forward are the same number. A cross-check from the whole par curve "
      f"gives {n(k['curve_forward'])}%.")
    P(f"Today's 2-year yield is {n(k['y0'])}%. If the curve did not move, the note would roll down to a {n(k['rolldown'])}% "
      f"yield and beat the bill by {n(k['unchanged_excess'])}%. The market instead prices the yield {n(k['priced_rise_bp'], 0)} bp "
      f"higher: some expected tightening plus a term premium. The effective fed funds rate is {n(k['effr'])}%. The Federal "
      f"Reserve Board's Kim-Wright model puts the 1-year and 2-year term premiums at {n(k['tp1'])}% and {n(k['tp2'])}% "
      f"({dlong(k['tp_asof'])}), so part of the forward is pay for bearing risk rather than an expected rate rise.")
    vn = view_names()
    P(f"Scenario yields are assumptions: the forward plus or minus steps of {n(k['shift_bp'], 0)} bp, half the interquartile "
      f"range of {k['hist_err_n']} monthly forward errors since 1990. The two views differ only in which gasoline path the "
      f"forward already contains: \"{vn['hyp']}\" puts today's price at the forward; \"{vn['cons']}\" puts EIA's path there.")
    srows = []
    for s, lab in [("below_eia", "Below EIA (reference)"), ("falling", "Falling (EIA)"), ("stable", "Stable"), ("rising", "Rising")]:
        srows.append([lab, usd(k[f"gas_end_{s}"]), f"{n(k[f'yoy_end_{s}'], 1)}%",
                      f"{n(k[f'y_hyp_{s}'])}%", f"{sg(k[f'x_hyp_{s}'])}%", f"{n(k[f'y_cons_{s}'])}%", f"{sg(k[f'x_cons_{s}'])}%"])
    srows.append(["Probability-weighted", "", "", "", f"{sg(k['x_hyp_expected'])}%", "", f"{sg(k['x_cons_expected'])}%"])
    B.append({"type": "table", "header": ["Gasoline scenario", f"Gas, {pd.Timestamp(k['path_end_month']):%b}",
                                          "Headline y/y", "Yield: flat priced", "Edge", "Yield: EIA priced", "Edge"],
              "rows": srows, "widths": [0.24, 0.1, 0.12, 0.15, 0.1, 0.17, 0.12],
              "note": "Edge = note return minus bill return over the holding period, not annualized. Yields are 1.5-year "
                      "yields at the horizon (assumptions). Below EIA has no probability."})
    P(f"History offers a small edge that has nothing to do with gasoline. The realized yield has tended to end below the "
      f"forward (median error {n(k['hist_err_med'], 0)} bp, mean {n(k['hist_err_mean'], 0)} bp), which would be worth "
      f"{sg(k['x_hist_median'])}% to {sg(k['x_hist_mean'])}% over the bill for this hold. That comes from term premium and "
      f"past easing cycles, and it reversed sharply in tightening years.")

    # 4
    H1("4. Evidence: pass-through and the walk-forward test")
    P(f"Module A regresses the monthly change in the CPI gasoline index (not seasonally adjusted) on the change in EIA's weekly "
      f"retail price averaged by month, with two lags and calendar-month dummies, {k['pt_start']} to {k['pt_end']} "
      f"({k['pt_n']} months). The same-month coefficient is {n(k['pt_b0'], 3)} (standard error {n(k['pt_b0_se'], 3)}); the lags add "
      f"{n(k['pt_b1'], 3)} and {n(k['pt_b2'], 3)}, for total pass-through of {n(k['pt_sum'], 3)} (not distinguishable from 1, "
      f"p = {n(k['pt_p_sum_eq_1'])}). R² is {n(k['pt_r2'], 3)} and the typical monthly miss is {n(k['pt_resid_sd'])} pp.")
    P(f"The fit has known flaws. Misses reverse the next month (Durbin-Watson {n(k['pt_dw'])}; Ljung-Box p = {n(k['pt_lb_p'], 3)}), "
      f"probably because BLS and EIA price on different days. Miss size varies over time (Breusch-Pagan p = {n(k['pt_bp_p'], 3)}), "
      f"so standard errors are robust to both. Big misses are more common than a normal curve predicts (kurtosis "
      f"{n(k['pt_kurtosis'], 1)}). The same-month coefficient drifts: {n(k['pt_b0_1990-2007'])}, {n(k['pt_b0_2008-2019'])} and "
      f"{n(k['pt_b0_2020-2026'])} across 1990-2007, 2008-2019 and 2020-2026.")
    P(f"Module B re-estimates the model on each of {k['wf_n_origins']} CPI release dates from {k['wf_first_origin']} to "
      f"{k['wf_last_eval_origin']}, using only data published by that morning (release dates checked against ALFRED vintages; "
      f"a test scrambles all later data and confirms the forecasts do not change).")
    wrows = []
    for h in (1, 2, 3, 6):
        star = lambda b: "*" if k[f"wf_dmp_{b}_h{h}"] < 0.05 else ""  # noqa: E731
        wrows.append([str(h), n(k[f"wf_rmse_model_h{h}"]),
                      f"{n(k[f'wf_rmse_no_change_h{h}'])} ({n(k[f'wf_ratio_no_change_h{h}'])}{star('no_change')})",
                      f"{n(k[f'wf_rmse_seasonal_h{h}'])} ({n(k[f'wf_ratio_seasonal_h{h}'])}{star('seasonal')})",
                      f"{n(k[f'wf_rmse_retail_1to1_h{h}'])} ({n(k[f'wf_ratio_retail_1to1_h{h}'])}{star('retail_1to1')})"])
    B.append({"type": "table", "header": ["Months ahead", "Model RMSE, pp", "No change (ratio)", "Seasonal no change (ratio)",
                                          "Retail 1:1 rule (ratio)"],
              "rows": wrows, "widths": [0.14, 0.17, 0.22, 0.25, 0.22],
              "note": "RMSE of the cumulative change in CPI gasoline. Ratio = model RMSE / benchmark RMSE; below 1 = model "
                      "better. * = Diebold-Mariano p < 0.05."})
    worst = "; ".join(f"{w['target']} ({sg(w['error'], 0)} pp)" for w in k["wf_worst_h3"])
    P(f"The model cuts the 1-month error by {n(k['wf_pct_cut_vs_no_change_h1'], 0)}% against a no-change forecast, but only "
      f"because it uses weekly prices already observed for the month in progress. By six months the gain is gone (ratio "
      f"{n(k['wf_ratio_no_change_h6'])}), and the seasonal benchmark wins from four months out. A simple rule, CPI gasoline "
      f"moving one-for-one with retail prices, beat the estimated model at every horizon, so the scenarios use that rule and "
      f"keep the estimated model as a sensitivity (headline paths differ by at most "
      f"{n(max(k[f'model_vs_1to1_max_pp_{s}'] for s in ['falling', 'stable', 'rising']))} pp). The largest 3-month misses "
      f"came at oil turning points: {worst}. Nothing here forecasts gasoline itself; the scenarios carry that risk.")
    P(f"Live check: with weekly prices through {dlong(k['nowcast_weekly_through'])}, the 1:1 rule puts {k['nowcast_month']} "
      f"CPI gasoline at {sg(k['nowcast_gas_1to1'], 1)}% for the month (estimated model {sg(k['nowcast_gas_model'], 1)}%).")

    # 5
    H1("5. Scenario returns and expected return vs the bill")
    P(f"The note's return falls about {n(k['sens_per_25bp'])}% for each 25 bp rise in the horizon yield (modified duration "
      f"{n(k['mod_dur'])}, convexity {n(k['convexity'])}). It is priced at {n(k['note_clean'], 3)} clean "
      f"(assumption: yield = Treasury's 2-year par yield, {n(k['y0'])}%).")
    sens = pd.read_csv(T / "treasury_sensitivity.csv")
    sens = sens[sens["yield_change_vs_rolldown_bp"].isin([-100, -50, 0, 50, 100])]
    B.append({"type": "table", "header": ["Yield change vs unchanged curve", "1.5-year yield", "Note return", "Bill return",
                                          "Edge", "Edge, annualized"],
              "rows": [[f"{int(r.yield_change_vs_rolldown_bp):+d} bp", f"{n(r.horizon_yield_pct)}%", f"{n(r.note_hpr_pct)}%",
                        f"{n(r.bill_hpr_pct)}%", f"{sg(r.excess_pct)}%", f"{sg(r.excess_annualized_pct)}%"]
                       for r in sens.itertuples()],
              "widths": [0.26, 0.15, 0.15, 0.14, 0.13, 0.17]})
    B.append(img(F / "note_vs_bill_by_scenario.png", 6.4))
    P(f"With {'equal' if eq else 'the configured'} scenario probabilities, the expected edge is {sg(k['x_hyp_expected'])}% if "
      f"the market prices flat gasoline and {sg(k['x_cons_expected'])}% if it prices EIA's forecast. The trade needs gasoline "
      f"below EIA's path ({usd(k['gas_end_below_eia'])} by {k['path_end_month']}) or a cheaper entry point.")

    # 6
    H1("6. Risks and what would invalidate the call")
    trig = pd.read_csv(T / "monitoring_triggers.csv").fillna("")
    gas_rows = trig[trig["trigger"].str.startswith("Retail gasoline")]
    keep = gas_rows.index[:2].tolist() + gas_rows.index[-1:].tolist()
    trig = trig[~trig.index.isin(gas_rows.index) | trig.index.isin(keep)]
    B.append({"type": "table", "header": ["Trigger", "Supports buying the note if", "Argues against if", "Latest"],
              "rows": trig[["trigger", "supports_note_if", "against_note_if", "current"]].values.tolist(),
              "widths": [0.24, 0.27, 0.29, 0.2], "small": True})
    BUL([f"Core momentum: core inflation is running at {n(k['core_3m_ann_sa'], 1)}% annualized over the last three months, "
         f"against the {n(k['assume_core_pct'], 1)}% assumption; above {n(k['core_3m_ann_trigger'], 1)}% the stable and "
         f"rising cases become more likely regardless of gasoline.",
         f"Oil supply: EIA's falling path depends on its oil outlook; if Brent runs ${cfg['triggers']['brent_above_steo_usd']} "
         f"or more above EIA's path, the rising case is in play.",
         "Policy reacts to core, not gasoline: a gasoline-only decline may not move the forward if core stays firm.",
         "Data quality: the missing October 2025 CPI and low late-2025 base distort year-over-year comparisons.",
         "Assumption risk: the scenario-to-yield mapping, step size and probabilities are judgment calls, and no futures "
         "data were available to anchor the gasoline path."])

    # 7
    H1("7. Monitoring plan")
    cal = pd.read_csv(T / "monitoring_calendar.csv").fillna("")
    B.append({"type": "table", "header": ["Date", "Release", "What it tests"],
              "rows": [[(pd.Timestamp(r.date).strftime("%a %b %-d, %Y") if r.date else "Recurring"), r.event, r.why]
                       for r in cal.itertuples()], "widths": [0.2, 0.38, 0.42], "small": True})
    P("Each release is picked up by rerunning the pipeline (python run_all.py). It rewrites this memo, the deck and "
      "outputs/changes_since_last_run.md, which lists new data and any change in the recommendation.")

    # 8
    B.append({"type": "pagebreak"})
    H1("8. Appendix")
    B.append({"type": "h2", "text": "Data sources"})
    man = json.loads(Path("data/raw/manifest.json").read_text())
    fred = {m["id"]: m for m in man if m["source"] == "FRED"}
    groups = [("CPI indexes (BLS via FRED)", ["CPIAUCNS", "CPIAUCSL", "CPILFENS", "CPILFESL", "CPIUFDNS", "CPIENGNS",
                                              "CUUR0000SETB01", "CUSR0000SETB01"]),
              ("Retail gasoline (EIA via FRED; BLS average price)", ["GASREGW", "APU000074714"]),
              ("Brent spot (EIA via FRED)", ["DCOILBRENTEU"]),
              ("Treasury yields, bills, SOFR, fed funds (Fed H.15 / NY Fed via FRED)", ["DGS2", "DGS1", "DGS6MO", "DTB6", "SOFR", "DFF"]),
              ("Breakevens and Kim-Wright term premiums (FRED)", ["T5YIE", "THREEFYTP1", "THREEFYTP2"])]
    drows = []
    for lab, ids in groups:
        ids = [i for i in ids if i in fred]
        last = max(str(fred[i]["last_obs"]) for i in ids)
        drows.append([lab, ", ".join(ids), last, fred[ids[0]]["retrieved"][:10]])
    other = {m["source"]: m for m in man if m["source"] not in ("FRED", "ALFRED", "BLS API v1")}
    for src, desc in [("U.S. Treasury par yield curve", "Daily par yields (home.treasury.gov)"),
                      ("U.S. Treasury daily bill rates", "26-week bank discount and coupon-equivalent rates"),
                      ("TreasuryDirect auction results", "Note and bill terms (CUSIP, coupon, maturity)"),
                      ("EIA STEO", f"Short-Term Energy Outlook, {k['steo_vintage']} (table 2)"),
                      ("ALFRED CPI release dates (release id 10)", "CPI release dates for the real-time test"),
                      ("Federal Reserve FOMC calendar", "Meeting dates")]:
        if src in other:
            drows.append([src, desc, "", other[src]["retrieved"][:10]])
    drows.append(["BLS API v1; ALFRED vintages", "NSA CPI cross-check and revision checks", "", ""])
    drows.append(["BLS relative importance", cfg["data"]["relative_importance_dec2025"]["source"], "Dec 2025",
                  cfg["data"]["relative_importance_dec2025"]["retrieved"]])
    B.append({"type": "table", "header": ["Source", "Series / contents", "Last obs.", "Retrieved"],
              "rows": drows, "widths": [0.34, 0.38, 0.14, 0.14], "small": True})
    B.append({"type": "h2", "text": "Assumptions"})
    arows = [[f"Core / food / other energy pace", f"{n(k['assume_core_pct'])}% / {n(k['assume_food_pct'])}% / "
              f"{n(k['assume_other_energy_pct'])}% a year", "Trailing 12-month change; ±"
              f"{n(k['core_sens_pp'], 1)} pp core sensitivity: {n(k['yoy_end_stable_core_lo'], 1)}-{n(k['yoy_end_stable_core_hi'], 1)}% (stable)"],
             ["Gasoline to CPI", "1:1 retail pass-through", "Estimated Module A model as sensitivity"],
             ["Gasoline scenarios", f"EIA {k['steo_vintage']} path; today's price; mirror of EIA",
              "Below-EIA path is a reference with no probability"],
             ["Note yield", f"{n(k['y0'])}% (Treasury 2-year par yield)", "No quoted price available (FedInvest blocked)"],
             ["Rate scenarios", f"Forward ± steps of {n(k['shift_bp'], 0)} bp", "Half the IQR of historical forward errors"],
             ["Probabilities", " / ".join(f"{s} {v:.2f}" for s, v in pr.items()), "Placeholder in config.yaml"],
             ["Minimum edge to buy", f"{n(k['min_edge'])}% over the hold", "Judged under the EIA-priced view"]]
    B.append({"type": "table", "header": ["Assumption", "Value", "Basis"], "rows": arows, "widths": [0.24, 0.38, 0.38], "small": True})
    B.append({"type": "h2", "text": "Method limits"})
    BUL(["Only one inflation channel is modeled (retail gasoline to CPI gasoline); core, food and other energy are assumptions.",
         "No federal funds rate forecast: rate paths are scenario assumptions anchored to Treasury forwards. SOFR and fed "
         "funds futures, and gasoline or Brent futures, were not available from free sources.",
         "The note's price is derived from Treasury's par curve, not a dealer quote; bid-ask costs are ignored.",
         "Relative-importance weights are rolled forward from December 2025; update them when BLS publishes the December "
         "2026 table (www.bls.gov blocks scripted downloads, so this is a manual step).",
         "Walk-forward results cover gasoline CPI only; the headline path has no out-of-sample test."])
    return B


# ---------------- deck ----------------
def deck_spec(k: dict, cfg: dict) -> dict:
    tc = cfg["triggers"]
    cal = pd.read_csv(T / "monitoring_calendar.csv").dropna(subset=["date"]).head(4)
    nxt = [f"{pd.Timestamp(r.date):%b %-d}: {r.event}" for r in cal.itertuples()]
    slides = [
        {"kind": "title", "title": "Will fading gasoline inflation make the 2-year note beat a 6-month bill?",
         "subtitle": f"Investment research | Market prices as of {dlong(k['pricing_date'])}",
         "stats": [[f"{n(k['bill_hpr'])}%", "6-month bill return"], [f"{n(k['breakeven'])}%", "Breakeven 1.5-year yield"],
                   [k["rec_short"], "Recommendation"]],
         "notes": f"Note {k['note_cusip']} vs bill {k['bill_cusip']}, settle {k['settlement_date']}, horizon {k['horizon_date']}."},
        {"kind": "chart", "title": f"Gasoline is fading, but headline CPI only drops in {k['path_end_month']} data",
         "image": img(F / "headline_cpi_scenarios.png", 8.0),
         "points": [f"{k['anchor_month']} pump prices averaged {usd(k['anchor_actual_gas'])}, under EIA's {usd(k['anchor_steo_gas'])}",
                    f"EIA path: {usd(k['gas_end_falling'])} by {k['path_end_month']}",
                    f"Headline y/y: {n(k['yoy_end_falling'], 1)}% (EIA) to {n(k['yoy_end_rising'], 1)}% (rising)",
                    f"Stable case first rises to {n(k['yoy_peak_stable'], 1)}% ({k['yoy_peak_month_stable']})"],
         "notes": "Core, food and other energy are assumptions (trailing 12-month pace). Sources: BLS, EIA."},
        {"kind": "ladder", "title": f"The market already prices a {n(k['priced_rise_bp'], 0)} bp rise in the 1.5-year yield",
         "steps": [[f"{n(k['rolldown'])}%", "1.5-year yield if the curve does not move"],
                   [f"{n(k['y0'])}%", "2-year yield today"],
                   [f"{n(k['breakeven'])}%", "Market forward = breakeven"]],
         "points": [f"Fed funds (effective): {n(k['effr'])}%",
                    f"Kim-Wright term premium: {n(k['tp1'])}% (1-yr), {n(k['tp2'])}% (2-yr)",
                    "The note wins only if the yield ends below the forward"],
         "notes": "Forward from the note financed at the bill; cross-checked against the bootstrapped par curve."},
        {"kind": "chart", "title": "Weekly gas prices predict next month's CPI print, not gasoline itself",
         "image": img(F / "forecast_errors_vs_benchmarks.png", 8.6),
         "points": [f"1-month error {n(k['wf_pct_cut_vs_no_change_h1'], 0)}% below no change",
                    f"6 months out: ratio {n(k['wf_ratio_no_change_h6'])}",
                    "A 1:1 rule beat the estimated model, so it is the baseline"],
         "notes": f"{k['wf_n_origins']} real-time forecasts, {k['wf_first_origin']} to {k['wf_last_eval_origin']}."},
        {"kind": "wide", "title": f"Expected edge vs the bill: {sg(k['x_hyp_expected'])}% if flat gasoline is priced, "
                                 f"{sg(k['x_cons_expected'])}% if EIA's forecast is",
         "image": img(F / "note_vs_bill_by_scenario.png", 11.6),
         "notes": "Left: market prices flat gasoline. Right: market prices EIA's forecast. Scenario yields are assumptions."},
        {"kind": "cards", "title": "What would change the call",
         "cards": [[f"Gasoline {tc['gas_below_eia_pct']}% below EIA", "For a full month, with the 2-year yield not falling: supports the note"],
                   [f"2-year yield at {n(k['entry_cons'])}%", f"Now {n(k['y0'])}%: the entry level with the outlook unchanged"],
                   [f"Core above {n(k['assume_core_pct'] + tc['core_3m_ann_excess_pp'], 1)}%", "3-month annualized core: argues against the note"],
                   [f"Brent ${tc['brent_above_steo_usd']} over EIA", "Supply disruption returns: rising-gasoline case"]],
         "notes": "Full trigger table in the memo, section 6."},
        {"kind": "close", "title": k["rec_short"],
         "points": ([f"Enter if the 2-year yield reaches {n(k['entry_cons'])}% with the gasoline outlook unchanged",
                     f"Or if gasoline runs {tc['gas_below_eia_pct']}%+ below EIA's path while yields hold",
                     f"Meanwhile the 6-month bill earns {n(k['bill_hpr'])}% to {dlong(k['horizon_date'])}"]
                    if k["rec_code"] == "NO_TRADE" else [f"Expected edge {sg(k['x_cons_expected'])}% even if EIA is priced"]),
         "next": nxt, "notes": "Rerun python run_all.py after each release."},
    ]
    return {"slides": slides, "footer": f"Data as of {k['as_of']} | Sources: BLS, EIA, FRED/ALFRED, U.S. Treasury"}


# ---------------- resume bullets ----------------
def resume_bullets(k: dict, n_tests: int) -> str:
    third = (f"Priced the on-the-run 2-year Treasury against a 6-month bill (breakeven 1.5-year yield {n(k['breakeven'])}%, "
             f"equal to the market forward) and showed an expected edge of {sg(k['x_cons_expected'])}% if EIA's gasoline "
             f"forecast is already priced; recommended no trade, with entry at a {n(k['entry_cons'])}% 2-year yield."
             if k["rec_code"] == "NO_TRADE" else
             f"Priced the on-the-run 2-year Treasury against a 6-month bill and found an expected edge of "
             f"{sg(k['x_cons_expected'])}% even with EIA's gasoline forecast priced in.")
    bl = [
        f"Built a reproducible Python pipeline (FRED/ALFRED, BLS, EIA, TreasuryDirect; {n_tests} pytest tests including a "
        f"no-look-ahead check) modeling how retail gasoline prices pass into CPI gasoline (pass-through {n(k['pt_sum'])}, "
        f"R² {n(k['pt_r2'])}, {k['pt_start'][:4]}-{k['pt_end'][:4]}).",
        f"Ran a real-time walk-forward test over {k['wf_n_origins']} CPI releases: the model cut 1-month forecast error "
        f"{n(k['wf_pct_cut_vs_no_change_h1'], 0)}% vs a no-change benchmark (RMSE {n(k['wf_rmse_model_h1'])} vs "
        f"{n(k['wf_rmse_no_change_h1'])} pp) but lost to a simple 1:1 rule at every horizon, so I adopted the simpler rule.",
        third,
    ]
    return ("# Resume bullets\n\n" + f"_Generated from the model run of {k['generated_at']}; numbers update on each run._\n\n"
            + "\n".join(f"- {b}" for b in bl) + "\n")


# ---------------- publish ----------------
def count_tests() -> int:
    out = subprocess.run(["python3", "-m", "pytest", "--collect-only", "-q", "-p", "no:warnings"],
                         capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", out)
    return int(m.group(1)) if m else 0


def publish(k: dict, cfg: dict) -> dict:
    BUILD.mkdir(parents=True, exist_ok=True)
    out_dir = Path("outputs/deliverables"); out_dir.mkdir(parents=True, exist_ok=True)
    memo = {"blocks": memo_blocks(k, cfg), "footer": f"Data as of {k['as_of']}. All figures produced by the model run "
                                                     f"of {k['generated_at']}."}
    (BUILD / "memo.json").write_text(json.dumps(memo, indent=1, default=str))
    (BUILD / "deck.json").write_text(json.dumps(deck_spec(k, cfg), indent=1, default=str))
    rb = resume_bullets(k, count_tests())
    (out_dir / "resume_bullets.md").write_text(rb)
    paths = {"memo": out_dir / "Energy_Inflation_2Y_Treasury_Memo.docx",
             "deck": out_dir / "Energy_Inflation_2Y_Treasury_Deck.pptx",
             "resume": out_dir / "resume_bullets.md"}
    for kind in ("memo", "deck"):
        r = subprocess.run(["node", f"reports/render_{kind}.js", str(BUILD / f"{kind}.json"), str(paths[kind])],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"render_{kind}.js failed:\n{r.stderr}")
        strip_zip_dirs(paths[kind])
    return paths


def strip_zip_dirs(path: Path) -> None:
    """Drop folder entries from an Office zip (Word has refused such files via co-editing services)."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist() if not i.filename.endswith("/")]
        if len(items) == len(z.infolist()):
            return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for i, data in items:
            out.writestr(i, data)
    tmp.replace(path)
