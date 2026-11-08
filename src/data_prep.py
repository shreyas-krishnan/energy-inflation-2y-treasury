"""Shared data loading and real-time (as-of) information sets.

Real-time rules (see README):
* CPI for reference month m becomes available on its BLS release date, taken from ALFRED's
  CPI release calendar (release id 10). Rule: the LAST release date in month m+1; if month m+1
  has no release (shutdowns), the first release date after month m+1. Using the last date in a
  month is conservative when a month has two release events (e.g. February seasonal-factor
  revisions).
* An EIA weekly retail gasoline observation dated Monday d is treated as available from d + 2
  days (EIA posts Monday prices Monday evening, Tuesday after holidays).
* NSA gasoline CPI and GASREGW are unrevised in ALFRED vintages (checked in
  outputs/tables/phase2_revision_check.csv), so the latest vintage equals the real-time value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

WEEKLY_LAG_DAYS = 2


def load_fred(raw: Path, sid: str) -> pd.Series:
    s = pd.read_csv(Path(raw) / f"fred_{sid}.csv", parse_dates=[0], index_col=0).iloc[:, 0]
    s = pd.to_numeric(s, errors="coerce")
    s.name = sid
    return s


def load_release_dates(raw: Path) -> pd.DatetimeIndex:
    txt = (Path(raw) / "alfred_release_dates_cpi_rid10.txt").read_text()
    d = pd.to_datetime(re.findall(r"^\d{4}-\d{2}-\d{2}$", txt, flags=re.M))
    return pd.DatetimeIndex(sorted(set(d)))


def cpi_availability(months: pd.DatetimeIndex, releases: pd.DatetimeIndex) -> pd.Series:
    """Date on which each CPI reference month (month-start timestamps) was first published."""
    out = {}
    for m in months:
        nxt = m + pd.offsets.MonthBegin(1)
        end_nxt = nxt + pd.offsets.MonthEnd(0)
        in_next = releases[(releases >= nxt) & (releases <= end_nxt)]
        if len(in_next):
            out[m] = in_next.max()
        else:
            later = releases[releases > end_nxt]
            out[m] = later.min() if len(later) else pd.NaT
    return pd.Series(out, name="available")


def monthly_avg(weekly: pd.Series) -> pd.Series:
    """Calendar-month average of weekly observations (all weeks dated in the month)."""
    w = weekly.dropna()
    return w.groupby(w.index.to_period("M")).mean().to_timestamp()


@dataclass
class InfoSet:
    origin: pd.Timestamp
    gas_cpi: pd.Series      # NSA gasoline CPI, only months published by `origin`
    weekly_gas: pd.Series   # weekly retail gasoline, only weeks available by `origin`
    last_cpi_month: pd.Timestamp


def information_set(origin: pd.Timestamp, gas_cpi: pd.Series, avail: pd.Series,
                    weekly_gas: pd.Series) -> InfoSet:
    """Everything a forecaster could see at `origin` (CPI release morning)."""
    origin = pd.Timestamp(origin)
    a = avail.reindex(gas_cpi.index)
    cpi = gas_cpi[(a <= origin).fillna(False).values].dropna()
    w = weekly_gas.dropna()
    w = w[w.index + pd.Timedelta(days=WEEKLY_LAG_DAYS) <= origin]
    return InfoSet(origin, cpi, w, cpi.index.max())


def realtime_monthly_gas(weekly: pd.Series, months: pd.DatetimeIndex) -> pd.Series:
    """Monthly average retail price using only `weekly` (already truncated to an origin).

    Weeks not yet observed are filled with the last observed weekly price (no-change
    assumption for retail gasoline). Months entirely in the future get the last price.
    """
    w = weekly.dropna()
    last_date, last_price = w.index[-1], w.iloc[-1]
    complete = monthly_avg(w)
    out = {}
    for m in months:
        end = m + pd.offsets.MonthEnd(0)
        if end < last_date:  # month fully in the past: plain average of its weeks, no filling
            out[m] = complete.get(m, np.nan)
            continue
        obs = w[(w.index >= m) & (w.index <= end)]
        n_expected = len(pd.date_range(m, end, freq="W-MON"))
        n_fill = max(n_expected - len(obs), 0)
        vals = np.concatenate([obs.values, np.repeat(last_price, n_fill)])
        out[m] = vals.mean()
    return pd.Series(out)


def dlog(s: pd.Series) -> pd.Series:
    """100 x monthly log change, requiring consecutive months."""
    s = s.dropna()
    prev = s.shift(1)
    gap = s.index.to_period("M").astype(int) - pd.Series(s.index.to_period("M").astype(int), index=s.index).shift(1)
    out = 100 * np.log(s / prev)
    out[gap.values != 1] = np.nan
    return out
