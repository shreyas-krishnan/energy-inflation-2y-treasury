"""Website tests: page text quotes only model numbers, every link resolves, every check is explained."""
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src import site

ROOT = Path(__file__).resolve().parents[1]
KN = ROOT / "outputs" / "key_numbers.json"
TABLES = ROOT / "outputs" / "tables"
SHOWN_TABLES = ["monitoring_triggers.csv", "monitoring_calendar.csv", "treasury_scenarios.csv",
                "treasury_sensitivity.csv"]
needs_run = pytest.mark.skipif(not KN.exists(), reason="run python run_all.py first")


def _allowed_numbers(k: dict, cfg: dict) -> set[str]:
    out = set()

    def add(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            if v != v:  # NaN
                return
            for d in range(4):
                for s in (f"{v:.{d}f}", f"{abs(v):.{d}f}"):
                    out.add(s.lstrip("+-"))
        elif isinstance(v, str):
            out.update(re.findall(r"\d+(?:\.\d+)?", v))
        elif isinstance(v, (list, tuple)):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
    add(k)
    add(cfg["triggers"])
    add(cfg["recommendation"]["min_edge_pct"])
    for name in SHOWN_TABLES:  # model outputs shown as tables on the page
        for v in pd.read_csv(TABLES / name).to_numpy().ravel():
            add(v.item() if hasattr(v, "item") else v)
    # structural tokens: step numbers, "1.5-year", the 1% illustration, the 5% significance level, the 1990
    # start of the forward-error history, and the October 2025 CPI that BLS never published
    out.update({"1", "2", "3", "4", "5", "6", "1.5", "1990", "2025"})
    return out


class _Chdir:
    def __enter__(self):
        self.cwd = os.getcwd()
        os.chdir(ROOT)

    def __exit__(self, *a):
        os.chdir(self.cwd)


@needs_run
def test_site_text_uses_only_model_numbers():
    k = json.loads(KN.read_text())
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    with _Chdir():
        page = site.render(k, cfg, checks=None)
    text = site.visible_text(page)
    text = re.sub(r"\b[0-9A-Z]{9}\b", "", text)                  # CUSIPs
    text = re.sub(r"\b\d{4}-\d{2}(-\d{2})?\b", "", text)         # ISO months / dates
    text = re.sub(r"\b\d+(\.\d+)?[-\u2011](year|month|day)\b", "", text)  # "2-year", "1.5-year", "178-day"
    text = text.replace("1:1", "")
    allowed = _allowed_numbers(k, cfg)
    stray = sorted({f for f in re.findall(r"\d+(?:\.\d+)?", text) if f not in allowed})
    assert not stray, f"numbers in the site's text not traceable to the model run: {stray}"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for a, v in attrs:
            if a in ("href", "src") and v and not v.startswith(("http", "#", "mailto:")):
                self.refs.append(v.split("?")[0])


@needs_run
@pytest.mark.skipif(not (ROOT / "outputs" / "deliverables").exists(), reason="run python run_all.py first")
def test_site_links_point_to_built_files(tmp_path):
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    with _Chdir():
        index = site.build(cfg, out=tmp_path / "docs")
    p = _Links()
    p.feed(index.read_text())
    assert p.refs, "no local links found"
    missing = [r for r in p.refs if not (index.parent / r).exists()]
    assert not missing, f"the page links to files that were not built: {missing}"
    data = json.loads(re.search(r'id="site-data">(.*?)</script>', index.read_text(), re.S).group(1))
    keys = {k for p in data["explorer"]["points"] for k in p["keys"]}
    assert {"rolldown", "hyp:falling", "hyp:stable", "hyp:rising", "cons:falling", "cons:stable", "cons:rising"} <= keys


def test_every_check_is_explained():
    with _Chdir():
        defined = site.defined_tests()
    described = site.described_tests()
    assert defined - described == set(), f"add a plain-English line to CHECK_GROUPS in src/site.py for: {defined - described}"
    assert described - defined == set(), f"CHECK_GROUPS lists checks that no longer exist: {described - defined}"
