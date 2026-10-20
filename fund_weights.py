"""
Fundamental rule weights, read from a small CSV so you can tune them without
touching code.

    fundamental_weights.csv
        # rule,weight
        roce,1
        roe,1
        ...
        peg,0        <- weight 0 = rule is skipped entirely

A rule that passes earns its weight; a rule that fails earns nothing; a rule that
is n/a (no data) or exempt (e.g. ROCE for a bank) is left out of BOTH sides, so
missing data neither helps nor hurts. The score is shown as
passed weight / evaluated weight -- with all weights at 1 that is a plain pass
count such as "5/7".

If the file does not exist, a template with every weight at 1 is written.
"""

import csv
import os

import fundamentals as fund

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fundamental_weights.csv")

DESCRIPTIONS = {
    "roce": "ROCE >= --min-roce",
    "roe": "average ROE >= --min-roe",
    "de": "debt-to-equity <= --max-de",
    "icr": "interest coverage >= --min-icr",
    "sales_growth": "sales growth >= --min-sales-growth",
    "pat_growth": "PAT growth >= --min-pat-growth",
    "pe_vs_industry": "P/E <= industry median x 1.10 (needs --industry-pe)",
    "peg": "PEG < --max-peg",
    "promoter_holding": "promoter holding >= --min-promoter (n/a if the company has no promoter)",
    "promoter_trend": "promoter holding has NOT fallen in each of the last 3 quarters",
    "pledging": "pledged share of promoter holding <= --max-pledge",
    "institutional_trend": "FII+DII holding did not fall over the latest quarter",
}


def template_text() -> str:
    lines = ["# Fundamental rule weights. One rule per line: rule,weight",
             "# weight 0 skips the rule; any positive number counts it (2 = twice as important as 1).",
             "# Thresholds themselves are command-line options (--min-roce, --max-de, ...).",
             "rule,weight"]
    lines += [f"{r},1   # {DESCRIPTIONS.get(r, '')}" for r in fund.ALL_RULES]
    return "\n".join(lines) + "\n"


def load_weights(path: str = None, create: bool = True) -> dict:
    """Returns {rule: weight} for every rule in fundamentals.ALL_RULES (missing rules default to 1)."""
    path = path or DEFAULT_FILE
    if not os.path.exists(path):
        if create:
            with open(path, "w", encoding="utf-8") as f:
                f.write(template_text())
            print(f"  [info] wrote a template weights file: {path}")
        return {r: 1.0 for r in fund.ALL_RULES}
    weights = {r: 1.0 for r in fund.ALL_RULES}
    with open(path, newline="", encoding="utf-8") as f:
        for lineno, row in enumerate(csv.reader(f), 1):
            if not row or not row[0].strip() or row[0].strip().startswith("#"):
                continue
            name = row[0].strip().lower()
            if name == "rule":
                continue
            if name not in fund.ALL_RULES:
                raise ValueError(f"{path} line {lineno}: unknown rule '{name}'. Valid: {', '.join(fund.ALL_RULES)}")
            if len(row) < 2:
                raise ValueError(f"{path} line {lineno}: expected rule,weight")
            raw = row[1].split("#")[0].strip()
            try:
                w = float(raw)
            except ValueError:
                raise ValueError(f"{path} line {lineno}: weight '{raw}' is not a number")
            if w < 0:
                raise ValueError(f"{path} line {lineno}: weight cannot be negative")
            weights[name] = w
    return weights


def skip_set(weights: dict) -> set:
    return {r for r, w in weights.items() if w <= 0}


def _fmt(x: float) -> str:
    return f"{x:g}"


def score(res: dict, weights: dict) -> dict:
    """res = fundamentals.evaluate(...) output. Returns text '5/7', pct, and the raw weights."""
    pw = sum(weights.get(r, 1.0) for r in res.get("passed", []))
    ew = pw + sum(weights.get(r, 1.0) for r in res.get("failed", []))
    if ew <= 0:
        return {"text": "n/a", "pct": None, "passed": 0.0, "evaluated": 0.0}
    return {"text": f"{_fmt(pw)}/{_fmt(ew)}", "pct": round(pw / ew * 100, 1), "passed": pw, "evaluated": ew}


def tier(pct, strong: float = 75.0, weak: float = 50.0) -> str:
    if pct is None:
        return "n/a"
    return "Strong" if pct >= strong else "Mixed" if pct >= weak else "Weak"
