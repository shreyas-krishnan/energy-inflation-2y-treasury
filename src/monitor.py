"""Monitoring plan: measurable triggers (computed from model outputs) and the release calendar."""
from __future__ import annotations

import html
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import data_prep as dp
from . import inflation as inf

TABLES = Path("outputs/tables")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def fomc_meetings(path: Path) -> list[dict]:
    """Parse meeting dates from the Federal Reserve FOMC calendar page."""
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="ignore"))))
    out = []
    heads = list(re.finditer(r"(\d{4}) FOMC Meetings", t))
    for k, h in enumerate(heads):
        year = int(h.group(1))
        block = t[h.end(): heads[k + 1].start() if k + 1 < len(heads) else len(t)]
        for m in re.finditer(rf"\b({MONTHS})(?:/({MONTHS}))? (\d{{1,2}})-(\d{{1,2}})(\*?)", block):
            if re.match(r",\s*\d{4}", block[m.end():m.end() + 7]):  # e.g. "January 25-26, 2028" in a footnote
                continue
            end_month = m.group(2) or m.group(1)
            end = pd.Timestamp(f"{end_month} {m.group(4)} {year}")
            out.append({"date": end, "event": f"FOMC decision ({m.group(1)} {m.group(3)}-{m.group(4)})"
                        + (", with projections" if m.group(5) else ""), "source": "federalreserve.gov FOMC calendar"})
    return sorted({o["date"]: o for o in out}.values(), key=lambda o: o["date"])


def steo_next_release(path: Path) -> pd.Timestamp | None:
    t = re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="ignore"))
    m = re.search(r"Next Release Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", t)
    return pd.Timestamp(m.group(1)) if m else None


