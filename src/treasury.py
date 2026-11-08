"""Module D: Treasury note and bill math.

Conventions (U.S. Treasury / SIFMA street convention):
* Notes: semiannual coupons on an end-of-month schedule when maturity is a month end; accrued
  interest actual/actual within the coupon period; dirty price
      P = sum_{k=0}^{n-1} (C/2) v^{w+k} + 100 v^{w+n-1},  v = 1/(1+y/2),
      w = days(settle, next coupon) / days(prev coupon, next coupon).
* Bills: price = 100 (1 - d t / 360). Bond-equivalent (coupon-equivalent / investment) yield:
      t <= 182.5:  365 d / (360 - d t)
      t >  182.5:  root of the Treasury quadratic (31 CFR 356, App. B).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq


# ---------------- schedules and accrued ----------------
def coupon_schedule(maturity: pd.Timestamp, first_after: pd.Timestamp) -> list[pd.Timestamp]:
    """Coupon dates from the last one on/before `first_after` through maturity."""
    maturity = pd.Timestamp(maturity)
    eom = maturity == maturity + pd.offsets.MonthEnd(0)
    dates = [maturity]
    while dates[-1] > first_after:
        d = dates[-1] - pd.DateOffset(months=6)
        if eom:
            d = d + pd.offsets.MonthEnd(0)
        dates.append(d)
    return sorted(dates)


def _period(settle, maturity):
    sched = coupon_schedule(maturity, settle)
    prev = max(d for d in sched if d <= settle)
    future = [d for d in sched if d > settle]
    return prev, future


def accrued(settle, coupon: float, maturity) -> float:
    settle = pd.Timestamp(settle)
    prev, future = _period(settle, maturity)
    nxt = future[0]
    return coupon / 2 * (settle - prev).days / (nxt - prev).days


# ---------------- note pricing ----------------
def dirty_price(y: float, settle, coupon: float, maturity, method: str = "street") -> float:
    """y and coupon in percent. method="street": compound discounting of the fractional
    period (secondary-market convention). method="treasury": simple interest for the
    fractional period, as in Treasury's auction pricing formula (31 CFR 356, App. B)."""
    settle = pd.Timestamp(settle)
    prev, future = _period(settle, maturity)
    w = (future[0] - settle).days / (future[0] - prev).days
    v = 1 / (1 + y / 200)
    n = len(future)
    k = np.arange(n)
    at_next = float(np.sum(coupon / 2 * v ** k) + 100 * v ** (n - 1))  # value at next coupon date
    if method == "street":
        return at_next * v ** w
    if method == "treasury":
        return at_next / (1 + w * y / 200)
    raise ValueError(method)


def clean_price(y, settle, coupon, maturity, method: str = "street") -> float:
    return dirty_price(y, settle, coupon, maturity, method) - accrued(settle, coupon, maturity)


def yield_from_clean(price: float, settle, coupon, maturity) -> float:
    return brentq(lambda y: clean_price(y, settle, coupon, maturity) - price, -5, 30, xtol=1e-12)


def yield_from_dirty(dirty: float, settle, coupon, maturity) -> float:
    return brentq(lambda y: dirty_price(y, settle, coupon, maturity) - dirty, -5, 30, xtol=1e-12)


def risk_measures(y: float, settle, coupon, maturity) -> dict:
    """Macaulay/modified duration, convexity (per 100 of dirty price), DV01 (per 100 face)."""
    settle = pd.Timestamp(settle)
    prev, future = _period(settle, maturity)
    w = (future[0] - settle).days / (future[0] - prev).days
    n = len(future)
    t = w + np.arange(n)                     # in half-years
    cf = np.full(n, coupon / 2); cf[-1] += 100
    v = 1 / (1 + y / 200)
    pv = cf * v ** t
    P = pv.sum()
    mac = (pv * t).sum() / P / 2             # years
    mod = mac / (1 + y / 200)
    conv = (pv * t * (t + 1)).sum() / P * v ** 2 / 4
    return {"dirty_price": P, "macaulay_duration": mac, "modified_duration": mod,
            "convexity": conv, "dv01_per_100": mod * P / 10000}


