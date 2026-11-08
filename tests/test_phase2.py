"""Phase 2 tests: real-time information sets, no look-ahead, regression and DM-test math."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import data_prep as dp
from src import passthrough as pt
from src import walkforward as wf

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


# ---------- availability rule ----------
def test_availability_rule_handles_gaps_and_double_releases():
    rel = pd.to_datetime(["2025-09-11", "2025-10-24", "2025-12-18",  # Nov 2025: no release
                          "2026-02-05", "2026-02-13"])               # Feb: two release events
    months = pd.to_datetime(["2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01", "2026-01-01"])
    a = dp.cpi_availability(months, rel)
    assert a[pd.Timestamp("2025-08-01")] == pd.Timestamp("2025-09-11")
    assert a[pd.Timestamp("2025-09-01")] == pd.Timestamp("2025-10-24")
    assert a[pd.Timestamp("2025-10-01")] == pd.Timestamp("2025-12-18")   # first release after gap
    assert a[pd.Timestamp("2025-11-01")] == pd.Timestamp("2025-12-18")
    assert a[pd.Timestamp("2026-01-01")] == pd.Timestamp("2026-02-13")   # later (conservative)


# ---------- real-time monthly gasoline ----------
def test_realtime_monthly_gas_partial_month_fill():
    # Oct 2026 has Mondays 5, 12, 19, 26. Observed two weeks; remaining two filled with last price.
    w = pd.Series([3.0, 4.0], index=pd.to_datetime(["2026-10-05", "2026-10-12"]))
    out = dp.realtime_monthly_gas(w, pd.to_datetime(["2026-10-01", "2026-11-01"]))
    assert out.iloc[0] == pytest.approx((3 + 4 + 4 + 4) / 4)
    assert out.iloc[1] == pytest.approx(4.0)


def test_realtime_monthly_gas_complete_month_not_filled():
    w = pd.Series([2.0, 2.0, 2.0, 5.0], index=pd.to_datetime(["2026-09-07", "2026-09-14", "2026-09-21", "2026-10-05"]))
    out = dp.realtime_monthly_gas(w, pd.to_datetime(["2026-09-01"]))
    assert out.iloc[0] == pytest.approx(2.0)  # September is complete: no fill from later price


def test_dlog_breaks_on_gaps():
    s = pd.Series([100.0, 110.0, 121.0], index=pd.to_datetime(["2025-09-01", "2025-11-01", "2025-12-01"]))
    d = dp.dlog(s)
    assert np.isnan(d.iloc[1])
    assert d.iloc[2] == pytest.approx(100 * np.log(121 / 110))


# ---------- no look-ahead on the real data ----------
@pytest.fixture(scope="module")
def real():
    g = dp.load_fred(RAW, "CUUR0000SETB01")
    w = dp.load_fred(RAW, "GASREGW").dropna()
    rel = dp.load_release_dates(RAW)
    av = dp.cpi_availability(pd.date_range("1990-01-01", g.dropna().index.max(), freq="MS"), rel)
    return g, w, av


@pytest.mark.parametrize("origin", ["2008-10-16", "2013-10-30", "2020-04-10", "2025-12-18", "2026-10-14"])
def test_information_set_contains_only_published_data(real, origin):
    g, w, av = real
    o = pd.Timestamp(origin)
    info = dp.information_set(o, g, av, w)
    assert (av.reindex(info.gas_cpi.index) <= o).all()
    assert (info.weekly_gas.index + pd.Timedelta(days=dp.WEEKLY_LAG_DAYS) <= o).all()
    # and nothing published by then is missing
    published = av[av <= o].index
    assert info.last_cpi_month == g.reindex(published).dropna().index.max()


@pytest.mark.parametrize("origin", ["2008-10-16", "2014-11-20", "2022-06-10", "2025-12-18", "2026-10-14"])
def test_forecast_unchanged_when_future_data_is_scrambled(real, origin):
    """Strongest check: replace every value not yet public at the origin with garbage.
    If the forecast changes, the forecaster used future data."""
    g, w, av = real
    o = pd.Timestamp(origin)
    base = wf.forecast_at_origin(dp.information_set(o, g, av, w), 2, 6, 120, "1990-09-01")

    rng = np.random.default_rng(0)
    g2 = g.copy()
    future_cpi = av.reindex(g2.index).isna() | (av.reindex(g2.index) > o)
    g2[future_cpi.values] = rng.uniform(1, 1000, future_cpi.sum())
    w2 = w.copy()
    future_w = w2.index + pd.Timedelta(days=dp.WEEKLY_LAG_DAYS) > o
    w2[future_w] = rng.uniform(0.5, 20, future_w.sum())
    scrambled = wf.forecast_at_origin(dp.information_set(o, g2, av, w2), 2, 6, 120, "1990-09-01")

    cols = ["model", "no_change", "seasonal", "retail_1to1"]
    pd.testing.assert_frame_equal(base[cols], scrambled[cols])


def test_walkforward_origins_never_precede_targets_data(real):
    g, w, av = real
    fc = wf.run(g, w, av, "2024-01-01", "1990-09-01", 2, 6, 120)
    # last CPI month used must have been published on or before the origin
    assert (av.reindex(fc["last_cpi_month"]).values <= fc["origin"].values).all()
    assert (fc["max_weekly_date_used"] + pd.Timedelta(days=dp.WEEKLY_LAG_DAYS) <= fc["origin"]).all()
    # every target is after the last published month
    assert (fc["target_month"] > fc["last_cpi_month"]).all()


# ---------- regression math ----------
def test_passthrough_recovers_known_coefficients():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2000-01-01", periods=300, freq="MS")
    x = pd.Series(rng.normal(0, 5, len(idx)), index=idx)
    seas = np.array([0, .5, -.3, .2, .1, 0, -.2, .3, -.1, 0, .4, -.5])
    y = 0.9 * x + 0.08 * x.shift(1) - 0.02 * x.shift(2) + seas[idx.month - 1] + rng.normal(0, 0.05, len(idx))
    res, _ = pt.fit_ols(y, x, 2)
    assert res.params["x_lag0"] == pytest.approx(0.9, abs=0.01)
    assert res.params["x_lag1"] == pytest.approx(0.08, abs=0.01)
    assert res.params["x_lag2"] == pytest.approx(-0.02, abs=0.01)
    assert res.params["m_2"] == pytest.approx(0.5, abs=0.05)


def test_predict_matches_fit_in_sample():
    rng = np.random.default_rng(2)
    idx = pd.date_range("2010-01-01", periods=120, freq="MS")
    x = pd.Series(rng.normal(0, 3, len(idx)), index=idx)
    y = 0.95 * x + rng.normal(0, 0.1, len(idx))
    beta, _ = pt.fit_numpy(y, x, 2)
    res, d = pt.fit_ols(y, x, 2)
    p = pt.predict(beta, x, d.index, 2)
    np.testing.assert_allclose(p.values, res.fittedvalues.values, atol=1e-8)


def test_contribution_uses_updated_weight():
    idx = pd.to_datetime(["2025-12-01", "2026-01-01", "2026-02-01"])
    g = pd.Series([100.0, 110.0, 99.0], index=idx)
    a = pd.Series([100.0, 100.0, 100.0], index=idx)
    t = pt.contribution_table(3.0, g, a)
    # Jan: weight 3.0 x +10% = 0.30 pp; Feb: weight 3.3 x -10% = -0.33 pp
    assert t["gas_contribution_pp"].tolist() == pytest.approx([0.30, -0.33])


# ---------- Diebold-Mariano ----------
def test_dm_sign_and_significance():
    rng = np.random.default_rng(3)
    e_bench = rng.normal(0, 2, 300)
    e_model = rng.normal(0, 1, 300)
    stat, p = wf.dm_test(e_model, e_bench, 1)
    assert stat < 0 and p < 0.01
    stat2, _ = wf.dm_test(e_bench, e_model, 1)
    assert stat2 == pytest.approx(-stat)


def test_dm_hand_example_h1():
    # d = e1^2 - e2^2 = [-3, -3, 3, -3]; mean -1.5; deviations [-1.5,-1.5,4.5,-1.5]
    # gamma0 = (3*2.25 + 20.25)/4 = 6.75; var(dbar) = 6.75/4; DM = -1.5/sqrt(1.6875) = -1.1547
    # HLN factor sqrt((T+1-2h+h(h-1)/T)/T) = sqrt(3/4); corrected stat = -1.0
    e1 = np.array([1.0, 1.0, 2.0, 1.0]); e2 = np.array([2.0, 2.0, 1.0, 2.0])
    stat, _ = wf.dm_test(e1, e2, 1)
    assert stat == pytest.approx(-1.0)
