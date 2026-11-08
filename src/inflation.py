"""Module C: headline CPI path = gasoline scenario + labeled assumptions for everything else.

Aggregation (BLS relative-importance arithmetic, NSA):
    headline_t / headline_{t-1} - 1 = sum_i w_{i,t-1}/100 * (I_{i,t}/I_{i,t-1} - 1)
for i in {core, food, gasoline, other energy}; weights are December-2025 relative importances
rolled forward by relative price change. "Other energy" = energy - gasoline (electricity,
utility gas, fuel oil, other motor fuel); its history is backed out of the energy and gasoline
indexes.

Only gasoline is modeled (retail price path -> CPI gasoline). Core, food and other energy are
ASSUMPTIONS: a trend pace (default: trailing 12-month NSA change) plus each component's average
calendar-month seasonal pattern over the last `seasonal_window_years`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

from . import data_prep as dp
from . import passthrough as pt

COMPONENTS = ["core", "food", "gasoline", "other_energy"]


# ---------------- data ----------------
def load_indexes(raw: Path) -> pd.DataFrame:
    df = pd.DataFrame({
        "all": dp.load_fred(raw, "CPIAUCNS"),
        "core": dp.load_fred(raw, "CPILFENS"),
        "food": dp.load_fred(raw, "CPIUFDNS"),
        "energy": dp.load_fred(raw, "CPIENGNS"),
        "gasoline": dp.load_fred(raw, "CUUR0000SETB01"),
    })
    return df[df.index >= "2000-01-01"]


def rolled_weights(idx: pd.DataFrame, ri: dict, base: str = "2025-12-01") -> pd.DataFrame:
    """Relative importance by month, rolled from the December base by relative prices.
    Months before the base are an approximation (earlier years used other basket weights)."""
    b = pd.Timestamp(base)
    rel_all = idx["all"] / idx.loc[b, "all"]
    w = pd.DataFrame(index=idx.index)
    w["core"] = ri["all_items_less_food_energy"] * (idx["core"] / idx.loc[b, "core"]) / rel_all
    w["food"] = ri["food"] * (idx["food"] / idx.loc[b, "food"]) / rel_all
    w["energy"] = ri["energy"] * (idx["energy"] / idx.loc[b, "energy"]) / rel_all
    w["gasoline"] = ri["gasoline_all_types"] * (idx["gasoline"] / idx.loc[b, "gasoline"]) / rel_all
    w["other_energy"] = w["energy"] - w["gasoline"]
    return w


def component_changes(idx: pd.DataFrame, w: pd.DataFrame) -> pd.DataFrame:
    """Monthly simple % changes (as fractions) by component; other energy backed out of energy."""
    r = idx.pct_change(fill_method=None)
    gap = idx.index.to_series().diff().dt.days > 31
    r[gap.values] = np.nan
    wp = w.shift(1)
    r["other_energy"] = (wp["energy"] * r["energy"] - wp["gasoline"] * r["gasoline"]) / wp["other_energy"]
    return r


def aggregate_check(idx: pd.DataFrame, w: pd.DataFrame, r: pd.DataFrame, start: str) -> pd.DataFrame:
    """Rebuild headline monthly change from components; compare with actual headline."""
    wp = w.shift(1)
    pred = sum(wp[c] / 100 * r[c] for c in COMPONENTS)
    out = pd.DataFrame({"actual_headline_mom_pct": 100 * r["all"], "rebuilt_from_components_pct": 100 * pred})
    out["diff_pp"] = out["rebuilt_from_components_pct"] - out["actual_headline_mom_pct"]
    return out[out.index >= start].dropna()


# ---------------- assumptions for non-gasoline components ----------------
def seasonal_pattern(r: pd.Series, end: pd.Timestamp, years: int) -> pd.Series:
    """Calendar-month mean log change minus the overall mean (sums to ~0 over a year)."""
    x = np.log1p(r[(r.index > end - pd.DateOffset(years=years)) & (r.index <= end)]).dropna()
    m = x.groupby(x.index.month).mean()
    return (m - m.mean()).reindex(range(1, 13)).fillna(0.0)


def trailing_annual_log(idx_series: pd.Series, end: pd.Timestamp) -> float:
    return float(np.log(idx_series[end] / idx_series[end - pd.DateOffset(years=1)]))


def other_energy_trailing_annual_log(idx: pd.DataFrame, w: pd.DataFrame, end: pd.Timestamp) -> float:
    """12-month change in other energy from levels (Laspeyres within the year-ago weights)."""
    s = end - pd.DateOffset(years=1)
    e = idx.loc[end, "energy"] / idx.loc[s, "energy"]
    g = idx.loc[end, "gasoline"] / idx.loc[s, "gasoline"]
    ratio = (w.loc[s, "energy"] * e - w.loc[s, "gasoline"] * g) / w.loc[s, "other_energy"]
    return float(np.log(ratio))


def nongas_paths(idx, w, r, last: pd.Timestamp, months: pd.DatetimeIndex, cfg_inf: dict) -> tuple[pd.DataFrame, dict]:
    """Assumed monthly NSA changes for core, food and other energy over `months`."""
    years = cfg_inf["seasonal_window_years"]
    trend = {
        "core": trailing_annual_log(idx["core"], last),
        "food": trailing_annual_log(idx["food"], last),
        "other_energy": other_energy_trailing_annual_log(idx, w, last),
    }
    used = {}
    out = pd.DataFrame(index=months)
    for c in ["core", "food", "other_energy"]:
        override = cfg_inf["component_trend_annual_pct"].get(c)
        t = np.log1p(override / 100) if override is not None else trend[c]
        used[c] = {"annual_pct": 100 * np.expm1(t), "source": "config override" if override is not None
                   else f"trailing 12-month NSA change to {last:%Y-%m}"}
        seas = seasonal_pattern(r[c], last, years)
        out[c] = np.expm1(t / 12 + seas.reindex(months.month).values)
    return out, used


# ---------------- gasoline scenarios ----------------
def steo_monthly(xlsx: Path, code: str = "MGRARUS_$") -> tuple[pd.Series, str]:
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb["2tab"]
    rows = list(ws.iter_rows(values_only=True))
    vintage = str(rows[1][1]).split(" - ")[-1].strip()  # e.g. "October 2026"
    years, months = rows[2], rows[3]
    row = next(r for r in rows if r and r[0] == code)
    yr, vals = None, {}
    for i in range(2, len(years)):
        yr = years[i] or yr
        if months[i] is not None and row[i] is not None:
            vals[pd.Timestamp(f"{yr}-{months[i]}-01")] = float(row[i])
    return pd.Series(vals).sort_index(), vintage


def gasoline_scenarios(weekly: pd.Series, steo: pd.Series, months: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict]:
    """Monthly average retail regular gasoline ($/gal) by scenario for `months`.

    Complete months use actual EIA weekly averages. For later months:
      stable : last weekly price held flat.
      falling: EIA STEO path, anchored to the last complete month (EIA's own month-to-month
               log changes applied to the actual average).
      rising : mirror image of the falling path around the stable path (same-size move up).
      below_eia (reference, no probability): one more step down - falls below EIA's path by
               as much as EIA's path falls below the stable path.
    """
    w = weekly.dropna()
    last_date, last_price = w.index[-1], float(w.iloc[-1])
    complete = dp.monthly_avg(w)
    complete = complete[complete.index + pd.offsets.MonthEnd(0) < last_date]
    anchor = complete.index.max()
    out = pd.DataFrame(index=months, columns=["falling", "stable", "rising", "below_eia"], dtype=float)
    for m in months:
        if m <= anchor:
            out.loc[m] = complete[m]
            continue
        if m not in steo.index or anchor not in steo.index:
            raise ValueError(f"EIA STEO path missing {m:%Y-%m} or anchor {anchor:%Y-%m}")
        fall = complete[anchor] * steo[m] / steo[anchor]
        out.loc[m, "stable"] = last_price
        out.loc[m, "falling"] = fall
        out.loc[m, "rising"] = last_price ** 2 / fall
        out.loc[m, "below_eia"] = fall ** 2 / last_price
    meta = {"last_weekly_date": last_date.date(), "last_weekly_price": last_price,
            "anchor_month": anchor.date(), "anchor_actual_avg": float(complete[anchor]),
            "anchor_steo": float(steo[anchor])}
    return out, meta


# ---------------- headline path ----------------
def headline_path(idx, w, last, months, gas_mom: pd.Series, nongas: pd.DataFrame) -> pd.DataFrame:
    """Chain the NSA headline index forward; weights roll with relative prices."""
    wt = w.loc[last, COMPONENTS].copy()
    level = float(idx.loc[last, "all"])
    rows = []
    for m in months:
        r = {"gasoline": gas_mom[m], **{c: nongas.loc[m, c] for c in ["core", "food", "other_energy"]}}
        contrib = {c: wt[c] / 100 * r[c] for c in COMPONENTS}
        R = sum(contrib.values())
        level *= 1 + R
        rows.append({"month": m, "headline_index": level, "headline_mom_pct": 100 * R,
                     **{f"contrib_{c}_pp": 100 * v for c, v in contrib.items()},
                     "gas_weight_pct": wt["gasoline"]})
        wt = wt * pd.Series({c: (1 + r[c]) / (1 + R) for c in COMPONENTS})
    df = pd.DataFrame(rows).set_index("month")
    hist = idx["all"]
    yago = [hist.get(m - pd.DateOffset(years=1), np.nan) for m in df.index]
    df["headline_yoy_pct"] = 100 * (df["headline_index"] / np.array(yago, dtype=float) - 1)
    return df


def gas_cpi_mom(retail: pd.Series, gas_monthly_hist: pd.Series, method: str, beta: pd.Series | None,
                lags: int) -> pd.Series:
    """CPI gasoline monthly change (fraction) from a retail path.
    retail_1to1: CPI gasoline log change = retail log change. estimated_model: Module A fit."""
    full = pd.concat([gas_monthly_hist[gas_monthly_hist.index < retail.index.min()], retail]).sort_index()
    x = dp.dlog(full)
    if method == "retail_1to1":
        y = x.reindex(retail.index)
    elif method == "estimated_model":
        y = pt.predict(beta, x, retail.index, lags)
    else:
        raise ValueError(method)
    return np.expm1(y / 100)
