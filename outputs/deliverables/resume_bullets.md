# Resume bullets

_Generated from the model run of 2026-11-08T16:46:39; numbers update on each run._

- Built a reproducible Python pipeline (FRED/ALFRED, BLS, EIA, TreasuryDirect; 47 pytest tests including a no-look-ahead check) modeling how retail gasoline prices pass into CPI gasoline (pass-through 0.99, R² 0.98, 1990-2026).
- Ran a real-time walk-forward test over 308 CPI releases: the model cut 1-month forecast error 74% vs a no-change benchmark (RMSE 1.69 vs 6.45 pp) but lost to a simple 1:1 rule at every horizon, so I adopted the simpler rule.
- Priced the on-the-run 2-year Treasury against a 6-month bill (breakeven 1.5-year yield 4.61%, equal to the market forward) and showed an expected edge of -0.63% if EIA's gasoline forecast is already priced; recommended no trade, with entry at a 4.89% 2-year yield.
