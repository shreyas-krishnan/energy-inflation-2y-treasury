# Energy Inflation and the Two-Year Treasury

[![Run analysis](https://github.com/shreyas-krishnan/energy-inflation-2y-treasury/actions/workflows/run-analysis.yml/badge.svg)](https://github.com/shreyas-krishnan/energy-inflation-2y-treasury/actions/workflows/run-analysis.yml)

### **[Open the live results page &rarr;](https://shreyas-krishnan.github.io/energy-inflation-2y-treasury/)**

**The question:** if gasoline inflation keeps fading, does buying the current 2-year Treasury note
and holding it six months beat a 6-month bill bought the same day?

The project answers that from public data (FRED, BLS, EIA, U.S. Treasury, TreasuryDirect, the Fed)
and answers it again every weekday. The results page shows:

- the current answer and what would flip it,
- the main findings in plain English,
- how the test works, step by step,
- an interactive "note vs bill" explorer,
- the charts, scenarios and watchlist,
- what each of the automated checks proves.

Interest-rate paths are scenario assumptions anchored to market prices. Nothing here forecasts the
Fed. This is a student research project, not investment advice.

## Run it

**On GitHub (no installs).** Open the **Actions** tab, choose **Run analysis**, click **Run workflow**,
then the green **Run workflow** button. A few minutes later the results page updates. GitHub also
runs it on its own every weekday at about 7:15 pm US Central. If a download or a check fails, the
run stops with a red X, nothing is published, and GitHub emails you.

**On your Mac.**

```bash
cd ~/energy-inflation-2y-treasury
python3 run_all.py          # fresh data -> Modules A-D -> memo and deck -> checks -> website
open docs/index.html        # the results page, built locally
```

Add `--offline` to rerun on the data already in `data/raw/`. First time on a new computer:

```bash
git clone https://github.com/shreyas-krishnan/energy-inflation-2y-treasury.git
cd energy-inflation-2y-treasury
pip3 install -r requirements.txt
npm install                 # docx + pptxgenjs, used only to lay out the memo and deck
```

Run `git pull` before working locally so you have the snapshots GitHub saved.

## How the analysis works

| Step | Question | Code |
|---|---|---|
| 1. Collect and check the data | Are the starting numbers right? Every file is stamped with when it was pulled; a failed download stops the run. | `src/download.py`, `src/verify.py` |
| 2. Module A: pass-through | When pump prices move, how much shows up in CPI gasoline? | `src/passthrough.py` |
| 3. Module B: real-time test | Would it have worked live, using only data published on each date? | `src/walkforward.py` |
| 4. Module C: headline inflation | Where does headline CPI go if gasoline falls, holds or rises? | `src/inflation.py` |
| 5. Module D: note vs bill | Given those paths, does the note beat the bill? | `src/treasury.py`, `src/phase3.py` |
| 6. Report and watch | What changed, and what would change the answer? | `src/monitor.py`, `src/report.py`, `src/site.py` |

Only one inflation channel is modeled (retail gasoline into CPI gasoline). Core, food and other
energy are labeled assumptions.

## What a run produces

| Output | What it is |
|---|---|
| `docs/index.html` | The results page (published by GitHub Pages) |
| `outputs/deliverables/` | Investment memo (.docx), 7-slide deck (.pptx), resume bullets |
| `outputs/key_numbers.json` | Every number the memo, deck and page use |
| `outputs/changes_since_last_run.md` | New releases picked up and material changes vs the previous run |
| `outputs/tables/`, `outputs/figures/` | Every table and chart the model writes |
| `outputs/history/` | One key-number snapshot per run. This is the only output kept in git; everything else is rebuilt each run and published on the results page. |

## Automated checks

`python3 -m pytest` runs 50 checks in seven groups. They include:

- **No peeking at the future:** a check scrambles all data not yet published at each forecast date and confirms the forecasts do not change.
- **Bond math against the Treasury:** pricing reproduces actual TreasuryDirect auction results.
- **Traceable numbers:** reports may only quote numbers the model produced.

The results page lists every check in plain English with its latest result. `run_all.py` runs them
automatically.

## Keeping it current

Market data roll forward on their own: on-the-run note and bill, settlement date, horizon. Manual upkeep:

- **BLS release dates:** add the 2027 CPI dates to `release_calendar` in `config.yaml` once BLS
  posts its 2027 schedule (www.bls.gov blocks scripted downloads).
- **CPI weights:** when BLS publishes the December 2026 relative-importance table (early 2027),
  update `relative_importance_dec2025` (and its base month) in `config.yaml`.
- **Judgment calls:** scenario probabilities, `min_edge_pct` and trigger thresholds live in
  `config.yaml`.
- **New checks:** a new test must also get a plain-English line in `CHECK_GROUPS` (`src/site.py`).
  A check enforces this.

## Data sources

| Data | Source | Notes |
|---|---|---|
| CPI indices, gasoline prices, Brent, yields, SOFR, EFFR, breakevens, term premiums | FRED public CSV (no key) | IDs in `config.yaml` |
| Real-time vintages, CPI release dates | ALFRED | Used to prove the real-time test saw only published data |
| NSA CPI cross-check | BLS public API v1 | Oct 2025 CPI was never published (2025 lapse in appropriations) |
| Treasury par curve, bill rates | home.treasury.gov daily CSVs | |
| 2-year note and 26-week bill terms | TreasuryDirect auction API | |
| Brent and gasoline forecasts | EIA STEO (STEO_m.xlsx) | |
| Gasoline relative importance | BLS Dec 2025 table | Read manually; values in `config.yaml` |

`data/raw/manifest.json` records URL, retrieval time and last observation for every download.

## Method notes

- **Module A** (`src/passthrough.py`): 100*dlog NSA CPI gasoline on 100*dlog monthly-average EIA
  regular retail price, current + 2 lags, 11 month dummies, HAC (3 lags) standard errors. NSA on both sides
  because no SA retail series exists and SA gasoline CPI is revised every February (ALFRED shows
  revisions up to 15 index points). NSA CPI and GASREGW are never revised.
- **Real time** (`src/data_prep.py`): CPI month m is public on its ALFRED release date (last
  release in month m+1, or first after it if none). Weekly prices are public 2 days after their
  Monday date. Spot-checked against ALFRED vintages in `phase2_availability_check.csv`.
- **Module B** (`src/walkforward.py`): one forecast origin per CPI release, 2001-2026, expanding
  window, horizons 1-6 months. Benchmarks: CPI no change, seasonal no change, retail 1:1 rule.
  RMSE/MAE and Diebold-Mariano (HLN-corrected) are in `walkforward_metrics.csv`. The 1:1 rule beat
  the estimated model, so it is the scenario baseline and the model is a sensitivity.
- **Module C** (`src/inflation.py`): headline NSA index chained from four components with BLS
  relative-importance weights (Dec 2025, rolled forward by relative prices). It rebuilds actual 2026
  headline CPI to within 0.005 pp. Core, food and other energy are ASSUMPTIONS: trailing 12-month pace
  plus a 10-year calendar-month pattern. Gasoline scenarios:
  - falling = EIA STEO retail path,
  - stable = latest weekly price,
  - rising = mirror of falling.

  No futures path is used: EIA stopped publishing NYMEX futures in April 2024 and there is no free source.
- **Module D** (`src/treasury.py`, `src/phase3.py`): on-the-run 2-year note and 26-week bill; settle
  T+1; horizon = bill maturity. Note yield = Treasury 2Y par yield (ASSUMPTION: FedInvest prices
  are blocked). Breakeven horizon yield = no-arbitrage forward. Rate scenarios = forward ± steps of
  half the IQR of historical forward errors (ASSUMPTION), under two views of what is priced:
  - `hypothesis`: the market prices flat gasoline,
  - `consensus`: the market prices EIA's forecast.

  Probabilities are in `config.yaml` (equal-weight placeholder).
