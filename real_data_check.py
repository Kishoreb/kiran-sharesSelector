"""
One-command real-data check: runs `screener.py validate` (with the
"what drives the result" ablation table) for each strategy on a real index
and saves everything into a dated folder.

Needs normal internet on the machine you run it on (Yahoo Finance for prices,
NSE for the index list). It cannot run in a sandbox without that access.

    python real_data_check.py                      # nifty200, 5y, both strategies
    python real_data_check.py --quick              # fewer parameter sweeps: run this first
    python real_data_check.py --index nifty100 --membership-file index_changes.csv
    python real_data_check.py --check-only         # just test that Yahoo / NSE are reachable
    python real_data_check.py --dry-run            # print the commands, run nothing

Each strategy downloads its own copy of the price history, so a full run takes
a while. Output folder (real_check_YYYYMMDD_HHMM/):
    summary_<strategy>.txt            full console output (the file to share/read)
    validation_report_<strategy>.html charts + tables, open in a browser
    validation_sweep_<strategy>.csv   one row per parameter combination
"""

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

CHECKS = [
    ("Yahoo Finance (prices)", "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5d&interval=1d", True),
    ("NSE archives (index list)", "https://archives.nseindia.com/content/indices/ind_nifty50list.csv", False),
]

SWEEPS_FULL = {
    "pullback_trend": ["reward_risk=1.5,2,3", "stop_mode=structure,atr", "min_pullback_days=1,2,3"],
    "breakout": ["reward_risk=1.5,2,3", "stop_mode=structure,atr", "breakout_lookback=10,20,30"],
}
SWEEPS_QUICK = {k: ["reward_risk=1.5,2,3"] for k in SWEEPS_FULL}


def reachable(name, url, required):
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12)
        print(f"  OK       {name}")
        return True
    except urllib.error.HTTPError as e:      # server answered, so the network path works
        print(f"  OK       {name} (HTTP {e.code}, reachable)")
        return True
    except Exception as e:
        print(f"  BLOCKED  {name}: {e}")
        if not required:
            print("           (not fatal: the last cached index list will be used if one exists, or pass --symbols)")
        return not required


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="nifty200")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--strategies", nargs="+", default=["pullback_trend", "breakout"], choices=list(SWEEPS_FULL))
    ap.add_argument("--capital", type=float, default=100000)
    ap.add_argument("--membership-file", default=None, help="index-changes CSV for point-in-time membership")
    ap.add_argument("--quick", action="store_true", help="only sweep reward_risk (much faster)")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("Connectivity:")
    ok = all([reachable(*c) for c in CHECKS])
    if args.check_only:
        sys.exit(0 if ok else 1)
    if not ok and not args.dry_run:
        print("\nCannot reach Yahoo Finance from this machine, so there is no price data to test. "
              "Run this on a machine with normal internet access.")
        sys.exit(1)

    out_dir = args.out_dir or os.path.join(HERE, "real_check_" + datetime.now().strftime("%Y%m%d_%H%M"))
    sweeps = SWEEPS_QUICK if args.quick else SWEEPS_FULL
    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    for strat in args.strategies:
        cmd = [sys.executable, os.path.join(HERE, "screener.py"), "validate",
               "--index", args.index, "--period", args.period, "--strategy", strat,
               "--capital", str(args.capital), "--ablation",
               "--report", os.path.join(out_dir, f"validation_report_{strat}.html"),
               "--sweep-out", os.path.join(out_dir, f"validation_sweep_{strat}.csv")]
        for sw in sweeps[strat]:
            cmd += ["--sweep", sw]
        if args.membership_file:
            cmd += ["--membership-file", args.membership_file]
        print(f"\n=== {strat} ===\n" + " ".join(cmd))
        if args.dry_run:
            continue
        with open(os.path.join(out_dir, f"summary_{strat}.txt"), "w", encoding="utf-8") as fh:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=HERE)
            for line in proc.stdout:
                sys.stdout.write(line)
                fh.write(line)
            proc.wait()
        if proc.returncode != 0:
            print(f"\n{strat} exited with code {proc.returncode}; see summary_{strat}.txt")

    if not args.dry_run:
        print(f"\nDone. Everything is in {out_dir}")
        print("Open the validation_report_*.html files in a browser; summary_*.txt has the same numbers as text.")
        print("Read the verdict lines first: they say, in plain words, whether the result survives each test.")


if __name__ == "__main__":
    main()
