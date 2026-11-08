"""Phase 1: download raw data and record a manifest (source, URL, as-of time, last observation).

Fails loudly: any HTTP error or empty series raises. No fallback numbers are ever substituted.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
ALFRED_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={sid}&vintage_date={vd}"
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
UA: dict = {}  # library default User-Agent; FRED drops some custom UA strings


class DataError(RuntimeError):
    pass


def _get(url: str, retries: int = 3, **kw) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=(15, 120), **kw)
        except requests.RequestException as e:  # timeouts: retry, then fail loudly
            last = e
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise DataError(f"HTTP {r.status_code} for {url}")
        return r
    raise DataError(f"Download failed after {retries} tries: {url} ({last})")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def fetch_fred(sid: str, raw: Path) -> dict:
    url = FRED_CSV.format(sid=sid)
    text = _get(url).text
    df = pd.read_csv(io.StringIO(text))
    if df.shape[1] != 2 or df.empty:
        raise DataError(f"FRED series {sid} returned no data (bad ID?)")
    (raw / f"fred_{sid}.csv").write_text(text)
    vals = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    last = df.loc[vals.last_valid_index()]
    missing = df.loc[vals.isna(), df.columns[0]].tolist()
    return {"source": "FRED", "id": sid, "url": url, "retrieved": _now(),
            "first_obs": df.iloc[0, 0], "last_obs": last.iloc[0], "last_value": float(last.iloc[1]),
            "n_missing": len(missing), "missing_sample": missing[-5:]}


def fetch_alfred(sid: str, vintage: str, raw: Path) -> dict:
    url = ALFRED_CSV.format(sid=sid, vd=vintage)
    text = _get(url).text
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        raise DataError(f"ALFRED {sid} vintage {vintage} empty")
    out = raw / "alfred"
    out.mkdir(exist_ok=True)
    (out / f"{sid}_{vintage}.csv").write_text(text)
    return {"source": "ALFRED", "id": sid, "vintage": vintage, "url": url, "retrieved": _now(),
            "last_obs": df.iloc[-1, 0]}


def fetch_bls(series: list[str], start: int, end: int, raw: Path) -> dict:
    payload = {"seriesid": series, "startyear": str(start), "endyear": str(end)}
    r = requests.post(BLS_API, json=payload, headers=UA, timeout=60)
    js = r.json()
    if js.get("status") != "REQUEST_SUCCEEDED":
        raise DataError(f"BLS API failed: {js.get('message')}")
    (raw / f"bls_v1_{start}_{end}.json").write_text(json.dumps(js, indent=1))
    found = [s["seriesID"] for s in js["Results"]["series"] if s["data"]]
    if set(found) != set(series):
        raise DataError(f"BLS returned data for {found}, expected {series}")
    return {"source": "BLS API v1", "ids": series, "url": BLS_API, "retrieved": _now()}


def fetch_url(url: str, dest: Path, label: str) -> dict:
    r = _get(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return {"source": label, "url": url, "file": str(dest), "retrieved": _now(), "bytes": len(r.content)}


def run(cfg: dict) -> list[dict]:
    raw = Path(cfg["data"]["raw_dir"])
    raw.mkdir(parents=True, exist_ok=True)
    manifest = []
    for sid in cfg["data"]["fred_series"]:
        manifest.append(fetch_fred(sid, raw))
    # Spot-check ALFRED vintages; Module B pulls the full vintage set it needs.
    for sid in cfg["data"]["alfred_series"]:
        manifest.append(fetch_alfred(sid, cfg["project"]["as_of_date"], raw))
    this_year = int(cfg["project"]["as_of_date"][:4])
    manifest.append(fetch_bls(cfg["data"]["bls_series"], cfg["data"]["bls_start_year"], this_year, raw))
    t = cfg["data"]["treasury"]
    web = raw / "web"
    for yr in (this_year - 1, this_year):
        manifest.append(fetch_url(t["par_curve_url"].format(year=yr), web / f"ust_par_curve_{yr}.csv", "U.S. Treasury par yield curve"))
        manifest.append(fetch_url(t["bill_rates_url"].format(year=yr), web / f"ust_bill_rates_{yr}.csv", "U.S. Treasury daily bill rates"))
    manifest.append(fetch_url(t["auction_notes_url"], raw / "treasurydirect_notes_2y.json", "TreasuryDirect auction results"))
    manifest.append(fetch_url(t["auction_bills_url"], raw / "treasurydirect_bills_26w.json", "TreasuryDirect auction results"))
    manifest.append(fetch_release_dates(raw))
    manifest.append(fetch_url(cfg["data"]["eia_steo"]["page_url"], web / "eia_steo.html", "EIA STEO landing page"))
    manifest.append(fetch_url(cfg["data"]["fomc_calendar_url"], web / "fomc_calendar.html", "Federal Reserve FOMC calendar"))
    manifest.append(fetch_url(cfg["data"]["eia_steo"]["xlsx_url"], web / "eia_steo_table.xlsx", "EIA STEO"))
    (raw / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    return manifest


def revision_check(raw: Path, series: list[str], vintages: list[str], start: str = "1990-08-01") -> pd.DataFrame:
    """Compare old ALFRED vintages with the current FRED download; non-zero diffs = revisions."""
    rows = []
    for sid in series:
        cur = pd.read_csv(raw / f"fred_{sid}.csv", parse_dates=[0], index_col=0).iloc[:, 0]
        cur = pd.to_numeric(cur, errors="coerce")
        for vd in vintages:
            text = _get(ALFRED_CSV.format(sid=sid, vd=vd)).text
            if not text.strip():
                rows.append({"series": sid, "vintage": vd, "n_compared": 0, "note": "no vintage"})
                continue
            v = pd.to_numeric(pd.read_csv(io.StringIO(text), parse_dates=[0], index_col=0).iloc[:, 0], errors="coerce")
            j = pd.concat([v, cur], axis=1, join="inner").dropna()
            j = j[j.index >= start]
            diff = (j.iloc[:, 0] - j.iloc[:, 1]).abs()
            rows.append({"series": sid, "vintage": vd, "n_compared": len(j), "max_abs_diff": diff.max(),
                         "n_revised": int((diff > 1e-3).sum()), "note": ""})
    return pd.DataFrame(rows)


def availability_check(raw: Path, avail: pd.Series, months: list[str], sid: str = "CPIAUCSL") -> pd.DataFrame:
    """For sample reference months, confirm via ALFRED that the month is absent from the vintage
    the day before our availability date and present on it (i.e. our dates are not too early).
    Uses headline CPI (same BLS release as gasoline CPI; ALFRED vintages for the gasoline index
    only start around 2010). A vintage ALFRED does not have is reported, not guessed."""
    rows = []
    for m in months:
        m = pd.Timestamp(m)
        a = avail[m]
        res = {}
        for tag, vd in [("day_before", a - pd.Timedelta(days=1)), ("on_date", a)]:
            try:
                text = _get(ALFRED_CSV.format(sid=sid, vd=vd.date())).text
            except DataError:
                res[tag] = None
                continue
            v = pd.read_csv(io.StringIO(text), parse_dates=[0], index_col=0).iloc[:, 0]
            v = pd.to_numeric(v, errors="coerce").dropna()
            res[tag] = bool(m in v.index)
        ok = None if None in res.values() else ((not res["day_before"]) and res["on_date"])
        rows.append({"series": sid, "ref_month": m.date(), "assumed_release": a.date(),
                     "in_vintage_day_before": res["day_before"], "in_vintage_on_date": res["on_date"],
                     "ok": ok})
    return pd.DataFrame(rows)


def fetch_release_dates(raw: Path) -> dict:
    url = "https://alfred.stlouisfed.org/release/downloaddates?rid=10&ff=txt"
    return fetch_url(url, raw / "alfred_release_dates_cpi_rid10.txt", "ALFRED CPI release dates (release id 10)")
