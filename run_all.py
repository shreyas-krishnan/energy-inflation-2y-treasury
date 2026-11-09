"""Run the full pipeline: Phase 1 (data), 2 (Modules A-B), 3 (Modules C-D), 4 (memo, deck, bullets),
then the automated checks and the project website (docs/index.html).

Usage:  python run_all.py            # download fresh data, then verify
        python run_all.py --offline  # verify using files already in data/raw
"""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from src import download, phase2, phase3, phase4, site, verify  # noqa: E402


def main() -> None:
    cfg = yaml.safe_load(open("config.yaml"))
    if not cfg["project"]["as_of_date"]:
        import datetime as _dt
        cfg["project"]["as_of_date"] = _dt.date.today().isoformat()
    if "--offline" not in sys.argv:
        manifest = download.run(cfg)
        print(f"Downloaded {len(manifest)} items; manifest at data/raw/manifest.json")
    claims, snap = verify.run(cfg)
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(claims.drop(columns="source"))
        print(snap.drop(columns="source"))
    out = phase2.run(cfg, offline="--offline" in sys.argv)
    m = out["metrics"]
    cols = ["period", "h", "n", "rmse_model", "rmse_no_change", "rmse_seasonal", "rmse_retail_1to1",
            "dm_p_vs_no_change", "dm_p_vs_seasonal", "dm_p_vs_retail_1to1"]
    with pd.option_context("display.width", 220, "display.float_format", "{:.3f}".format):
        print(out["diagnostics"])
        print(m[cols])
    out3 = phase3.run(cfg)
    with pd.option_context("display.width", 220, "display.float_format", "{:.3f}".format):
        print(pd.Series(out3["treasury"]["setup"]).to_string())
        print(out3["treasury"]["scenarios"].to_string(index=False))
    out4 = phase4.run(cfg, out3)
    print(out4["changes"])
    for kind, pth in out4["paths"].items():
        print(f"{kind}: {pth}")

    # Automated checks, then the project website (docs/), which shows their results
    junit = Path("outputs/build/test_results.xml")
    junit.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"])
    print(f"site: {site.build(cfg)}")
    if tests.returncode != 0:
        sys.exit("Some automated checks failed (see above). The site shows which; nothing should be published.")


if __name__ == "__main__":
    main()