def calendar(cfg: dict, raw: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for c in cfg["release_calendar"]["cpi"]:
        rows.append({"date": pd.Timestamp(c["date"]), "event": f"CPI for {c['reference']} (BLS, 8:30 ET)",
                     "why": "Tests the 1:1 gasoline nowcast, core assumption and the headline path",
                     "source": "BLS 2026 release schedule (config.yaml)"})
    nxt = steo_next_release(raw / "web" / "eia_steo.html")
    if nxt is not None:
        rows.append({"date": nxt, "event": "EIA Short-Term Energy Outlook",
                     "why": "Moves the falling (EIA) gasoline path and the below-EIA trigger",
                     "source": "EIA STEO page"})
    for f in fomc_meetings(raw / "web" / "fomc_calendar.html"):
        rows.append({**f, "why": "Policy decision; resets the front end of the curve and the forward"})
    df = pd.DataFrame(rows)
    df = df[(df["date"] >= start) & (df["date"] <= end)].sort_values("date")
    recurring = pd.DataFrame([
        {"date": pd.NaT, "event": "EIA weekly retail gasoline (every Monday)",
         "why": "Tracks the gasoline path against the EIA, stable and below-EIA levels",
         "source": "EIA via FRED GASREGW"},
        {"date": pd.NaT, "event": "Treasury daily par yield curve and bill rates (each business day)",
         "why": "Moves the forward, breakeven and the entry-level test", "source": "U.S. Treasury"},
    ])
    return pd.concat([df, recurring], ignore_index=True)


def triggers(cfg: dict, raw: Path, p3: dict, p2_metrics: pd.DataFrame, nowcast: pd.DataFrame) -> pd.DataFrame:
    tc = cfg["triggers"]
    setup = p3["treasury"]["setup"]
    gas = pd.read_csv(TABLES / "gasoline_scenarios.csv", index_col=0, parse_dates=True)
    weekly = dp.load_fred(raw, "GASREGW").dropna()
    rows = []
    # 1. Gasoline path vs EIA and today's price (monthly averages)
    mtd = weekly[weekly.index >= weekly.index[-1].replace(day=1)]
    for m, r in gas.iterrows():
        if m <= pd.Timestamp(p3["inflation"]["meta"]["anchor_month"]):
            continue
        rows.append({"trigger": f"Retail gasoline, {m:%b %Y} monthly average",
                     "supports_note_if": f"<= ${r['falling'] * (1 - tc['gas_below_eia_pct'] / 100):.2f} "
                                         f"({tc['gas_below_eia_pct']}% below EIA's ${r['falling']:.2f})",
                     "against_note_if": f"> ${r['stable'] * (1 + tc['gas_above_stable_pct'] / 100):.2f} (today's price)",
                     "current": f"${mtd.mean():.2f} month-to-date ({len(mtd)} wk)" if m.to_period("M") == weekly.index[-1].to_period("M") else "",
                     "source": "EIA weekly (GASREGW); EIA STEO"})
    # 2. CPI gasoline print vs 1:1 nowcast
    rmse1 = float(p2_metrics.query("period == 'all' and h == 1")["rmse_retail_1to1"].iloc[0])
    n1 = nowcast.iloc[0]
    band = tc["gas_cpi_miss_rmse_multiple"] * rmse1
    rows.append({"trigger": f"CPI gasoline (NSA) for {pd.Timestamp(n1['target_month']):%b %Y}",
                 "supports_note_if": "within the band: pass-through assumption holds",
                 "against_note_if": f"outside {n1['retail_1to1_mom_pct']:+.1f}% +/- {band:.1f} pp "
                                    f"({tc['gas_cpi_miss_rmse_multiple']}x the 1-month RMSE of the 1:1 rule)",
                 "current": f"1:1 nowcast {n1['retail_1to1_mom_pct']:+.1f}% m/m", "source": "Module A/B"})
    # 3. Core inflation vs assumption
    core = dp.load_fred(raw, "CPILFESL").dropna()
    core3 = 100 * ((core.iloc[-1] / core.iloc[-4]) ** 4 - 1)
    gap_months = (core.index[-1].to_period("M") - core.index[-4].to_period("M")).n
    core_assump = p3["inflation"]["used"]["core"]["annual_pct"]
    rows.append({"trigger": "Core CPI, 3-month annualized (SA)",
                 "supports_note_if": f"< {core_assump:.1f}%",
                 "against_note_if": f"> {core_assump + tc['core_3m_ann_excess_pp']:.1f}% (assumption {core_assump:.1f}% + {tc['core_3m_ann_excess_pp']} pp)",
                 "current": f"{core3:.1f}% (to {core.index[-1]:%b %Y}" + (", spans a missing month" if gap_months != 3 else "") + ")",
                 "source": "BLS via FRED CPILFESL"})
    # 4. Brent vs EIA path
    steo_b = inf.steo_monthly(raw / "web" / "eia_steo_table.xlsx", "BREPUUS")[0]
    brent = dp.load_fred(raw, "DCOILBRENTEU").dropna()
    bm = brent[brent.index >= brent.index[-1].replace(day=1)]
    mth = brent.index[-1].replace(day=1)
    if mth in steo_b.index:
        rows.append({"trigger": f"Brent spot, {mth:%b %Y} average",
                     "supports_note_if": f"< ${steo_b[mth]:.0f} (EIA path)",
                     "against_note_if": f"> ${steo_b[mth] + tc['brent_above_steo_usd']:.0f} (EIA + ${tc['brent_above_steo_usd']})",
                     "current": f"${bm.mean():.2f} month-to-date", "source": "EIA via FRED DCOILBRENTEU; EIA STEO"})
    # 5. Entry level on the 2-year yield
    rows.append({"trigger": "2-year Treasury yield (entry test)",
                 "supports_note_if": f">= {setup['entry_2y_yield_consensus_pct']:.2f}% with gasoline outlook unchanged",
                 "against_note_if": f"falls toward {setup['rolldown_yield_pct (curve unchanged)']:.2f}% without gasoline falling below EIA",
                 "current": f"{setup['note_yield_pct (ASSUMPTION: Treasury 2Y par yield)']:.2f}% ({setup['pricing_date']})",
                 "source": "U.S. Treasury par yield curve"})
    df = pd.DataFrame(rows)
    df.to_csv(TABLES / "monitoring_triggers.csv", index=False)
    return df
