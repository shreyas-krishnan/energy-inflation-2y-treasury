"""Project website: rebuilds docs/ from the model's outputs on every run.

Every number on the page comes from outputs/key_numbers.json or the model's output tables (the same
rule as the memo); this module only arranges and explains them. Styling and the interactive
explorer live in site/ (style.css, app.js) and are copied into docs/assets/.

    python -m src.site      # rebuild docs/ from the latest outputs without rerunning the model
"""
from __future__ import annotations

import ast
import datetime as dt
import html
import json
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import yaml

from .report import dlong, n, sg, usd

OUT = Path("outputs")
T = OUT / "tables"
F = OUT / "figures"
DELIV = OUT / "deliverables"
DOCS = Path("docs")
STATIC = Path("site")
JUNIT = OUT / "build" / "test_results.xml"
E = html.escape
SCENARIOS = ["below_eia", "falling", "stable", "rising"]
SCEN_LABEL = {"below_eia": "Below EIA (reference)", "falling": "Falling gasoline (EIA path)",
              "stable": "Stable gasoline (today's price)", "rising": "Rising gasoline (mirror of EIA)"}
SCEN_SHORT = {"below_eia": "Below EIA", "falling": "Falling", "stable": "Stable", "rising": "Rising"}
VIEWS = {"hyp": ("hypothesis", "Market prices flat gasoline"), "cons": ("consensus", "Market prices EIA's forecast")}
VIEW_SHORT = {"hyp": "Flat gasoline", "cons": "EIA's forecast"}


# ---------------------------------------------------------------- formatting
def sgm(x, d=2) -> str:
    """Signed number with a typographic minus."""
    return sg(x, d).replace("-", "−")


def tm(s, fmt="long") -> str:
    """A date wrapped in <time> (dates are shown as written by the model run)."""
    ts = pd.Timestamp(s)
    text = {"long": dlong(s), "short": ts.strftime("%a %b %-d"), "month": ts.strftime("%B %Y"),
            "med": ts.strftime("%b %-d, %Y")}[fmt]
    return f'<time datetime="{ts:%Y-%m-%d}">{text}</time>'


def run_time(iso: str) -> str:
    t = dt.datetime.fromisoformat(iso)
    tz = dt.datetime.now().astimezone().tzname() or ""
    return f'<time datetime="{iso}">{t.strftime("%B %-d, %Y at %-I:%M %p").replace("AM", "am").replace("PM", "pm")} {tz}</time>'


def ym(s) -> str:
    """'1990-12' -> December 1990, wrapped in <time>."""
    return tm(s, "month")


def cpi_month(k) -> str:
    return pd.Timestamp(k["latest_cpi_month"]).strftime("%B %Y")


# ---------------------------------------------------------------- the automated checks, in plain English
CHECK_GROUPS = [
    {"title": "No peeking at the future",
     "why": "A backtest that quietly uses data published later looks brilliant and is worthless. These checks prove "
            "every historical forecast used only what was public that morning.",
     "tests": {
         "test_availability_rule_handles_gaps_and_double_releases":
             "The CPI release-date rule copes with a month BLS skipped and a month with two releases",
         "test_realtime_monthly_gas_partial_month_fill":
             "A month still under way is completed with the latest weekly pump price",
         "test_realtime_monthly_gas_complete_month_not_filled":
             "A finished month uses only its own weekly prices, never later ones",
         "test_dlog_breaks_on_gaps": "Monthly changes are never computed across a missing month",
         "test_information_set_contains_only_published_data":
             "On five historical dates, the model sees exactly the data published by then: no more, no less",
         "test_forecast_unchanged_when_future_data_is_scrambled":
             "Replacing every not-yet-published number with garbage leaves the forecasts unchanged (five dates)",
         "test_walkforward_origins_never_precede_targets_data":
             "Every walk-forward forecast is made before the data it predicts",
     }},
    {"title": "The statistics are computed correctly",
     "why": "The pass-through estimate and the forecast comparison drive the whole inflation side, so the math is "
            "checked against simulated data with known answers and a worked example.",
     "tests": {
         "test_passthrough_recovers_known_coefficients":
             "The regression recovers known pass-through coefficients from simulated data",
         "test_predict_matches_fit_in_sample": "The fast forecasting code gives the same answer as the full regression",
         "test_contribution_uses_updated_weight": "Gasoline's contribution to inflation uses its weight as prices change",
         "test_dm_sign_and_significance":
             "The forecast-comparison test (Diebold-Mariano) picks out the better forecaster",
         "test_dm_hand_example_h1": "The same test matches a small example worked by hand",
     }},
    {"title": "Bond math matches the Treasury's own numbers",
     "why": "If the pricing code is off, every return is off. These checks tie it to real auction results and to "
            "textbook identities.",
     "tests": {
         "test_note_auction_price_matches_treasurydirect":
             "Reprices the October 2026 two-year note auction exactly as TreasuryDirect published it",
         "test_bill_auction_price_and_investment_rate":
             "Reprices the November 2026 six-month bill auction and its investment rate",
         "test_bill_bey_matches_treasury_daily_rate":
             "Reproduces Treasury's published bond-equivalent yield for the bill in this trade",
         "test_long_bill_bey_satisfies_treasury_definition":
             "Bills longer than half a year follow Treasury's special yield formula",
         "test_end_of_month_coupon_schedule": "Coupon dates follow Treasury's end-of-month rule",
         "test_par_bond_on_coupon_date_prices_at_100":
             "A bond whose yield equals its coupon is worth exactly par on a coupon date",
         "test_one_period_hand_example": "Matches a one-coupon pricing example worked by hand",
         "test_duration_matches_numerical_derivative": "Duration matches the price change from a tiny yield move",
         "test_zero_coupon_macaulay_duration_is_time_to_maturity":
             "A zero-coupon bond's duration equals its time to maturity",
     }},
    {"title": "The note-versus-bill comparison is consistent",
     "why": "The recommendation rests on comparing two returns over the same days. These checks make sure the "
            "comparison behaves the way finance theory says it must.",
     "tests": {
         "test_breakeven_equalizes_returns": "At the breakeven yield the note and the bill return exactly the same",
         "test_breakeven_equals_no_arbitrage_forward":
             "The breakeven equals the market's forward rate (within half a basis point)",
         "test_note_return_falls_as_yield_rises": "A higher yield at the horizon always means a lower note return",
         "test_note_return_includes_coupon": "The note's return includes its coupon and its pull toward par",
         "test_curve_forward_on_flat_curve_is_flat": "A flat yield curve implies a flat forward rate",
         "test_bootstrap_reprices_par_bonds": "The curve built from par yields reprices those same bonds at par",
     }},
    {"title": "The inflation arithmetic adds up",
     "why": "Headline inflation is rebuilt from its pieces, so the pieces must add back to the published index and "
            "the scenarios must be built the way they are described.",
     "tests": {
         "test_components_rebuild_headline": "Core, food, gasoline and other energy rebuild the published headline CPI",
         "test_weights_sum_to_100": "The four component weights always add up to the whole basket",
         "test_one_to_one_rule_equals_retail_change": "The 1:1 rule moves CPI gasoline exactly with pump prices",
         "test_rising_mirrors_falling_around_stable": "The rising path mirrors the falling path around today's price",
         "test_consensus_mapping_only_moves_the_anchor":
             "The two market views use the same step size and differ only in which path is priced",
         "test_below_eia_is_one_step_below_falling": "The below-EIA reference path sits one step below EIA's path",
     }},
    {"title": "Reports say only what the model found",
     "why": "The memo, deck and this page are written by code. These checks stop any number from appearing that "
            "the model did not produce, and confirm the files open.",
     "tests": {
         "test_memo_prose_uses_only_model_numbers": "Every number in the memo's text traces to the model's output",
         "test_site_text_uses_only_model_numbers": "Every number in this page's text traces to the model's output",
         "test_site_links_point_to_built_files": "Every chart, download and asset this page links to exists",
         "test_every_check_is_explained": "Every automated check is described on this page",
         "test_recommendation_rule": "The buy / no-trade rule switches exactly at the minimum edge",
         "test_change_report_flags_new_data_and_recommendation":
             "The change report flags new data and any change in the recommendation",
         "test_deliverables_are_well_formed": "The Word memo and PowerPoint deck are valid files",
     }},
    {"title": "Release calendars are read correctly",
     "why": "The watchlist depends on knowing when the next CPI, EIA outlook and Fed meeting are.",
     "tests": {
         "test_fomc_parser_ignores_footnote_dates": "Fed meeting dates are read without picking up footnote dates",
         "test_steo_next_release_parser": "EIA's next outlook date is read from its web page",
     }},
]


