"""Static charts for the memo and deck (matplotlib, light surface).

Palette: reference categorical slots in fixed order (blue, orange, aqua, yellow). Aqua and
yellow are below 3:1 contrast on the light surface, so every line is direct-labeled.
One y-axis per panel; series with different units are indexed to a common base.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 11,
    "axes.titleweight": "semibold", "axes.titlelocation": "left", "font.size": 9,
    "lines.linewidth": 2, "legend.frameon": False, "figure.dpi": 150,
})


def _end_label(ax, x, y, text, color, dy=0):
    ax.annotate(text, xy=(x, y), xytext=(6, dy), textcoords="offset points", color=INK,
                fontsize=8.5, va="center", ha="left")
    ax.plot([x], [y], marker="o", ms=4, color=color, mec=SURFACE, mew=1.5)


def _source(fig, text):
    fig.text(0.01, 0.005, text, fontsize=7, color=INK2, ha="left", va="bottom")


def gas_vs_cpi(gas_monthly: pd.Series, gas_cpi: pd.Series, out: Path, start="2015-01-01", base="2019-01-01"):
    c = gas_cpi[start:].dropna()
    g = gas_monthly[start:c.index.max()]  # same end month as CPI; drops the partial current month
    gi, ci = 100 * g / g[base], 100 * c / c[base]
    fig, axes = plt.subplots(2, 1, figsize=(8, 6.2), sharex=True, gridspec_kw={"height_ratios": [1.3, 1]})
    ax = axes[0]
    ax.plot(gi.index, gi, color=SERIES[0], label="Retail regular gasoline (EIA weekly, monthly avg)")
    ax.plot(ci.index, ci, color=SERIES[1], label="CPI gasoline, all types (BLS, NSA)")
    ax.set_title("Retail gasoline and the CPI gasoline index move almost one-for-one")
    ax.set_ylabel(f"Index, {pd.Timestamp(base):%b %Y} = 100")
    _end_label(ax, gi.index[-1], gi.iloc[-1], "Retail", SERIES[0], dy=10)
    _end_label(ax, ci.index[-1], ci.iloc[-1], "CPI gasoline", SERIES[1], dy=-10)
    ax.legend(loc="upper left", fontsize=8)
    ax = axes[1]
    gx = 100 * np.log(g).diff()
    cx = 100 * np.log(c).diff()
    ax.axhline(0, color=INK2, lw=0.8)
    ax.plot(gx.index, gx, color=SERIES[0], lw=1.6)
    ax.plot(cx.index, cx, color=SERIES[1], lw=1.6)
    ax.set_title("Monthly change", fontsize=10)
    ax.set_ylabel("Log change, %")
    _source(fig, "Sources: EIA via FRED (GASREGW), BLS via FRED (CUUR0000SETB01). Data as of 2026-11-08.")
    fig.tight_layout(rect=(0, 0.03, 0.93, 1))
    fig.savefig(out); plt.close(fig)


def passthrough_fit(y: pd.Series, fitted: pd.Series, r2: float, coefs: dict, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(9, 4), gridspec_kw={"width_ratios": [1, 1.4]})
    ax = axes[0]
    lim = [min(y.min(), fitted.min()) - 2, max(y.max(), fitted.max()) + 2]
    ax.plot(lim, lim, color=INK2, lw=1, ls="--")
    ax.scatter(fitted, y, s=14, color=SERIES[0], alpha=0.6, edgecolors=SURFACE, linewidths=0.5)
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("Fitted, % m/m"); ax.set_ylabel("Actual CPI gasoline, % m/m (log)")
    ax.set_title(f"In-sample fit, R² = {r2:.3f}")
    txt = "\n".join(f"{k}: {v:.3f}" for k, v in coefs.items())
    ax.text(0.04, 0.96, txt, transform=ax.transAxes, va="top", fontsize=8, color=INK)
    ax = axes[1]
    resid = y - fitted
    ax.axhline(0, color=INK2, lw=0.8)
    ax.bar(resid.index, resid.values, width=25, color=SERIES[0])
    ax.set_title("Residuals (actual − fitted), pp")
    _source(fig, "Model: NSA log changes, current + 2 lags of retail price, month dummies; 1990-12 to 2026-09. "
                 "Sources: BLS, EIA via FRED.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out); plt.close(fig)


LABELS = {"model": "Pass-through model", "no_change": "No change (CPI flat)",
          "seasonal": "Seasonal no-change", "retail_1to1": "Retail 1:1 rule"}


def forecast_errors(metrics: pd.DataFrame, out: Path, period: str = "all"):
    m = metrics[metrics["period"] == period].sort_values("h")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    ax = axes[0]
    for i, f in enumerate(LABELS):
        ax.plot(m["h"], m[f"rmse_{f}"], color=SERIES[i], marker="o", ms=5, mec=SURFACE, mew=1.2, label=LABELS[f])
    ax.set_title(f"Forecast error by horizon (origins 2001–2026, n≈{int(m['n'].iloc[0])})")
    ax.set_xlabel("Horizon, months after last published CPI")
    ax.set_ylabel("RMSE of cumulative change, pp")
    ax.set_xticks(range(1, 7)); ax.set_ylim(bottom=0)
    ax.legend(loc="lower right", fontsize=8)

    ax = axes[1]
    ax.axhline(1, color=INK2, lw=1)
    bench = [("no_change", "vs no change", 1), ("seasonal", "vs seasonal no-change", 2),
             ("retail_1to1", "vs retail 1:1 rule", 3)]
    ax.set_ylim(0, 1.3); ax.set_xlim(0.7, 8.6); ax.set_xticks(range(1, 7))
    ends = []
    for key, lab, ci in bench:
        r = m[f"rmse_ratio_vs_{key}"].values
        sig = m[f"dm_p_vs_{key}"].values < 0.05
        ax.plot(m["h"], r, color=SERIES[ci], lw=2)
        ax.scatter(m["h"][sig], r[sig], s=36, color=SERIES[ci], edgecolors=SURFACE, linewidths=1.2, zorder=3)
        ax.scatter(m["h"][~sig], r[~sig], s=36, facecolors=SURFACE, edgecolors=SERIES[ci], linewidths=1.6, zorder=3)
        ends.append([r[-1], lab])
    ends.sort()
    for j in range(1, len(ends)):
        ends[j][0] = max(ends[j][0], ends[j - 1][0] + 0.065)
    for (y, lab), (yv, _) in zip(ends, sorted([[e[0], e[1]] for e in ends])):
        ax.annotate(lab, xy=(6.15, y), fontsize=8, color=INK, va="center")
    ax.set_title("Model RMSE ÷ benchmark RMSE")
    ax.set_xlabel("Horizon, months after last published CPI")
    ax.set_ylabel("RMSE ratio (below 1 = model better)")
    ax.text(0.02, 0.03, "Filled marker: Diebold-Mariano p < 0.05   Hollow: not significant",
            transform=ax.transAxes, fontsize=7.5, color=INK2)
    _source(fig, "Real-time expanding-window test; target = cumulative log change in NSA CPI gasoline. Sources: BLS, EIA, ALFRED.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out); plt.close(fig)


SCEN_COLORS = {"falling": SERIES[0], "stable": SERIES[1], "rising": SERIES[2]}


def headline_scenarios(hist_yoy: pd.Series, paths: pd.DataFrame, out: Path, vintage: str):
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    h = hist_yoy.asfreq("MS")  # keep NaN months as gaps (Oct 2025 was not published)
    ax.plot(h.index, h.values, color=INK2, lw=2, label="Actual (BLS, NSA)")
    base_method = paths["passthrough"].iloc[0]
    for s, col in SCEN_COLORS.items():
        for method, ls, lw in [(base_method, "-", 2), ("estimated_model", (0, (3, 2)), 1.2)]:
            p = paths[(paths["scenario"] == s) & (paths["passthrough"] == method)].set_index("month")["headline_yoy_pct"].dropna()
            lab = f"{s.capitalize()} gasoline" if ls == "-" else None
            ax.plot(p.index, p.values, color=col, ls=ls, lw=lw, label=lab, marker="o" if ls == "-" else None,
                    ms=4, mec=SURFACE, mew=1)
            if ls == "-":
                ax.annotate(f"{s.capitalize()} {p.iloc[-1]:.1f}%", xy=(p.index[-1], p.iloc[-1]), xytext=(6, 0),
                            textcoords="offset points", fontsize=8.5, va="center", color=INK)
    ref = paths[(paths["scenario"] == "below_eia") & (paths["passthrough"] == base_method)].set_index("month")["headline_yoy_pct"].dropna()
    if len(ref):
        ax.plot(ref.index, ref.values, color=INK2, ls=(0, (1, 1.5)), lw=1.5, label="Below EIA (reference, no probability)")
        ax.annotate(f"Below EIA {ref.iloc[-1]:.1f}%", xy=(ref.index[-1], ref.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", fontsize=8, va="center", color=INK2)
    ax.plot([], [], color=INK2, ls=(0, (3, 2)), lw=1.2, label="Same, estimated pass-through model")
    ax.set_title("Headline CPI, 12-month change: three gasoline scenarios")
    ax.set_ylabel("% change from a year earlier")
    ax.legend(loc="upper left", fontsize=8)
    ax.margins(x=0.08)
    _source(fig, f"Gasoline: 1:1 retail pass-through (solid). Falling = EIA STEO {vintage} path; stable = latest weekly price; "
                 "rising = mirror of falling.\nCore, food, other energy: trailing 12-month pace + seasonal pattern (assumptions). "
                 "Oct 2026 y/y not computable: Oct 2025 CPI was not published. Sources: BLS, EIA.")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(out); plt.close(fig)


MAPPING_TITLES = {"hypothesis": "If the market prices flat gasoline",
                  "consensus": "If the market prices EIA's forecast"}


def note_vs_bill(trade, y_roll, y_be, y_fwd, sc: pd.DataFrame, out: Path, subtitle: str):
    maps = [m for m in sc["mapping"].dropna().unique() if m != "reference"]
    fig, axes = plt.subplots(1, len(maps), figsize=(6.2 * len(maps), 5), sharey=True, squeeze=False)
    ys = np.linspace(y_roll - 0.9, y_roll + 1.3, 221)
    note = [100 * trade.note_return(y) for y in ys]
    rb = 100 * trade.bill_return()
    for ax, mname in zip(axes[0], maps):
        ax.plot(ys, note, color=SERIES[0], lw=2, label="2-year note, 6-month return")
        ax.axhline(rb, color=SERIES[1], lw=2, label=f"6-month bill to maturity ({rb:.2f}%)")
        ax.axvline(y_be, color=INK, lw=1.2)
        ax.axvline(y_roll, color=INK2, lw=1, ls=(0, (2, 2)))
        m = sc[sc["mapping"] == mname].set_index("scenario")
        for s, col in list(SCEN_COLORS.items()) + [("below_eia", INK2)]:
            if s not in m.index:
                continue
            r = m.loc[s]
            y = r["horizon_1p5y_yield_pct (ASSUMPTION)"]
            hollow = s == "below_eia"
            ax.scatter([y], [r["note_hpr_pct"]], s=60, zorder=4, linewidths=1.6,
                       facecolors=SURFACE if hollow else col, edgecolors=col if hollow else SURFACE)
            name = "Below EIA (ref.)" if hollow else s.capitalize()
            ax.annotate(f"{name}: {r['excess_pct']:+.2f}%", xy=(y, r["note_hpr_pct"]), xytext=(8, 6),
                        textcoords="offset points", fontsize=8.5, color=INK)
        e = m.loc["probability-weighted", "excess_pct"]
        ax.set_title(f"{MAPPING_TITLES.get(mname, mname)}\nProbability-weighted edge vs bill: {e:+.2f}%")
        ax.set_xlabel("1.5-year Treasury yield at the horizon, %")
    ax0 = axes[0][0]
    lo = ax0.get_ylim()
    ax0.annotate(f"Breakeven = forward {y_be:.2f}%", xy=(y_be, lo[1]), xytext=(5, -4), textcoords="offset points",
                 va="top", fontsize=8, color=INK)
    ax0.annotate(f"Curve unchanged {y_roll:.2f}%", xy=(y_roll, lo[0]), xytext=(-5, 6), textcoords="offset points",
                 ha="right", va="bottom", fontsize=8, color=INK2)
    ax0.set_ylabel("Holding-period return, % (not annualized)")
    h_, l_ = ax0.get_legend_handles_labels(); axes[0][-1].legend(h_, l_, loc="lower left", fontsize=8)
    _source(fig, subtitle + ". Labels: return minus bill. Scenario yields = forward \u00b1 45 bp steps (assumption); "
                 "equal probabilities. Sources: TreasuryDirect, U.S. Treasury.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out); plt.close(fig)