# ---------------- bills ----------------
def bill_price(discount_pct: float, days: int) -> float:
    return 100 * (1 - discount_pct / 100 * days / 360)


def bill_bey(discount_pct: float, days: int) -> float:
    """Bond-equivalent (investment) yield in percent, Treasury formula."""
    d = discount_pct / 100
    p = 1 - d * days / 360
    if days <= 182.5:
        return 100 * 365 * d / (360 - d * days)
    a = days / (2 * 365) - 0.25
    b = days / 365
    c = (p - 1) / p
    return 100 * (-b + np.sqrt(b * b - 4 * a * c)) / (2 * a)


# ---------------- horizon analysis ----------------
@dataclass
class Trade:
    settle: pd.Timestamp
    horizon: pd.Timestamp
    coupon: float
    maturity: pd.Timestamp
    y0: float               # note yield at purchase, %
    bill_discount: float    # bill bank-discount rate, %
    reinvest_rate: float    # simple annual rate (%) for coupons received before the horizon

    @property
    def bill_days(self) -> int:
        return (self.horizon - self.settle).days

    def bill_return(self) -> float:
        return 100 / bill_price(self.bill_discount, self.bill_days) - 1

    def coupons_before_horizon(self) -> list[pd.Timestamp]:
        sched = coupon_schedule(self.maturity, self.settle)
        return [d for d in sched if self.settle < d <= self.horizon]

    def start_dirty(self) -> float:
        return dirty_price(self.y0, self.settle, self.coupon, self.maturity)

    def note_return(self, y_end: float) -> float:
        cash = dirty_price(y_end, self.horizon, self.coupon, self.maturity)
        for d in self.coupons_before_horizon():
            cash += self.coupon / 2 * (1 + self.reinvest_rate / 100 * (self.horizon - d).days / 365)
        return cash / self.start_dirty() - 1

    def breakeven_yield(self) -> float:
        rb = self.bill_return()
        return brentq(lambda y: self.note_return(y) - rb, -5, 30, xtol=1e-12)

    def forward_yield(self) -> float:
        """No-arbitrage forward yield of the note for delivery at the horizon, financed at the
        bill: F = (P0 - PV(coupons before T)) / DF(T), DF from the bill (matures at T)."""
        df_T = bill_price(self.bill_discount, self.bill_days) / 100
        r = bill_bey(self.bill_discount, self.bill_days) / 100
        pv_c = sum(self.coupon / 2 / (1 + r * (d - self.settle).days / 365) for d in self.coupons_before_horizon())
        F = (self.start_dirty() - pv_c) / df_T
        return yield_from_dirty(F, self.horizon, self.coupon, self.maturity)


def annualize(hpr: float, days: int) -> float:
    return 100 * hpr * 365 / days


# ---------------- curve ----------------
def interp_par(curve: dict[float, float], t: float) -> float:
    ks = sorted(curve)
    return float(np.interp(t, ks, [curve[k] for k in ks]))


def bootstrap_semiannual(curve: dict[float, float], tmax: float = 2.0) -> dict[float, float]:
    """Discount factors at 0.5-year steps from semiannual par yields (linear interpolation)."""
    dfs = {}
    t = 0.5
    while t <= tmax + 1e-9:
        c = interp_par(curve, t) / 200
        prior = sum(dfs[s] for s in dfs)
        dfs[t] = (1 - c * prior) / (1 + c)
        t = round(t + 0.5, 10)
    return dfs


def curve_forward_par(curve: dict[float, float], start: float = 0.5, length: float = 1.5) -> float:
    """Forward par yield (%) for a `length`-year bond starting in `start` years."""
    dfs = bootstrap_semiannual(curve, start + length)
    d0 = dfs[start]
    pay = [round(start + 0.5 * k, 10) for k in range(1, int(length * 2) + 1)]
    ann = sum(dfs[p] / d0 for p in pay)
    return 200 * (1 - dfs[pay[-1]] / d0) / ann
