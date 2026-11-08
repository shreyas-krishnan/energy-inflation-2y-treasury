"""Phase 4 tests: memo prose uses only model numbers; recommendation rule; change report; parsers."""
import json
import re
import zipfile
from pathlib import Path

import pytest
import yaml

from src import key_numbers as kn
from src import monitor, report

ROOT = Path(__file__).resolve().parents[1]
KN = ROOT / "outputs" / "key_numbers.json"


def _allowed_numbers(k: dict, cfg: dict) -> set[str]:
    out = set()

    def add(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            for d in range(4):
                for s in (f"{v:.{d}f}", f"{abs(v):.{d}f}"):
                    out.add(s.lstrip("+-"))
        elif isinstance(v, str):
            out.update(re.findall(r"\d+(?:\.\d+)?", v))
        elif isinstance(v, list):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
    for v in k.values():
        add(v)
    for v in cfg["triggers"].values():
        add(v)
    add(cfg["recommendation"]["min_edge_pct"])
    # structural tokens: section numbers, maturities named in words, the 10% illustration, sample-split years
    out.update({"1", "2", "3", "4", "5", "6", "7", "8", "10", "1.5", "1990", "2007", "2008", "2019", "2020", "2025"})
    return out


@pytest.mark.skipif(not KN.exists(), reason="run python run_all.py first")
def test_memo_prose_uses_only_model_numbers():
    k = json.loads(KN.read_text())
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    import os
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        blocks = report.memo_blocks(k, cfg)
    finally:
        os.chdir(cwd)
    text = []
    for b in blocks:
        if b["type"] == "p":
            text.append("".join(r[0] for r in b["runs"]))
        elif b["type"] == "callout":
            text += [b["title"], b["text"]]
        elif b["type"] == "bullets":
            text += b["items"]
    prose = " ".join(text)
    prose = re.sub(r"\b(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}", "", prose)
    prose = re.sub(r"\b\d{4}-\d{2}(-\d{2})?(T[\d:]+)?\b", "", prose)          # ISO dates / timestamps
    prose = re.sub(r"\b[0-9A-Z]{9}\b", "", prose)                              # CUSIPs
    prose = re.sub(r"\b\d+-(year|month|day)\b", "", prose)                    # "2-year", "6-month"
    prose = prose.replace("1:1", "").replace("one-for-one", "")
    allowed = _allowed_numbers(k, cfg)
    found = re.findall(r"\d+(?:\.\d+)?", prose)
    stray = sorted({f for f in found if f not in allowed})
    assert not stray, f"numbers in memo prose not traceable to key_numbers.json: {stray}"


def test_recommendation_rule():
    assert kn.recommend(0.15, 0.10)[0] == "BUY"
    assert kn.recommend(0.10, 0.10)[0] == "BUY"
    assert kn.recommend(0.05, 0.10)[0] == "NO_TRADE"
    assert kn.recommend(-0.63, 0.10)[1] == "No trade at current prices"


def test_change_report_flags_new_data_and_recommendation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()
    monkeypatch.setattr(kn, "HIST", tmp_path / "outputs" / "history")
    base = {"generated_at": "t0", "as_of": "2026-11-08", "latest_cpi_month": "2026-09", "steo_vintage": "October 2026",
            "last_weekly_gas_date": "2026-11-02", "pricing_date": "2026-11-06", "tp_asof": "2026-10-30",
            "rec_short": "No trade at current prices", "y0": 4.51}
    first = kn.snapshot(base)
    assert "First snapshot" in first
    import time
    time.sleep(1.1)  # snapshot files are time-stamped to the second
    new = {**base, "generated_at": "t1", "latest_cpi_month": "2026-10", "rec_short": "Buy the 2-year note", "y0": 4.90}
    txt = kn.snapshot(new)
    assert "latest_cpi_month: 2026-09 -> 2026-10" in txt
    assert "Recommendation" in txt and "Buy the 2-year note" in txt
    assert "2-year yield" in txt


def test_fomc_parser_ignores_footnote_dates(tmp_path):
    html = ("<h4>2027 FOMC Meetings</h4><p>January 26-27</p><p>March 16-17*</p>"
            "<p>Note: A two-day meeting is scheduled for January 25-26, 2028.</p>")
    f = tmp_path / "fomc.html"; f.write_text(html)
    got = [(m["date"].strftime("%Y-%m-%d"), "projections" in m["event"]) for m in monitor.fomc_meetings(f)]
    assert got == [("2027-01-27", False), ("2027-03-17", True)]


def test_steo_next_release_parser(tmp_path):
    f = tmp_path / "steo.html"
    f.write_text("<p>Release Date: October 6, 2026 | Next Release Date: <b>November 10, 2026</b></p>")
    assert str(monitor.steo_next_release(f).date()) == "2026-11-10"


@pytest.mark.skipif(not (ROOT / "outputs/deliverables").exists(), reason="run python run_all.py first")
def test_deliverables_are_well_formed():
    d = ROOT / "outputs" / "deliverables"
    with zipfile.ZipFile(d / "Energy_Inflation_2Y_Treasury_Memo.docx") as z:
        assert "word/document.xml" in z.namelist()
        assert not any(n.endswith("/") for n in z.namelist())
    with zipfile.ZipFile(d / "Energy_Inflation_2Y_Treasury_Deck.pptx") as z:
        slides = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        assert 6 <= len(slides) <= 8
    assert (d / "resume_bullets.md").read_text().count("\n- ") in (2, 3)