def described_tests() -> set[str]:
    return {t for g in CHECK_GROUPS for t in g["tests"]}


def defined_tests(test_dir: Path = Path("tests")) -> set[str]:
    out = set()
    for f in test_dir.glob("test_*.py"):
        for node in ast.parse(f.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                out.add(node.name)
    return out


def read_checks(path: Path = JUNIT) -> dict | None:
    """Parse pytest's JUnit XML from the latest run."""
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else next(root.iter("testsuite"))
    cases = []
    for tc in root.iter("testcase"):
        name = tc.get("name", "")
        base = name.split("[")[0]
        status = "passed"
        if tc.find("failure") is not None or tc.find("error") is not None:
            status = "failed"
        elif tc.find("skipped") is not None:
            status = "skipped"
        cases.append({"base": base, "name": name, "status": status})
    return {"cases": cases, "timestamp": suite.get("timestamp"),
            "passed": sum(c["status"] == "passed" for c in cases),
            "failed": sum(c["status"] == "failed" for c in cases),
            "skipped": sum(c["status"] == "skipped" for c in cases), "total": len(cases)}


# ---------------------------------------------------------------- page pieces
def section(sid: str, eyebrow: str, title: str, lede: str, body: str, static: bool = False, cls: str = "") -> str:
    st = " data-static" if static else ""
    return (f'<section class="section {cls}" id="{sid}"{st}><div class="wrap">'
            f'<header class="section-head"><p class="eyebrow">{eyebrow}</p><h2>{title}</h2>'
            + (f"<p>{lede}</p>" if lede else "") + f"</header>{body}</div></section>")


def hero(k: dict, cfg: dict) -> str:
    tc = cfg["triggers"]
    buy = k["rec_code"] == "BUY"
    if buy:
        why = (f"The expected edge of the note over the bill clears the {n(k['min_edge'])}% minimum even if the "
               f"market has already priced EIA's gasoline forecast.")
        flip = ""
    else:
        why = (f"Gasoline inflation is fading, but the bond market leaves no room to profit from it. Over the "
               f"{k['holding_days']}-day hold the bill locks in {n(k['bill_hpr'])}%. The note wins only if the "
               f"1.5-year yield on {tm(k['horizon_date'])} ends below {n(k['breakeven'])}%, and that is exactly the "
               f"market's own forward price for that yield.")
        flip = ('<div class="flip"><p class="mini-title">What would flip it to buy</p><ul>'
                f"<li>The 2-year yield rises to <strong>{n(k['entry_cons'])}%</strong> or higher (now {n(k['y0'])}%) "
                f"with the gasoline outlook unchanged.</li>"
                f"<li>Pump prices run <strong>{tc['gas_below_eia_pct']}% or more below</strong> EIA's forecast for a "
                f"full month while the 2-year yield holds.</li></ul></div>")
    return f"""
<section class="hero" id="answer">
  <div class="wrap hero-grid">
    <div class="hero-text">
      <p class="eyebrow">Student research project &middot; Updated {tm(k['as_of'])}</p>
      <h1>Will fading gasoline inflation make the 2-year Treasury note beat a 6-month bill?</h1>
      <p class="lede">The idea: if pump prices keep falling, inflation cools, yields drift lower, and a 2-year note held
      for six months out-earns a 6-month bill bought the same day. This page tests that idea with fresh public data
      every time the analysis runs, and shows its work.</p>
      <div class="hero-chips">
        <span class="chip">Latest CPI: {E(cpi_month(k))}</span>
        <span class="chip">Treasury prices from {tm(k['pricing_date'])}</span>
        <a class="chip chip--link" href="#run">How to rerun it &rarr;</a>
      </div>
    </div>
    <aside class="verdict {'verdict--buy' if buy else 'verdict--no'}" aria-label="Current answer">
      <p class="verdict-label">Current answer</p>
      <p class="verdict-text">{E(k['rec_short'])}</p>
      <p class="verdict-why">{why}</p>
      {flip}
    </aside>
  </div>
</section>
<div class="wrap stats" role="list">
  <div class="stat" role="listitem"><p class="stat-label">Bill return, locked in</p>
    <p class="stat-value">{n(k['bill_hpr'])}%</p><p class="stat-sub">{k['holding_days']} days, to {tm(k['horizon_date'])}</p></div>
  <div class="stat" role="listitem"><p class="stat-label">Breakeven 1.5-year yield</p>
    <p class="stat-value">{n(k['breakeven'])}%</p><p class="stat-sub">The note wins only below this</p></div>
  <div class="stat" role="listitem"><p class="stat-label">Expected edge of the note</p>
    <p class="stat-value">{sgm(k['x_cons_expected'])}%</p>
    <p class="stat-sub">If EIA's forecast is priced in ({sgm(k['x_hyp_expected'])}% if flat gasoline is)</p></div>
  <div class="stat" role="listitem"><p class="stat-label">2-year yield needed to buy</p>
    <p class="stat-value">{n(k['entry_cons'])}%</p><p class="stat-sub">Now {n(k['y0'])}%</p></div>
</div>"""


def insights(k: dict, cfg: dict) -> str:
    buy = k["rec_code"] == "BUY"
    items = [
        ("Pump prices pass straight through to CPI",
         f"Over {k['pt_n']} months since {k['pt_start'][:4]}, a 1% move in retail gasoline moved the CPI gasoline index "
         f"by {n(k['pt_sum'])}% within three months. That is statistically indistinguishable from one-for-one "
         f"(p = {n(k['pt_p_sum_eq_1'])}), and the fit is tight (R&sup2; {n(k['pt_r2'])})."),
        ("Gasoline inflation fades, but late",
         f"If pump prices hold at today's {usd(k['last_weekly_gas'])}, headline inflation still peaks at "
         f"{n(k['yoy_peak_stable'], 1)}% in {k['yoy_peak_month_stable']} and only falls in {k['path_end_month']}, when the "
         f"{k['gas_spike_month']} gasoline jump (+{n(k['gas_spike_pct'], 1)}% in one month) drops out of the "
         f"year-over-year comparison."),
        ("The market prices higher yields, not lower",
         f"The note beats the bill only if the 1.5-year yield ends below {n(k['breakeven'])}%, the market's forward "
         f"rate. That is {n(k['priced_rise_bp'], 0)} bp above the {n(k['rolldown'])}% it would be if the yield curve "
         f"stood still, so the note starts with a hurdle to clear."),
        ("Whether gasoline is &ldquo;priced in&rdquo; decides the call",
         f"If the market's forward assumes flat gasoline, EIA's falling path is upside and the expected edge is "
         f"{sgm(k['x_hyp_expected'])}%. If the forward already assumes EIA's path, it is {sgm(k['x_cons_expected'])}%. "
         f"The rule buys only if the edge clears {n(k['min_edge'])}% under that stricter second view"
         + (", and it does." if buy else ". It does not, so the answer is no trade.")),
        ("Core inflation is the bigger risk",
         f"Core prices rose at a {n(k['core_3m_ann_sa'], 1)}% annual pace over the last three months, above the "
         f"{n(k['assume_core_pct'], 1)}% the scenarios assume. Above {n(k['core_3m_ann_trigger'], 1)}%, the "
         f"higher-yield scenarios become more likely whatever gasoline does."),
    ]
    cards = "".join(f'<article class="insight card"><span class="num" aria-hidden="true">{i}</span>'
                    f"<h3>{t}</h3><p>{b}</p></article>" for i, (t, b) in enumerate(items, 1))
    cards += ('<article class="insight card card--cta"><h3>Want the full argument?</h3>'
              "<p>The memo walks through the thesis, the evidence and the risks; the deck is the short version.</p>"
              '<p class="cta-links"><a class="btn btn--amber" href="downloads/Energy_Inflation_2Y_Treasury_Memo.docx">'
              'Memo (Word)</a> <a class="btn btn--ghost" href="downloads/Energy_Inflation_2Y_Treasury_Deck.pptx">'
              "Deck (PowerPoint)</a></p></article>")
    return section("findings", "What we found", "Five things the data say",
                   "The short version of what the latest run found, before any of the machinery.",
                   f'<div class="insights">{cards}</div>')


def next_release(k: dict) -> str:
    cal = pd.read_csv(T / "monitoring_calendar.csv").dropna(subset=["date"])
    cal = cal[pd.to_datetime(cal["date"]) >= pd.Timestamp(k["as_of"])]
    if cal.empty:
        return "No dated releases left before the horizon."
    r = cal.iloc[0]
    return f"Next release to watch: {E(r['event'])} on {tm(r['date'])}."


def how_it_works(k: dict) -> str:
    steps = [
        ("Collect and check the data", "Are the starting numbers right?",
         "Every run downloads fresh data from FRED and ALFRED (St. Louis Fed), the BLS, EIA, the U.S. Treasury, "
         "TreasuryDirect and the Federal Reserve, stamps each file with the date it was pulled, and cross-checks the "
         "headline facts against a second source. If any download fails, the run stops instead of guessing.",
         f"Latest CPI month: {E(cpi_month(k))}. Over the past year headline CPI is up {n(k['headline_yoy_latest'], 1)}%, "
         f"core {n(k['core_yoy_latest'], 1)}% and energy {n(k['energy_yoy_latest'], 1)}% (not seasonally adjusted).",
         ["src/download.py", "src/verify.py"]),
        ("Module A &middot; Measure pass-through", "When pump prices move, how much shows up in the CPI gasoline index?",
         f"A regression of the monthly change in CPI gasoline on the monthly change in EIA's weekly retail price, with "
         f"two months of delayed effects and calendar-month effects, fitted on {k['pt_n']} months "
         f"({ym(k['pt_start'])} to {ym(k['pt_end'])}).",
         f"Total pass-through is {n(k['pt_sum'])} (p = {n(k['pt_p_sum_eq_1'])} against exactly one-for-one), with a "
         f"typical monthly miss of {n(k['pt_resid_sd'])} percentage points.",
         ["src/passthrough.py"]),
        ("Module B &middot; Test it in real time", "Would it have worked if we had run it live?",
         f"Replays history: on each of {k['wf_n_origins']} CPI release dates from {ym(k['wf_first_origin'])} to "
         f"{ym(k['wf_last_eval_origin'])}, the model is refitted using only data published by that morning, then scored "
         f"against three simple rules: no change, seasonal no change, and moving one-for-one with pump prices.",
         f"One month ahead the model's typical miss is {n(k['wf_rmse_model_h1'])} pp versus "
         f"{n(k['wf_rmse_no_change_h1'])} pp for no change, a {n(k['wf_pct_cut_vs_no_change_h1'], 0)}% cut. The plain one-for-one rule does even better "
         f"({n(k['wf_rmse_retail_1to1_h1'])} pp), so the scenarios use it.",
         ["src/walkforward.py"]),
        ("Module C &middot; Project headline inflation", "Where does headline CPI go if gasoline falls, holds or rises?",
         f"Rebuilds headline CPI from core, food, gasoline ({n(k['gas_weight_pct'], 1)}% of the basket) and other "
         f"energy. Gasoline follows three paths: EIA's {k['steo_vintage']} forecast, today's price, or a mirror-image "
         f"rise. Core, food and other energy grow at their recent pace, which is an assumption, not a forecast.",
         f"Headline CPI by {k['path_end_month']}: {n(k['yoy_end_falling'], 1)}% if gasoline falls, "
         f"{n(k['yoy_end_stable'], 1)}% if it holds, {n(k['yoy_end_rising'], 1)}% if it rises "
         f"(now {n(k['headline_yoy_latest'], 1)}%).",
         ["src/inflation.py"]),
        ("Module D &middot; Compare the note with the bill", "Given those paths, does the note beat the bill?",
         f"Prices the newest 2-year note ({k['note_cusip']}, {n(k['note_coupon'], 3)}% coupon) and 6-month bill "
         f"({k['bill_cusip']}) with Treasury's own formulas, finds the breakeven yield, and maps each gasoline path to a "
         f"yield {n(k['shift_bp'], 0)} bp apart around the market's forward. Rate paths are scenario assumptions "
         f"anchored to market prices; nothing here forecasts the Fed.",
         f"Expected edge {sgm(k['x_cons_expected'])}% if the market prices EIA's forecast and "
         f"{sgm(k['x_hyp_expected'])}% if it prices flat gasoline. Answer: {E(k['rec_short'].lower())}.",
         ["src/treasury.py", "src/phase3.py"]),
        ("Report and keep watch", "What changed, and what would change the answer?",
         "Writes the memo, the slide deck, this page and a watchlist of triggers, then compares every key number with "
         "the previous run and flags anything material.",
         next_release(k),
         ["src/monitor.py", "src/report.py", "src/site.py"]),
    ]
    lis = []
    for i, (title, q, how, found, code) in enumerate(steps, 1):
        chips = " ".join(f'<code class="code-chip">{c}</code>' for c in code)
        lis.append(f'<li class="step"><span class="step-num" aria-hidden="true">{i}</span><div class="step-body">'
                   f'<div><h3>{title}</h3><p class="q">{q}</p><p>{how}</p><p class="code-line">Code: {chips}</p></div>'
                   f'<div class="found"><p class="mini-title">What the latest run found</p><p>{found}</p></div>'
                   f"</div></li>")
    return section("how", "How the test works", "Six steps from the gas pump to the bond market",
                   "The analysis is a chain. Each link answers one question with data, and the next link builds on it. "
                   "Only one inflation channel is modeled: retail gasoline into CPI gasoline. Everything else is a "
                   "labeled assumption.",
                   f'<ol class="steps">{"".join(lis)}</ol>')


def explorer_data(k: dict) -> dict:
    cur = pd.read_csv(T / "treasury_return_curve.csv")
    sc = pd.read_csv(T / "treasury_scenarios.csv")
    ycol = next(c for c in sc.columns if c.startswith("horizon_1p5y_yield_pct"))
    pts = [{"y": r.horizon_yield_pct, "note": r.note_hpr_pct, "bill": r.bill_hpr_pct, "edge": r.excess_pct,
            "keys": ["rolldown"] if r.yield_change_vs_rolldown_bp == 0 else []} for r in cur.itertuples()]
    code = {v[0]: c for c, v in VIEWS.items()}
    for _, r in sc.iterrows():
        if r["mapping"] not in code or r["scenario"] not in SCENARIOS:
            continue
        key, y = f"{code[r['mapping']]}:{r['scenario']}", float(r[ycol])
        match = next((p for p in pts if abs(p["y"] - y) < 1e-7), None)
        if match:
            match["keys"].append(key)
        else:
            pts.append({"y": y, "note": float(r["note_hpr_pct"]), "bill": float(r["bill_hpr_pct"]),
                        "edge": float(r["excess_pct"]), "keys": [key]})
    pts.sort(key=lambda p: p["y"])
    for p in pts:
        for f in ("y", "note", "bill", "edge"):
            p[f] = round(float(p[f]), 6)
    return {"points": pts, "breakeven": k["breakeven"], "forward": k["forward"], "rolldown": k["rolldown"],
            "bill": k["bill_hpr"], "days": k["holding_days"], "horizon": dlong(k["horizon_date"]),
            "labels": {"rolldown": "Curve unchanged", **SCEN_LABEL}, "short": {"rolldown": "Unchanged", **SCEN_SHORT},
            "views": {c: v[1] for c, v in VIEWS.items()}}


def view_toggle(label: str) -> str:
    btns = "".join(f'<button type="button" class="seg-btn" data-view="{c}" aria-pressed="{str(c == "hyp").lower()}" '
                   f'title="{E(v[1])}">{E(VIEW_SHORT[c])}</button>' for c, v in VIEWS.items())
    return (f'<div class="seg-wrap"><span class="seg-label">{E(label)}:</span>'
            f'<div class="seg" role="group" aria-label="{E(label)}">{btns}</div></div>')


def explorer(k: dict) -> str:
    sens = pd.read_csv(T / "treasury_sensitivity.csv")
    rows = "".join(f"<tr><td>{sgm(r.yield_change_vs_rolldown_bp, 0)} bp</td><td class=\"num\">{n(r.horizon_yield_pct)}%</td>"
                   f'<td class="num">{n(r.note_hpr_pct)}%</td><td class="num">{n(r.bill_hpr_pct)}%</td>'
                   f'<td class="num">{sgm(r.excess_pct)}%</td></tr>' for r in sens.itertuples())
    body = f"""
<div class="card explorer" id="explorer">
  <div class="explorer-top">
    {view_toggle("What the market has priced")}
    <div class="chips" id="explorer-chips" aria-label="Jump to a scenario"></div>
  </div>
  <div class="legend" aria-hidden="true"><span><i class="key key--note"></i>2-year note, return if sold on the horizon date</span>
    <span><i class="key key--bill"></i>6-month bill, held to maturity</span></div>
  <div class="chart-box"><svg id="explorer-chart" role="img" aria-label="Note return and bill return against the 1.5-year yield at the horizon"></svg>
    <div class="tooltip" id="explorer-tip" hidden></div></div>
  <label class="slider-label" for="explorer-slider">1.5-year Treasury yield on the day you sell:
    <output id="explorer-yield"></output></label>
  <input type="range" id="explorer-slider" min="0" max="1" step="1" value="0">
  <div class="readouts">
    <div class="readout"><span>2-year note</span><strong id="ro-note"></strong></div>
    <div class="readout"><span>6-month bill</span><strong id="ro-bill"></strong></div>
    <div class="readout readout--edge"><span>Edge, note minus bill</span><strong id="ro-edge"></strong></div>
  </div>
  <p class="explorer-verdict" id="ro-verdict" aria-live="polite"></p>
  <noscript><p>Turn on JavaScript to use the slider. The table below shows the same calculation.</p></noscript>
</div>
<div class="explain-grid">
  <div class="card"><h3>How to read the chart</h3><ul class="read-list">
    <li><strong>The orange line is flat</strong> because the bill's return is locked in the day you buy it:
    {n(k['bill_hpr'])}%.</li>
    <li><strong>The blue line slopes down</strong> because a higher yield on the day you sell means a lower price for the
    note. Each 25 bp rise costs about {n(k['sens_per_25bp'])}% of return.</li>
    <li><strong>The lines cross at the breakeven</strong>, {n(k['breakeven'])}%. That is also the market's forward rate
    ({n(k['forward'])}%), the yield today's prices imply for that day. Buying the note is a bet that yields end up below
    what the market already expects.</li>
    <li><strong>&ldquo;Curve unchanged&rdquo;</strong> ({n(k['rolldown'])}%) is where the yield lands if nothing moves.
    The market prices it {n(k['priced_rise_bp'], 0)} bp higher than that.</li></ul></div>
  <div class="card"><h3>If yields move from the unchanged curve</h3>
  <div class="table-wrap"><table class="compact"><thead><tr><th>Move</th><th class="num">Yield</th><th class="num">Note</th>
  <th class="num">Bill</th><th class="num">Edge</th></tr></thead><tbody>{rows}</tbody></table></div></div>
</div>"""
    return section("trade", "Try the trade", "Who wins: the note or the bill?",
                   f"You buy the 2-year note on {tm(k['settlement_date'])} and sell it on {tm(k['horizon_date'])}, after "
                   f"{k['holding_days']} days. A 6-month bill bought the same day returns {n(k['bill_hpr'])}% for sure. "
                   f"The note's return depends on one unknown: the 1.5-year Treasury yield on the day you sell. Drag "
                   f"the slider or pick a scenario.", body)


def figures(k: dict) -> list[dict]:
    return [
        {"file": "gasoline_vs_cpi_gasoline.png", "tab": "Pump prices vs CPI",
         "title": "Pump prices and the CPI gasoline index move together",
         "takeaway": f"Total pass-through is {n(k['pt_sum'])}; one-for-one cannot be rejected (p = {n(k['pt_p_sum_eq_1'])}).",
         "shows": "Top: EIA's weekly retail gasoline price (averaged by month) and the CPI gasoline index, rescaled to the "
                  "same starting level. Bottom: the monthly percentage change in each.",
         "read": "Where the blue and orange lines overlap, CPI gasoline is tracking pump prices one-for-one. Small gaps "
                 "appear in months when BLS and EIA collected prices on different days."},
        {"file": "passthrough_fit.png", "tab": "Model fit",
         "title": "The pass-through regression fits closely, with small, noisy misses",
         "takeaway": f"R&sup2; is {n(k['pt_r2'], 3)} over {k['pt_n']} months; the typical miss is {n(k['pt_resid_sd'])} pp, "
                     f"and misses tend to reverse the next month.",
         "shows": "Left: one dot per month, the model's fitted change against the actual change in CPI gasoline. "
                  "Right: the miss (actual minus fitted) for every month.",
         "read": "Dots on the dashed diagonal are perfect fits. On the right, bars near zero are small misses; the height "
                 "of a bar is how many percentage points the model was off that month."},
        {"file": "forecast_errors_vs_benchmarks.png", "tab": "Real-time test",
         "title": "In real time, the model wins only for the month already under way",
         "takeaway": f"One month ahead: {n(k['wf_rmse_model_h1'])} pp error vs {n(k['wf_rmse_no_change_h1'])} pp for no "
                     f"change. The simple 1:1 rule ({n(k['wf_rmse_retail_1to1_h1'])} pp) does better at every horizon.",
         "shows": f"Left: the typical forecast error (RMSE) for the cumulative change in CPI gasoline, one to six months "
                  f"ahead, for the model and three simple benchmarks, over {k['wf_n_origins']} real-time forecasts. "
                  f"Right: the model's error divided by each benchmark's.",
         "read": "Lower is better on the left. On the right, a ratio below the line at one means the model beats that "
                 "benchmark; filled dots are statistically significant at the 5% level, hollow dots are not."},
        {"file": "headline_cpi_scenarios.png", "tab": "Inflation paths",
         "title": "Headline inflation under three gasoline paths",
         "takeaway": f"By {k['path_end_month']}: {n(k['yoy_end_falling'], 1)}% if gasoline falls, "
                     f"{n(k['yoy_end_stable'], 1)}% if it holds, {n(k['yoy_end_rising'], 1)}% if it rises, against "
                     f"{n(k['headline_yoy_latest'], 1)}% now.",
         "shows": "Actual 12-month CPI inflation (gray) and the model's paths: gasoline falling along EIA's forecast, "
                  "holding at today's price, or rising by the same amount. The dotted line is a below-EIA reference.",
         "read": "The break in the gray line is real: BLS never published October 2025 CPI, so that year-over-year rate "
                 "cannot be computed. Dashed lines use the estimated pass-through model instead of the 1:1 rule; they "
                 "barely differ."},
        {"file": "note_vs_bill_by_scenario.png", "tab": "Note vs bill",
         "title": "Where each scenario lands: note return vs the bill",
         "takeaway": f"Probability-weighted edge: {sgm(k['x_hyp_expected'])}% if the market prices flat gasoline, "
                     f"{sgm(k['x_cons_expected'])}% if it prices EIA's forecast.",
         "shows": "The blue line is the note's return over the hold for each possible 1.5-year yield on the horizon date; "
                  "the orange line is the bill's locked-in return. Dots mark the gasoline scenarios. Left panel: the "
                  "market's forward assumes flat gasoline. Right panel: it already assumes EIA's forecast.",
         "read": f"Wherever the blue line sits above the orange one, the note wins. They cross at the breakeven yield, "
                 f"{n(k['breakeven'])}%."},
    ]


def evidence(k: dict) -> str:
    figs = figures(k)
    tabs = "".join(f'<button type="button" role="tab" id="tab-fig{i}" aria-controls="fig{i}" data-target="fig{i}">'
                   f"{f['tab']}</button>" for i, f in enumerate(figs))
    panels = "".join(
        f'<article class="figure-card card" id="fig{i}" role="tabpanel" aria-labelledby="tab-fig{i}">'
        f"<h3>{f['title']}</h3><p class=\"takeaway\">{f['takeaway']}</p>"
        f'<a class="fig-link" href="assets/fig/{f["file"]}" target="_blank" rel="noopener">'
        f'<img src="assets/fig/{f["file"]}" alt="{E(f["title"])}" loading="lazy"></a>'
        f'<div class="fig-notes"><div><h4>What it shows</h4><p>{f["shows"]}</p></div>'
        f'<div><h4>How to read it</h4><p>{f["read"]}</p></div></div></article>' for i, f in enumerate(figs))
    return section("evidence", "The evidence", "Charts from the latest run",
                   "Each chart is redrawn on every run. Click a chart to open it full size.",
                   f'<div class="tabs" data-tabs><div class="tablist" role="tablist" aria-label="Charts">{tabs}</div>'
                   f"{panels}</div>")


def scenarios(k: dict) -> str:
    sc = pd.read_csv(T / "treasury_scenarios.csv")
    ycol = next(c for c in sc.columns if c.startswith("horizon_1p5y_yield_pct"))
    end = pd.Timestamp(k["path_end_month"]).strftime("%b %Y")
    desc = {"hyp": f"The forward assumes pump prices stay near {usd(k['last_weekly_gas'])}. A fall along EIA's path "
                   f"would be news and pull the yield one step below the forward.",
            "cons": "The forward already assumes EIA's falling path. Only a fall beyond EIA's forecast is news; flat "
                    "gasoline would push the yield one step above the forward."}
    panels = []
    for c, (mapping, label) in VIEWS.items():
        d = sc[sc["mapping"] == mapping].set_index("scenario")
        rows = []
        for s in SCENARIOS:
            r = d.loc[s]
            prob = "none" if pd.isna(r["probability"]) else n(r["probability"])
            rows.append(f'<tr><td><i class="dot dot--{s}" aria-hidden="true"></i>{SCEN_LABEL[s]}</td>'
                        f'<td class="num" data-label="Probability">{prob}</td>'
                        f'<td class="num" data-label="Gasoline, {end}">{usd(r["retail_gas_end_usd"])}</td>'
                        f'<td class="num" data-label="Headline CPI">{n(r["headline_yoy_end_pct"], 1)}%</td>'
                        f'<td class="num" data-label="1.5-year yield">{n(r[ycol])}%</td>'
                        f'<td class="num" data-label="Note">{n(r["note_hpr_pct"])}%</td>'
                        f'<td class="num" data-label="Bill">{n(r["bill_hpr_pct"])}%</td>'
                        f'<td class="num strong" data-label="Edge">{sgm(r["excess_pct"])}%</td></tr>')
        w = d.loc["probability-weighted"]
        rows.append(f'<tr class="total"><td>Probability-weighted</td><td class="num" data-label="Probability"></td>'
                    f'<td class="num" data-label=""></td><td class="num" data-label=""></td><td class="num" data-label=""></td>'
                    f'<td class="num" data-label="Note">{n(w["note_hpr_pct"])}%</td>'
                    f'<td class="num" data-label="Bill">{n(w["bill_hpr_pct"])}%</td>'
                    f'<td class="num strong" data-label="Edge">{sgm(w["excess_pct"])}%</td></tr>')
        panels.append(
            f'<div class="view-panel" data-view-panel="{c}"><p class="view-desc"><strong>{E(label)}.</strong> {desc[c]}</p>'
            f'<div class="table-wrap"><table class="stack"><thead><tr><th>Gasoline scenario</th><th class="num">Probability</th>'
            f'<th class="num">Gasoline, {end}</th><th class="num">Headline CPI, {end}</th><th class="num">1.5-year yield</th>'
            f'<th class="num">Note</th><th class="num">Bill</th><th class="num">Edge</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></div>')
    body = (f'<div class="card">{view_toggle("What the market has priced")}{"".join(panels)}'
            '<p class="table-note">Edge is the note\'s return minus the bill\'s over the hold, not annualized. Yields at the '
            "horizon are scenario assumptions. Probabilities are equal placeholders set in config.yaml; the below-EIA "
            "path is a reference with no probability.</p></div>")
    return section("scenarios", "Scenarios", "From gasoline paths to returns",
                   f"Each gasoline path is mapped to a 1.5-year yield {n(k['shift_bp'], 0)} bp apart: half the "
                   f"interquartile range of {k['hist_err_n']} monthly misses of the forward rate since 1990. The two views "
                   f"differ in one assumption only: which gasoline path the market's forward already contains.", body)


def pretty(s: str) -> str:
    return E(str(s)).replace("&lt;=", "\u2264").replace("&gt;=", "\u2265").replace("+/-", "\u00b1")


def watchlist(k: dict) -> str:
    trig = pd.read_csv(T / "monitoring_triggers.csv").fillna("")
    trows = "".join(f'<tr><td data-label="Signal">{pretty(r.trigger)}</td><td data-label="Supports buying the note if">'
                    f'{pretty(r.supports_note_if)}</td><td data-label="Argues against if">{pretty(r.against_note_if)}</td>'
                    f'<td data-label="Latest">{pretty(r.current) or "<span class=muted>Not yet</span>"}</td></tr>'
                    for r in trig.itertuples())
    cal = pd.read_csv(T / "monitoring_calendar.csv")
    items = []
    for r in cal.itertuples():
        when = tm(r.date, "short") if isinstance(r.date, str) and r.date else '<span class="muted">Recurring</span>'
        items.append(f'<li><span class="when">{when}</span><span><strong>{E(r.event)}</strong>'
                     f'<span class="why">{E(r.why)}</span></span></li>')
    body = (f'<div class="card"><h3 class="card-title">Signals that would change the answer</h3>'
            f'<div class="table-wrap"><table class="stack"><thead><tr><th>Signal</th><th>Supports buying the note if</th>'
            f"<th>Argues against if</th><th>Latest</th></tr></thead><tbody>{trows}</tbody></table></div></div>"
            f'<div class="card"><h3 class="card-title">Upcoming releases</h3><ul class="calendar">{"".join(items)}</ul></div>')
    return section("watch", "Watchlist", "What would change the answer",
                   "Measurable signals checked on every run, and the releases that feed them.",
                   f'<div class="watch-grid">{body}</div>')


def _iso_pretty(m: re.Match) -> str:
    t = dt.datetime.fromisoformat(m.group(0))
    return t.strftime("%b %-d, %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")


def md_to_html(md: str) -> str:
    md = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", _iso_pretty, md)
    out, in_list = [], False
    for line in md.splitlines():
        line = line.rstrip()
        txt = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", E(line[2:] if line.startswith("- ") else line))
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{txt}</li>")
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        if line.startswith("# ") or not line:
            continue
        if line.startswith("## "):
            out.append(f"<h4>{E(line[3:])}</h4>")
        else:
            out.append(f"<p>{txt}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


def history_rows(limit: int = 12) -> str:
    snaps = {}
    for f in sorted((OUT / "history").glob("key_numbers_*.json")):
        s = json.loads(f.read_text())
        snaps[s.get("as_of")] = s  # keep the last run of each day
    rows = []
    need = ("as_of", "generated_at", "latest_cpi_month", "y0", "breakeven", "x_cons_expected", "rec_short")
    for s in sorted(snaps.values(), key=lambda s: s["generated_at"], reverse=True)[:limit]:
        if any(s.get(f) is None for f in need):
            continue
        rows.append(f'<tr><td>{tm(s["as_of"], "short")}</td><td>{E(pd.Timestamp(s["latest_cpi_month"]).strftime("%b %Y"))}</td>'
                    f'<td class="num">{n(s["y0"])}%</td><td class="num">{n(s["breakeven"])}%</td>'
                    f'<td class="num">{sgm(s["x_cons_expected"])}%</td><td>{E(s["rec_short"])}</td></tr>')
    return "".join(rows)


def changes(k: dict) -> str:
    md = (OUT / "changes_since_last_run.md").read_text() if (OUT / "changes_since_last_run.md").exists() else ""
    body = (f'<div class="changes-grid"><div class="card"><h3 class="card-title">Since the previous run</h3>'
            f'<div class="md">{md_to_html(md)}</div></div>'
            f'<div class="card"><h3 class="card-title">Run history (last run of each day)</h3>'
            f'<div class="table-wrap"><table class="compact"><thead><tr><th>Run date</th><th>Latest CPI</th>'
            f'<th class="num">2-year yield</th><th class="num">Breakeven</th><th class="num">Edge, EIA priced</th>'
            f"<th>Answer</th></tr></thead><tbody>{history_rows()}</tbody></table></div></div></div>")
    return section("changes", "Change log", "What moved since the last run",
                   "Every run is saved, so you can see when new data arrived and whether the answer changed.",
                   body, static=True)


def checks_section(checks: dict | None, cfg: dict) -> str:
    by_base: dict[str, list] = {}
    for c in (checks or {}).get("cases", []):
        by_base.setdefault(c["base"], []).append(c["status"])
    icon = {"passed": ('<span class="ok" aria-label="passed">&#10003;</span>'),
            "failed": ('<span class="fail" aria-label="failed">&#10007;</span>'),
            "skipped": ('<span class="skip" aria-label="skipped">&ndash;</span>'),
            None: ('<span class="skip" aria-label="not run">&middot;</span>')}
    groups = []
    for g in CHECK_GROUPS:
        lis, n_ok, n_all = [], 0, 0
        for name, desc in g["tests"].items():
            st = by_base.get(name)
            status = None if not st else ("failed" if "failed" in st else "skipped" if "skipped" in st else "passed")
            n_all += len(st or [1]); n_ok += sum(s == "passed" for s in (st or []))
            reps = f' <span class="muted">({len(st)} cases)</span>' if st and len(st) > 1 else ""
            lis.append(f"<li>{icon[status]}<span>{desc}{reps}<code class=\"fn\">{name}</code></span></li>")
        badge = (f'<span class="pill pill--ok">{n_ok}/{n_all} passed</span>' if checks and n_ok == n_all else
                 f'<span class="pill pill--bad">{n_ok}/{n_all} passed</span>' if checks else
                 '<span class="pill">not run</span>')
        groups.append(f'<details class="check-group"><summary><span class="cg-title">{g["title"]}</span>{badge}'
                      f'<span class="cg-why">{g["why"]}</span></summary><ul class="check-list">{"".join(lis)}</ul></details>')
    if checks:
        ok = checks["failed"] == 0
        summary = (f'<div class="check-summary {"is-ok" if ok else "is-bad"}"><span class="big-icon" aria-hidden="true">'
                   f'{"&#10003;" if ok else "&#10007;"}</span><div><p class="cs-title">'
                   f'{checks["passed"]} of {checks["total"]} checks passed</p><p class="muted">In the latest run'
                   + (f", {checks['skipped']} skipped" if checks["skipped"] else "")
                   + ". Click a group to see what each check does.</p></div></div>")
    else:
        summary = ('<div class="check-summary"><div><p class="cs-title">Checks not run yet</p><p class="muted">Run '
                   "<code>python3 run_all.py</code> to run them and rebuild this page.</p></div></div>")
    return section("checks", "Automated checks", "How we know the machinery works",
                   "Every run ends with automated checks (pytest). They don't test whether the investment idea is "
                   "right; they test that the machinery is: no peeking at future data, bond math that matches the "
                   "Treasury's own numbers, and reports that only quote the model.",
                   summary + "".join(groups), static=True)


def run_section(k: dict, cfg: dict) -> str:
    s = cfg["site"]
    wf_url = f"{s['repo_url']}/actions/workflows/{s['workflow_file']}"
    badge = f"{wf_url}/badge.svg"
    steps = [("Download", "src/download.py", "Fresh data from every source, each stamped with when it was pulled."),
             ("Verify", "src/verify.py", "Cross-checks the starting facts against a second source."),
             ("Modules A and B", "src/phase2.py", "Pass-through regression and the real-time forecast test."),
             ("Modules C and D", "src/phase3.py", "Headline inflation paths and note-versus-bill returns."),
             ("Report", "src/phase4.py", "Watchlist, key numbers, change log, memo and deck."),
             ("Check", "tests/", "Runs every automated check."),
             ("Publish", "src/site.py", "Rebuilds this page.")]
    pipe = "".join(f'<li><span class="pnum">{i}</span><div><strong>{t}</strong> <code class="code-chip">{c}</code>'
                   f"<p>{d}</p></div></li>" for i, (t, c, d) in enumerate(steps, 1))
    body = f"""
<div class="run-grid">
  <article class="card run-card run-card--primary">
    <p class="run-tag">Easiest</p>
    <h3>Run it on GitHub</h3>
    <p>No installs. GitHub downloads the data, runs the model and the checks, then republishes this page.</p>
    <ol class="howto">
      <li>Open the workflow page (sign in as the repository owner).</li>
      <li>Click <strong>Run workflow</strong> on the right, then the green <strong>Run workflow</strong> button.</li>
      <li>Wait a few minutes. A green check means this page now shows the new results; refresh it.</li>
    </ol>
    <p><a class="btn btn--amber" href="{wf_url}" target="_blank" rel="noopener">Open the Run analysis workflow &rarr;</a></p>
    <p class="muted small">If a download fails, the run stops with a red X, nothing is published, and this page keeps
    the last good results. GitHub emails you about failed runs.</p>
  </article>
  <article class="card run-card">
    <h3>Run it on your Mac</h3>
    <p>One command reruns everything and rebuilds this page locally.</p>
    <pre data-copy><code>cd ~/energy-inflation-2y-treasury
python3 run_all.py
open docs/index.html</code></pre>
    <p class="muted small">First time on a new computer:</p>
    <pre data-copy><code>git clone {s['repo_url']}.git
cd energy-inflation-2y-treasury
pip3 install -r requirements.txt
npm install</code></pre>
    <p class="muted small">Add <code>--offline</code> to rerun on the data already downloaded.</p>
  </article>
  <article class="card run-card">
    <h3>It also runs on its own</h3>
    <p>GitHub runs the analysis {E(s['schedule_note'])} and republishes this page, so new CPI, gasoline, EIA and
    Treasury data show up the evening they are released.</p>
    <p class="last-run">Last run: {run_time(k['generated_at'])}</p>
    <p><a href="{wf_url}" target="_blank" rel="noopener"><img class="badge" src="{badge}" alt="Status of the latest run"
    onerror="this.parentNode.parentNode.hidden=true"></a></p>
  </article>
</div>
<div class="card"><h3 class="card-title">What a run does</h3><ol class="pipeline">{pipe}</ol></div>"""
    return section("run", "Run it yourself", "Three ways to run the analysis",
                   "The whole analysis is one Python program. Pick whichever way is easiest.", body, static=True)


def data_sources(k: dict, cfg: dict) -> str:
    man = json.loads(Path("data/raw/manifest.json").read_text())
    fred = {m["id"]: m for m in man if m["source"] == "FRED"}
    groups = [("CPI indexes (BLS via FRED)", ["CPIAUCNS", "CPIAUCSL", "CPILFENS", "CPILFESL", "CPIUFDNS", "CPIENGNS",
                                              "CUUR0000SETB01", "CUSR0000SETB01"]),
              ("Retail gasoline (EIA via FRED; BLS average price)", ["GASREGW", "APU000074714"]),
              ("Brent crude spot (EIA via FRED)", ["DCOILBRENTEU"]),
              ("Treasury yields, bills, SOFR, fed funds (via FRED)", ["DGS2", "DGS1", "DGS6MO", "DTB6", "SOFR", "DFF"]),
              ("Inflation breakevens and term premiums (FRED)", ["T5YIE", "THREEFYTP1", "THREEFYTP2"])]
    rows = []
    for lab, ids in groups:
        ids = [i for i in ids if i in fred]
        if not ids:
            continue
        last = max(str(fred[i]["last_obs"]) for i in ids)
        links = ", ".join(f'<a href="https://fred.stlouisfed.org/series/{i}" target="_blank" rel="noopener">{i}</a>' for i in ids)
        rows.append((lab, links, tm(last, "month" if lab.startswith("CPI") else "med") if last else "",
                     tm(fred[ids[0]]["retrieved"][:10], "med")))
    other = {m["source"]: m for m in man if m["source"] not in ("FRED", "ALFRED", "BLS API v1")}
    for src, desc in [("U.S. Treasury par yield curve", "Daily par yields"),
                      ("U.S. Treasury daily bill rates", "Six-month bill discount and coupon-equivalent rates"),
                      ("TreasuryDirect auction results", "Note and bill terms: CUSIP, coupon, maturity"),
                      ("EIA STEO", f"Short-Term Energy Outlook, {E(k['steo_vintage'])}"),
                      ("ALFRED CPI release dates (release id 10)", "CPI release dates for the real-time test"),
                      ("Federal Reserve FOMC calendar", "Fed meeting dates")]:
        if src in other:
            rows.append((E(src), desc, "", tm(other[src]["retrieved"][:10], "med")))
    ri = cfg["data"]["relative_importance_dec2025"]
    rows.append(("BLS relative importance of CPI components", E(ri["source"]), "December 2025", tm(ri["retrieved"], "med")))
    trs = "".join(f'<tr><td data-label="Source">{a}</td><td data-label="Series">{b}</td><td data-label="Latest data">{c}</td>'
                  f'<td data-label="Downloaded">{d}</td></tr>' for a, b, c, d in rows)
    downloads = [("Investment memo", "Energy_Inflation_2Y_Treasury_Memo.docx", "Word", "The full argument, 8 sections"),
                 ("Slide deck", "Energy_Inflation_2Y_Treasury_Deck.pptx", "PowerPoint", "The short version"),
                 ("Resume bullets", "resume_bullets.md", "Text", "What was built and found"),
                 ("Key numbers", "key_numbers.json", "JSON", "Every number this page and the memo use"),
                 ("Result tables", "result_tables.zip", "CSV, zipped", "Every table the model writes"),
                 ("Change report", "changes_since_last_run.md", "Text", "New data and changes vs the previous run")]
    dl = "".join(f'<a class="download" href="downloads/{f}"><span class="dl-type">{t}</span><strong>{lab}</strong>'
                 f"<span class=\"muted small\">{d}</span></a>" for lab, f, t, d in downloads)
    body = (f'<div class="downloads">{dl}</div>'
            f'<div class="card"><h3 class="card-title">Where the data come from</h3><div class="table-wrap">'
            f'<table class="stack compact"><thead><tr><th>Source</th><th>Series</th><th>Latest data</th><th>Downloaded</th>'
            f"</tr></thead><tbody>{trs}</tbody></table></div>"
            f'<p class="table-note">Every raw file and its download time is listed in <code>data/raw/manifest.json</code>. '
            f"Nothing on this page is typed in by hand: it is all produced by the model run of {run_time(k['generated_at'])}."
            f"</p></div>")
    return section("data", "Data and downloads", "Sources, files and the full write-up", "", body, static=True)


GLOSSARY = [
    ("Basis point (bp)", "One hundredth of a percentage point. A yield moving from 4.50% to 4.75% has risen 25 bp."),
    ("CPI, headline and core", "The Consumer Price Index measures what households pay. Headline CPI covers everything; "
                               "core leaves out food and energy, which swing the most."),
    ("Not seasonally adjusted (NSA)", "The raw index, before BLS removes regular seasonal swings. The model uses raw data "
                                      "plus calendar-month effects because raw CPI is never revised."),
    ("Pass-through", "How much of a change in pump prices shows up in the CPI gasoline index. One-for-one means a 1% "
                     "rise at the pump becomes a 1% rise in CPI gasoline."),
    ("Nowcast", "An estimate of a number for a month that is already under way but not yet published."),
    ("Walk-forward (real-time) test", "Replaying history one release at a time, refitting the model with only the data "
                                      "public on each date, to see how it would really have done."),
    ("RMSE", "Root mean squared error: the typical size of a forecast miss, with big misses counting extra."),
    ("Diebold-Mariano test", "A standard test of whether one forecaster's errors are reliably smaller than another's, "
                             "rather than smaller by luck."),
    ("Treasury bill and note", "Government IOUs. A bill matures within a year and pays no coupon; you buy it below "
                               "face value. A note pays a coupon every six months and matures in two to ten years."),
    ("Holding-period return", "What an investment earns between the day you buy it and the day you sell it, "
                              "including coupons, not annualized."),
    ("Edge", "The note's holding-period return minus the bill's over the same days. Positive means the note wins."),
    ("Forward rate and breakeven yield", "The forward rate is the future yield implied by today's yield curve. The "
                                         "breakeven is the yield at which the note and bill tie; here the two are the same."),
    ("Roll-down", "As a note ages it slides down the yield curve. The roll-down yield is where it would end up if the "
                  "curve did not move at all."),
    ("Term premium", "Extra yield investors demand for tying money up longer, separate from where they expect rates "
                     "to go."),
    ("The two market views", "An assumption about what today's forward already contains: flat gasoline, or EIA's "
                             "falling forecast. Only surprises relative to what is priced move yields."),
    ("EIA STEO", "The Energy Information Administration's monthly Short-Term Energy Outlook, which forecasts gasoline "
                 "and oil prices."),
    ("ALFRED vintage", "A copy of a data series exactly as it looked on a past date, used to prove the real-time test "
                       "saw only what was published."),
    ("Base effect", "Year-over-year inflation compares with a year ago, so a big jump last year drops out twelve "
                    "months later and pulls the rate down even if prices are flat now."),
]


def glossary() -> str:
    items = "".join(f"<div><dt>{t}</dt><dd>{d}</dd></div>" for t, d in GLOSSARY)
    return section("glossary", "Glossary", "Terms used on this page", "", f'<dl class="glossary">{items}</dl>', static=True)


def render(k: dict, cfg: dict, checks: dict | None) -> str:
    s = cfg["site"]
    data = {"explorer": explorer_data(k)}
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    stamp = re.sub(r"\D", "", k["generated_at"])
    nav = [("findings", "Findings"), ("how", "How it works"), ("trade", "Try the trade"),
           ("evidence", "Evidence"), ("scenarios", "Scenarios"), ("watch", "Watchlist"), ("checks", "Checks"),
           ("run", "Run it")]
    navhtml = "".join(f'<a href="#{i}">{t}</a>' for i, t in nav)
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Energy Inflation and the 2-Year Treasury</title>
<meta name="description" content="Does fading gasoline inflation make a 2-year Treasury note beat a 6-month bill? A reproducible analysis rebuilt from public data on every run.">
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&amp;display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/style.css?v={stamp}">
</head>
<body>
<a class="skip-link" href="#findings">Skip to the findings</a>
<header class="topbar"><div class="wrap topbar-in">
  <a class="brand" href="#answer"><span class="brand-mark" aria-hidden="true"></span>Energy Inflation &times; 2-Year Treasury</a>
  <nav class="nav" aria-label="Sections">{navhtml}</nav>
</div></header>
{hero(k, cfg)}
<main>
{insights(k, cfg)}
{how_it_works(k)}
{explorer(k)}
{evidence(k)}
{scenarios(k)}
{watchlist(k)}
{changes(k)}
{checks_section(checks, cfg)}
{run_section(k, cfg)}
{data_sources(k, cfg)}
{glossary()}
</main>
<footer class="footer" data-static><div class="wrap footer-in">
  <p><strong>Energy Inflation and the Two-Year Treasury.</strong> A student research project. Not investment advice.</p>
  <p>Built from the model run of {run_time(k['generated_at'])}. <a href="{s['repo_url']}">Source code on GitHub</a>.</p>
</div></footer>
<script type="application/json" id="site-data">{payload}</script>
<script src="assets/app.js?v={stamp}" defer></script>
</body>
</html>
"""
    return _nobreak(page)


def _nobreak(page: str) -> str:
    """Use non-breaking hyphens in '6-month', '1.5-year' and the like (text only, never tags or scripts)."""
    parts = re.split(r"(<script\b.*?</script>|<[^>]+>)", page, flags=re.S)
    return "".join(p if p.startswith("<") else re.sub(r"(\d)-(year|month|day)\b", "\\1\u2011\\2", p)
                   for p in parts)


class _Text(HTMLParser):
    """Visible prose of a page: skips scripts, styles, svg, code, <time> and anything marked data-static."""
    SKIP = {"script", "style", "svg", "pre", "code", "time", "noscript"}
    VOID = {"img", "br", "hr", "meta", "link", "input", "source", "wbr", "area", "base", "col", "embed", "track"}

    def __init__(self):
        super().__init__()
        self.stack: list[bool] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        self.stack.append(tag in self.SKIP or any(a == "data-static" for a, _ in attrs))

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()

    def handle_data(self, d):
        if not any(self.stack):
            self.parts.append(d)


def visible_text(page: str) -> str:
    p = _Text()
    p.feed(page)
    return " ".join(p.parts)


def build(cfg: dict, out: Path = DOCS) -> Path:
    k = json.loads((OUT / "key_numbers.json").read_text())
    checks = read_checks()
    if out.exists():
        shutil.rmtree(out)
    (out / "assets" / "fig").mkdir(parents=True)
    (out / "downloads").mkdir(parents=True)
    for f in STATIC.iterdir():
        if f.is_file():
            shutil.copy2(f, out / "assets" / f.name)
    for f in F.glob("*.png"):
        shutil.copy2(f, out / "assets" / "fig" / f.name)
    for f in DELIV.iterdir():
        if f.suffix in {".docx", ".pptx", ".md"}:
            shutil.copy2(f, out / "downloads" / f.name)
    for f in (OUT / "key_numbers.json", OUT / "changes_since_last_run.md"):
        if f.exists():
            shutil.copy2(f, out / "downloads" / f.name)
    with zipfile.ZipFile(out / "downloads" / "result_tables.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(T.glob("*.csv")):
            z.write(f, f.name)
    (out / "index.html").write_text(render(k, cfg, checks))
    (out / ".nojekyll").write_text("")
    return out / "index.html"


if __name__ == "__main__":
    print(build(yaml.safe_load(open("config.yaml"))))
