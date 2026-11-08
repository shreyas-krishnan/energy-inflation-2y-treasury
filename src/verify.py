"""Phase 1: check the user's lead numbers against the downloaded sources.

Writes outputs/tables/phase1_claim_check.csv and outputs/tables/phase1_market_snapshot.csv.
Year-over-year rates use BLS NSA indices (the basis BLS uses in its release) and are
computed by date lookup, never by row offset (Oct 2025 is missing from CPI).
"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pandas as pd


def fred(raw: Path, sid: str) -> pd.Series:
    d = pd.read_csv(raw / f"fred_{sid}.csv", parse_dates=[0], index_col=0).iloc[:, 0]
    return pd.to_numeric(d, errors="coerce")


def bls_nsa(raw: Path, start: int, end: int) -> dict[str, pd.Series]:
    js = json.loads((raw / f"bls_v1_{start}_{end}.json").read_text())
    out = {}
    for s in js["Results"]["series"]:
        rows = {}
        for o in s["data"]:
            if not o["period"].startswith("M") or o["period"] == "M13":
                continue
            ts = pd.Timestamp(int(o["year"]), int(o["period"][1:]), 1)
            v = o["value"].strip()
            rows[ts] = float(v) if v not in ("-", "") else float("nan")
        out[s["seriesID"]] = pd.Series(rows).sort_index()
    return out


def yoy(s: pd.Series, month: str) -> float:
    t = pd.Timestamp(month)
    return 100 * (s[t] / s[t - pd.DateOffset(years=1)] - 1)


def mom(s: pd.Series, month: str) -> float:
    t = pd.Timestamp(month)
    return 100 * (s[t] / s[t - pd.DateOffset(months=1)] - 1)


def steo_path(xlsx: Path, code: str) -> pd.Series:
    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)["2tab"]
    rows = list(ws.iter_rows(values_only=True))
    years, months = rows[2], rows[3]
    yr, idx, vals = None, [], []
    for i in range(2, len(years)):
        yr = years[i] or yr
        if months[i] is None:
            continue
        for r in rows:
            if r and r[0] == code and r[i] is not None:
                idx.append(pd.Timestamp(f"{yr}-{months[i]}-01")); vals.append(float(r[i]))
    if not vals:
        raise ValueError(f"STEO code {code} not found")
    return pd.Series(vals, index=idx)


def run(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = Path(cfg["data"]["raw_dir"])
    yr = int(cfg["project"]["as_of_date"][:4])
    b = bls_nsa(raw, cfg["data"]["bls_start_year"], yr)
    ri = cfg["data"]["relative_importance_dec2025"]

    # Gasoline relative importance updated to Aug 2026 by relative price change (BLS method).
    g_nsa, a_nsa = fred(raw, "CUUR0000SETB01"), fred(raw, "CPIAUCNS")
    ri_aug = ri["gasoline_all_types"] * (g_nsa["2026-08-01"] / g_nsa["2025-12-01"]) / (a_nsa["2026-08-01"] / a_nsa["2025-12-01"])
    gas_sa_mom = mom(fred(raw, "CUSR0000SETB01"), "2026-09-01")
    head_sa_mom = mom(fred(raw, "CPIAUCSL"), "2026-09-01")
    contrib = ri_aug / 100 * gas_sa_mom

    brent = steo_path(raw / "web" / "eia_steo_table.xlsx", "BREPUUS")
    q4 = brent["2026-10-01":"2026-12-01"].mean()
    y27 = brent["2027-01-01":"2027-12-01"].mean()

    src_bls = "BLS API v1, NSA, 12-month % change"
    rows = [
        ("Sep 2026 headline CPI y/y", 3.7, yoy(b["CUUR0000SA0"], "2026-09-01"), src_bls + " (CUUR0000SA0)"),
        ("Sep 2026 core CPI y/y", 2.6, yoy(b["CUUR0000SA0L1E"], "2026-09-01"), src_bls + " (CUUR0000SA0L1E)"),
        ("Sep 2026 energy CPI y/y", 20.4, yoy(b["CUUR0000SA0E"], "2026-09-01"), src_bls + " (CUUR0000SA0E)"),
        ("Sep 2026 gasoline CPI m/m (SA)", 9.1, gas_sa_mom, "FRED CUSR0000SETB01"),
        ("Gasoline share of Sep headline SA m/m change (%)", 50.0, 100 * contrib / head_sa_mom,
         f"approx: Aug-2026 gasoline RI {ri_aug:.3f} (BLS Dec-2025 RI {ri['gasoline_all_types']} updated by relative prices) x gas m/m / headline m/m {head_sa_mom:.2f}"),
        ("Jun 2022 energy CPI y/y", 41.6, yoy(b["CUUR0000SA0E"], "2022-06-01"), src_bls + " (CUUR0000SA0E)"),
        ("Jun 2022 headline CPI y/y", 9.1, yoy(b["CUUR0000SA0"], "2022-06-01"), src_bls + " (CUUR0000SA0)"),
        ("EIA Oct-2026 STEO Brent Q4 2026 avg $/bbl", 105.0, q4, "EIA STEO Oct 2026, table 2, BREPUUS (monthly avg of Oct-Dec)"),
        ("EIA Oct-2026 STEO Brent 2027 avg $/bbl", 84.0, y27, "EIA STEO Oct 2026, table 2, BREPUUS (mean of 12 months)"),
    ]
    claims = pd.DataFrame(rows, columns=["claim", "user_value", "source_value", "source"])
    claims["source_value"] = claims["source_value"].round(2)
    claims["as_of"] = cfg["project"]["as_of_date"]

    def _read(kind):
        parts = [pd.read_csv(f, parse_dates=["Date"]) for y in (yr - 1, yr)
                 if (f := raw / "web" / f"ust_{kind}_{y}.csv").exists() and f.stat().st_size > 0]
        return pd.concat(parts, ignore_index=True).dropna(subset=["Date"]).sort_values("Date")
    curve, bills = _read("par_curve"), _read("bill_rates")
    c, bl = curve.iloc[-1], bills.iloc[-1]
    snap = [
        ("UST par yield 6 Mo", c["6 Mo"], c["Date"].date(), "U.S. Treasury daily par yield curve"),
        ("UST par yield 1 Yr", c["1 Yr"], c["Date"].date(), "U.S. Treasury daily par yield curve"),
        ("UST par yield 2 Yr", c["2 Yr"], c["Date"].date(), "U.S. Treasury daily par yield curve"),
        ("26-wk bill bank discount", bl["26 WEEKS BANK DISCOUNT"], bl["Date"].date(), "U.S. Treasury daily bill rates"),
        ("26-wk bill coupon equivalent", bl["26 WEEKS COUPON EQUIVALENT"], bl["Date"].date(), "U.S. Treasury daily bill rates"),
    ]
    for sid in ["DGS2", "DGS6MO", "DTB6", "DFF", "SOFR", "T5YIE", "DCOILBRENTEU", "GASREGW"]:
        s = fred(raw, sid).dropna()
        snap.append((sid, s.iloc[-1], s.index[-1].date(), "FRED"))
    note = json.loads((raw / "treasurydirect_notes_2y.json").read_text())[0]
    for k in ["cusip", "interestRate", "highYield", "highPrice", "issueDate", "datedDate", "maturityDate"]:
        snap.append((f"2y note {k}", note[k], note["issueDate"][:10], "TreasuryDirect auction results"))
    snapdf = pd.DataFrame(snap, columns=["item", "value", "observation_date", "source"])

    out = Path("outputs/tables"); out.mkdir(parents=True, exist_ok=True)
    claims.to_csv(out / "phase1_claim_check.csv", index=False)
    snapdf.to_csv(out / "phase1_market_snapshot.csv", index=False)
    return claims, snapdf
