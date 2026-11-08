"""Phase 4 runner: monitoring plan, key-numbers snapshot + change report, memo/deck/resume."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import key_numbers, monitor, report

TABLES = Path("outputs/tables")


def run(cfg: dict, p3: dict) -> dict:
    raw = Path(cfg["data"]["raw_dir"])
    setup = p3["treasury"]["setup"]
    start = pd.Timestamp(cfg["project"]["as_of_date"])
    cal = monitor.calendar(cfg, raw, start, pd.Timestamp(setup["horizon_date"]))
    cal.to_csv(TABLES / "monitoring_calendar.csv", index=False)
    metrics = pd.read_csv(TABLES / "walkforward_metrics.csv")
    nowcast = pd.read_csv(TABLES / "nowcast_asof.csv")
    monitor.triggers(cfg, raw, p3, metrics, nowcast)
    k = key_numbers.collect(cfg, p3)
    changes = key_numbers.snapshot(k)
    paths = report.publish(k, cfg)
    return {"key_numbers": k, "changes": changes, "paths": paths}
