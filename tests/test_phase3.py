"""Phase 3 tests: bond/bill math vs hand-checked and official Treasury figures; CPI aggregation."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src import data_prep as dp
from src import inflation as inf
from src import treasury as tr

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MAT = pd.Timestamp("2028-10-31")


# ---------- official auction results (TreasuryDirect, 91282CRU7 and 912797WX1) ----------
def test_note_auction_price_matches_treasurydirect():
    # 2-year note auctioned 2026-10-26: coupon 4.625, high yield 4.708, issue 2026-11-02,
    # dated 2026-10-31. TreasuryDirect high price 99.843155, accrued 0.25552 per 1000.
    assert tr.clean_price(4.708, "2026-11-02", 4.625, MAT, method="treasury") == pytest.approx(99.843155, abs=1e-6)
    assert tr.accrued("2026-11-02", 4.625, MAT) == pytest.approx(0.025552, abs=1e-6)


def test_bill_auction_price_and_investment_rate():
    # 26-week bill auctioned 2026-11-02: high rate 4.150, 182 days, price 97.901944, inv. rate 4.298
    assert tr.bill_price(4.150, 182) == pytest.approx(97.901944, abs=1e-6)
    assert round(tr.bill_bey(4.150, 182), 3) == 4.298


def test_bill_bey_matches_treasury_daily_rate():
    # Treasury daily bill rates 2026-11-06: 26-week bank discount 4.12, coupon equivalent 4.26;
    # on-the-run bill 912797WX1 matures 2027-05-06, settlement 2026-11-09 -> 178 days.
    assert round(tr.bill_bey(4.12, 178), 2) == 4.26


def test_long_bill_bey_satisfies_treasury_definition():
    d, t = 4.13, 364
    p = tr.bill_price(d, t) / 100
    y = tr.bill_bey(d, t) / 100
    assert p * (1 + y / 2) * (1 + y * (t / 365 - 0.5)) == pytest.approx(1.0, abs=1e-10)


# ---------- hand-checked pricing ----------
def test_end_of_month_coupon_schedule():
    s = tr.coupon_schedule(MAT, pd.Timestamp("2026-11-09"))
    assert [d.strftime("%Y-%m-%d") for d in s] == ["2026-10-31", "2027-04-30", "2027-10-31", "2028-04-30", "2028-10-31"]


def test_par_bond_on_coupon_date_prices_at_100():
    assert tr.dirty_price(4.625, "2027-04-30", 4.625, MAT) == pytest.approx(100.0, abs=1e-10)


def test_one_period_hand_example():
    # 1 coupon left, 90 of 181 days to go: dirty = (100 + 2.5) / 1.025^(90/181) at 5% yield
    mat = pd.Timestamp("2027-04-30")
    expected = 102.5 / 1.025 ** (90 / 181)
    assert tr.dirty_price(5.0, "2027-01-30", 5.0, mat) == pytest.approx(expected, rel=1e-12)


def test_duration_matches_numerical_derivative():
    y, settle = 4.51, "2026-11-09"
    r = tr.risk_measures(y, settle, 4.625, MAT)
    h = 0.0001
    up, dn = tr.dirty_price(y + 100 * h, settle, 4.625, MAT), tr.dirty_price(y - 100 * h, settle, 4.625, MAT)
    P = r["dirty_price"]
    assert (dn - up) / (2 * h * P) == pytest.approx(r["modified_duration"], rel=1e-5)
    assert (up + dn - 2 * P) / (h * h * P) == pytest.approx(r["convexity"], rel=1e-3)


def test_zero_coupon_macaulay_duration_is_time_to_maturity():
    r = tr.risk_measures(4.0, "2027-04-30", 0.0, MAT)
    assert r["macaulay_duration"] == pytest.approx(1.5, abs=1e-10)


# ---------- horizon analysis ----------
@pytest.fixture
def trade():
    return tr.Trade(pd.Timestamp("2026-11-09"), pd.Timestamp("2027-05-06"), 4.625, MAT, 4.51, 4.12, tr.bill_bey(4.12, 178))


def test_breakeven_equalizes_returns(trade):
    yb = trade.breakeven_yield()
    assert trade.note_return(yb) == pytest.approx(trade.bill_return(), abs=1e-12)


def test_breakeven_equals_no_arbitrage_forward(trade):
    assert trade.breakeven_yield() == pytest.approx(trade.forward_yield(), abs=0.005)  # < 0.5 bp


def test_note_return_falls_as_yield_rises(trade):
    r = [trade.note_return(y) for y in np.arange(3.5, 5.6, 0.25)]
    assert all(a > b for a, b in zip(r, r[1:]))


def test_note_return_includes_coupon(trade):
    # with the horizon yield equal to the start yield, return ~ carry: coupon + pull to par
    r = trade.note_return(4.51)
    assert 0.020 < r < 0.025


def test_curve_forward_on_flat_curve_is_flat():
    assert tr.curve_forward_par({0.5: 4.0, 1.0: 4.0, 2.0: 4.0}) == pytest.approx(4.0, abs=1e-10)


def test_bootstrap_reprices_par_bonds():
    curve = {0.5: 4.23, 1.0: 4.33, 2.0: 4.51}
    dfs = tr.bootstrap_semiannual(curve, 2.0)
    c = 4.51 / 200
    assert c * sum(dfs.values()) + dfs[2.0] == pytest.approx(1.0, abs=1e-12)


# ---------- Module C ----------
@pytest.fixture(scope="module")
def cpi():
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    idx = inf.load_indexes(RAW)
    w = inf.rolled_weights(idx, cfg["data"]["relative_importance_dec2025"])
    return idx, w, inf.component_changes(idx, w)


def test_components_rebuild_headline(cpi):
    idx, w, r = cpi
    chk = inf.aggregate_check(idx, w, r, "2026-01-01")
    assert len(chk) >= 9
    assert chk["diff_pp"].abs().max() < 0.005


def test_weights_sum_to_100(cpi):
    _, w, _ = cpi
    total = w[["core", "food", "gasoline", "other_energy"]].sum(axis=1)
    assert total["2026-01-01":].sub(100).abs().max() < 0.01


def test_one_to_one_rule_equals_retail_change():
    hist = pd.Series([4.0, 4.4], index=pd.to_datetime(["2026-08-01", "2026-09-01"]))
    path = pd.Series([4.4 * 0.9, 4.4 * 0.9], index=pd.to_datetime(["2026-10-01", "2026-11-01"]))
    g = inf.gas_cpi_mom(path, hist, "retail_1to1", None, 2)
    assert g.tolist() == pytest.approx([-0.1, 0.0])


def test_rising_mirrors_falling_around_stable():
    weekly = pd.Series([3.0, 3.0, 3.0, 3.0, 4.0], index=pd.to_datetime(
        ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"]))
    steo = pd.Series([3.0, 2.7], index=pd.to_datetime(["2026-09-01", "2026-10-01"]))
    sc, _ = inf.gasoline_scenarios(weekly, steo, pd.to_datetime(["2026-10-01"]))
    r = sc.iloc[0]
    assert np.log(r["rising"]) - np.log(r["stable"]) == pytest.approx(np.log(r["stable"]) - np.log(r["falling"]))
    assert r["falling"] == pytest.approx(3.0 * 2.7 / 3.0)


def test_consensus_mapping_only_moves_the_anchor():
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    m = cfg["treasury_trade"]["rate_scenarios"]["mappings"]
    assert set(m["hypothesis"]) == set(m["consensus"])
    diffs = {m["consensus"][s] - m["hypothesis"][s] for s in m["hypothesis"]}
    assert diffs == {1}                       # same step size; EIA path moves to the forward
    assert m["consensus"]["falling"] == 0 and m["hypothesis"]["stable"] == 0


def test_below_eia_is_one_step_below_falling():
    weekly = pd.Series([3.0, 3.0, 3.0, 3.0, 4.0], index=pd.to_datetime(
        ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"]))
    steo = pd.Series([3.0, 2.7], index=pd.to_datetime(["2026-09-01", "2026-10-01"]))
    sc, _ = inf.gasoline_scenarios(weekly, steo, pd.to_datetime(["2026-10-01"]))
    r = sc.iloc[0]
    assert np.log(r["falling"]) - np.log(r["below_eia"]) == pytest.approx(np.log(r["stable"]) - np.log(r["falling"]))
