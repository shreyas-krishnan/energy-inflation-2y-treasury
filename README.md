# Energy Inflation and the Two-Year Treasury

Question: does buying the current 2-year Treasury note (91282CRU7) and holding it six months beat
a 6-month bill bought the same day, if gasoline inflation fades? Interest-rate paths are scenario
assumptions anchored to market-implied forwards, not forecasts.

## Status
- [x] Phase 1: data verification and download (data as of 2026-11-08)
- [x] Phase 2: Modules A-B (gasoline pass-through, walk-forward test)
- [x] Phase 3: Modules C-D (headline CPI scenarios, Treasury returns) - rerun after 2026-11-10 releases
- [x] Phase 4: memo, deck, resume bullets (regenerated on every run)

## Run
```
pip install -r requirements.txt
npm install                  # docx + pptxgenjs, used only to lay out the memo and deck
python run_all.py            # download fresh data, rerun Modules A-D, rebuild memo/deck/bullets
python run_all.py --offline  # same, using files already in data/raw
python -m pytest             # tests
```

## Keeping it current
Every run downloads the latest data, refits everything and rewrites:
- `outputs/deliverables/Energy_Inflation_2Y_Treasury_Memo.docx` - investment memo
- `outputs/deliverables/Energy_Inflation_2Y_Treasury_Deck.pptx` - 7-slide pitch deck
- `outputs/deliverables/resume_bullets.md`
- `outputs/changes_since_last_run.md` - new releases picked up and material changes vs the
  previous run (thresholds in `WATCH`, `src/key_numbers.py`)
- `outputs/key_numbers.json` - every number the memo and deck use; one copy per run in
  `outputs/history/`

A scheduled task in the Claude app ("Energy inflation & 2-year Treasury: weekday update") runs
this at about 7:05 pm local time, Monday to Friday, then reports new releases, the
recommendation, key numbers and any triggers that fired. It stops and reports instead of
guessing if a download fails. It runs only while the app is open (otherwise on next launch).

The market data roll forward on their own (on-the-run note and bill, settlement date, horizon).
Manual upkeep:
- **BLS release dates**: add 2027 CPI dates to `release_calendar` in `config.yaml` once BLS posts
  its 2027 schedule (www.bls.gov blocks scripted downloads).
- **CPI weights**: when BLS publishes the December 2026 relative-importance table (early 2027),
  update `relative_importance_dec2025` (and its base month) in `config.yaml`.
- **Judgment calls**: scenario probabilities, `min_edge_pct` and trigger thresholds live in
  `config.yaml`.

## Data sources (Phase 1)
| Data | Source | Notes |
|---|---|---|
| CPI indices, gasoline prices, Brent, yields, SOFR, EFFR, breakevens | FRED public CSV (no key) | IDs in `config.yaml`; all verified to exist |
| Real-time vintages | ALFRED `alfredgraph.csv` | Endpoint verified; full vintage pull happens in Module B |
| NSA CPI cross-check + footnotes | BLS public API v1 | Oct 2025 headline/core/energy/food CPI missing (2025 lapse in appropriations) |
| Treasury par curve, bill rates | home.treasury.gov daily CSVs | Latest: 2026-11-06 |
| 2-year note and 26-week bill terms | TreasuryDirect auction API | |
| Brent and gasoline forecasts | EIA STEO Oct 2026 (STEO_m.xlsx) | Next STEO 2026-11-10 |
| Gasoline relative importance | BLS Dec 2025 table | Read manually; www.bls.gov blocks scripted downloads. Values in `config.yaml` |

`data/raw/manifest.json` records URL, retrieval time and last observation for every download.
Phase 1 outputs: `outputs/tables/phase1_claim_check.csv`, `outputs/tables/phase1_market_snapshot.csv`.

## Method notes (Phase 2)
- **Module A** (`src/passthrough.py`): 100*dlog NSA CPI gasoline on 100*dlog monthly-average EIA
  regular retail price, current + 2 lags, 11 month dummies, HAC (3 lags) SEs. NSA on both sides
  because no SA retail series exists and SA gasoline CPI is revised every February (ALFRED shows
  revisions up to 15 index points); NSA CPI and GASREGW are never revised.
- **Real time** (`src/data_prep.py`): CPI month m is public on its ALFRED release date (last
  release in month m+1, or first after it if none); weekly prices public 2 days after their
  Monday date. Spot-checked against ALFRED vintages in `phase2_availability_check.csv`.
- **Module B** (`src/walkforward.py`): one forecast origin per CPI release, 2001-2026, expanding
  window, horizons 1-6 months; benchmarks: CPI no change, seasonal no change, retail 1:1 rule.
  RMSE/MAE and Diebold-Mariano (HLN-corrected) in `walkforward_metrics.csv`.
- Cleveland Fed nowcast comparison not done: the page offers no downloadable history, and it
  nowcasts headline CPI, not CPI gasoline.

## Method notes (Phase 3)
- **Module C** (`src/inflation.py`): headline NSA index chained from four components with BLS
  relative-importance weights (Dec 2025, rolled by relative prices); rebuilds actual 2026
  headline to <0.005 pp (`inflation_aggregation_check.csv`). Gasoline: retail scenario path ->
  CPI gasoline by the 1:1 rule (baseline) and the Module A model (sensitivity). Core, food and
  other energy are ASSUMPTIONS: trailing 12-month pace + 10-year calendar-month pattern.
  Scenarios: falling = EIA STEO retail path (anchored to the last complete month), stable =
  latest weekly price, rising = mirror of falling. No futures path (EIA stopped publishing NYMEX
  futures in April 2024; no free source).
- **Module D** (`src/treasury.py`, `src/phase3.py`): on-the-run 2-year note and 26-week bill as
  of the pricing date; settle T+1; horizon = bill maturity. Note yield = Treasury 2Y par yield
  (ASSUMPTION: FedInvest prices blocked). Breakeven horizon yield = no-arbitrage forward.
  Rate scenarios = forward +/- steps of half the IQR of historical forward errors (ASSUMPTION),
  under two views of what is priced in: `hypothesis` (market prices flat gasoline) and
  `consensus` (market prices EIA's forecast). Same steps and probabilities; only the anchor
  moves. A `below_eia` reference path shows what gasoline must do for the note to win under
  the consensus view. Probabilities in `config.yaml` (equal weights placeholder).

## Tests
`python -m pytest` - includes a test that scrambles all data not yet published at each origin
and checks the forecast does not change.
