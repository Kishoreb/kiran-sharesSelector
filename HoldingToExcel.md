# Mutual Fund Shortlister

A small Python toolkit that shortlists mutual funds **by category** —
just tell it "small cap", "midcap", "large cap", "flexi cap", "elss", etc.
It scores funds on:

- 1/3/5-year CAGR, volatility, a Sharpe-style risk-return ratio, a Sortino
  ratio (downside-only risk), rolling 3-year return consistency, simulated
  SIP XIRR and max drawdown;
- **benchmark-relative** performance: excess return over, and rolling
  win-rate against, the category benchmark (`benchmark.py`);
- a **portfolio-quality** score (0–100) built from the AMC's disclosed
  monthly holdings (`portfolio_quality.py`).

Hard cutoffs filter funds out first; a weighted composite score ranks the rest.

The toolkit also includes a separate utility, `cdsl_holdings_to_xls.py`, that
extracts **your own** stock and mutual fund holdings from a CDSL Consolidated
Account Statement (CAS) PDF into Excel (see "Extracting your holdings from a
CDSL CAS PDF" below). It is independent of the shortlisting scripts.

Data sources:
- The universe of mutual fund schemes and each fund's NAV history come from
  AMFI's scheme master via [mfapi.in](https://www.mfapi.in/) (free, no API key).
- Benchmark series: a local TRI CSV you supply, or an index fund tracking the
  benchmark index (also from mfapi.in) as a proxy.
- Holdings: monthly portfolio Excel files published by each AMC (see
  "Portfolio quality" below for what is and isn't automated).
- Your own holdings (CDSL extractor only): the CAS PDF you supply.

## Files

| File                       | Purpose                                                                 |
|----------------------------|--------------------------------------------------------------------------|
| `config.py`                | All thresholds, score weights, benchmark map, portfolio-quality rubric   |
| `fund_universe.py`         | Fetches the AMFI scheme master and filters it by category + plan type    |
| `fetch_nav_data.py`        | Downloads & caches NAV history per scheme code                           |
| `metrics.py`               | CAGR, volatility, risk-return ratio, Sortino, rolling returns, SIP XIRR, max drawdown |
| `benchmark.py`             | Benchmark data (CSV / pinned code / auto-discovered index-fund proxy), excess return, rolling beat-benchmark % |
| `portfolio_quality.py`     | Parses AMC portfolio workbooks and computes the 0–100 portfolio-quality score |
| `holdings_fetch.py`        | Downloads monthly portfolio files for the AMCs that can be automated     |
| `amc_registry.py`          | Per-AMC knowledge: disclosure page, whether it can be automated, notes   |
| `report.py`                | Formats the ranked shortlist as a styled Excel workbook                  |
| `shortlist.py`             | Main script: category → candidates → fetch → metrics → filter → score → rank → CSV + Excel |
| `cdsl_holdings_to_xls.py`  | Standalone: CDSL CAS PDF → stock `.xls` + mutual fund `-MF.XLS` of your own holdings |
| `test_benchmark.py`, `test_portfolio_quality.py` | Offline tests (synthetic data, no network)         |
| `requirements.txt`         | Python dependencies                                                      |

Keep all `.py` files in one folder. Data is created under `./data/`.

## Setup

```bash
pip install -r requirements.txt
```

`xlrd` is only needed for old `.xls` portfolio files (Nippon India and Baroda
BNP Paribas publish those). `pdfplumber` and `xlwt` are needed only by
`cdsl_holdings_to_xls.py`; `pytesseract` plus the Tesseract program are needed
only if your CAS PDF has no text layer (see the CDSL section).

## 1. Run it — just name a category

```bash
python shortlist.py "small cap"
python shortlist.py midcap
python shortlist.py "large cap"
python shortlist.py "flexi cap" --refresh          # force re-download instead of using cache
python shortlist.py "small cap" --fetch-holdings   # also try the AMC portfolio downloaders first
```

Supported categories (case/spacing/hyphens don't matter): `small cap`,
`mid cap`, `large cap`, `multi cap`, `flexi cap`, `large & mid cap`, `elss`,
`focused`, `value`, `contra`, `dividend yield`, `sectoral`. Run
`python shortlist.py` with no arguments to see this list any time.

This will:
1. Fetch (or load cached) AMFI's full scheme list and filter it to every
   **Direct + Growth** plan fund whose name matches the category
2. Download (or load cached) NAV history for each candidate fund
3. Compute the performance, risk and consistency metrics
4. Add benchmark-relative metrics (benchmark per fund category, see below)
5. Add the portfolio-quality score where a matching, fresh portfolio file exists
6. Drop funds that fail the hard filters in `config.py`
7. Score the rest with a weighted, z-scored composite score and rank them
8. Print the top funds and write the full ranked list to `shortlisted_funds.csv`
   and a formatted `shortlisted_funds.xlsx`

You can also pass a CSV with a `scheme_code` column instead of a category,
e.g. `python shortlist.py my_funds.csv` — the script auto-detects `.csv` input.

## 2. Tune it

Everything is controlled from `config.py`:

- **Hard filters** (`MIN_CAGR_1Y/3Y/5Y`, `MAX_VOLATILITY`, `MIN_RISK_RETURN_RATIO`,
  `MIN_HISTORY_YEARS`): a fund failing any is dropped. Set to `None` to disable.
- **Score weights** (`SCORE_WEIGHTS`): how much each metric counts. Each metric
  is z-scored across the surviving funds first. Weights are normalised, so they
  need not sum to exactly 1.
- **Benchmark settings** (`BENCHMARK_*`, `BENCHMARKS`): see below.
- **Portfolio-quality rubric** (`PQ_*`, `HOLDINGS_DIR`, `AMFI_MARKETCAP_CSV`): see below.
- `RISK_FREE_RATE`, `TOP_N`, `MAX_FUNDS_TO_SCAN`, and the plan-type switches
  (`REQUIRE_DIRECT_PLAN`, `REQUIRE_GROWTH_PLAN`, `INCLUDE_INDEX_FUNDS`,
  `INCLUDE_FUND_OF_FUNDS`).

**Missing values:** any metric that can't be computed for a fund (too little
history, no benchmark, no holdings file) is scored as *average* (z = 0) rather
than excluding the fund. Nothing is ever estimated to fill a gap.

Because of that, two columns in the CSV/Excel (and `score_coverage` in the
printed table) show how much of each fund's score rests on real data:

- `score_coverage` — share of the total score weight that was actually measured
  (100% = nothing missing; e.g. 90% = a metric worth 10% of the score was missing).
- `score_missing` — which metrics were missing (e.g. `portfolio_quality`).

They don't change the ranking. Use them to discount ranks built on gaps, e.g. a
fund with no holdings file or no benchmark history.

## How the metrics are computed

- **CAGR (1y/3y/5y)**: latest NAV vs the NAV N years ago (nearest trading day).
  Not enough history → `None`.
- **Volatility**: annualised std-dev of month-over-month NAV returns (`× √12`).
- **Risk-return ratio (Sharpe-style)**: `(3y CAGR − risk-free rate) / volatility`.
- **Sortino ratio**: same, divided by downside deviation instead of volatility.
- **Rolling 3-year returns**: trailing 3-year CAGR at every month-end; summarised
  as average, minimum, std-dev and `rolling_positive_pct` (share of windows > 0).
- **SIP XIRR**: monthly SIP simulated over the trailing `SIP_YEARS`.
- **Max drawdown**: largest peak-to-trough NAV decline over the fund's history.

### Benchmark-relative metrics (`benchmark.py`)

- **`benchmark_excess_return`**: fund CAGR minus benchmark CAGR over the *same*
  dates (`BENCHMARK_EXCESS_YEARS`, default 3).
- **`rolling_beat_benchmark_pct`**: share of rolling windows in which the fund's
  trailing CAGR beat the benchmark's (this is the spec's "rolling consistency").

Each fund is benchmarked by its own AMFI category (`BENCHMARKS` in `config.py`;
sectoral/thematic funds have none). Benchmark data, first match wins:

1. a CSV in `data/benchmarks/` named after the category (`small_cap.csv`,
   `large_and_mid_cap.csv`, …) with columns `date` and `nav` (or `tri`/`close`) —
   drop real NSE Total Return Index history here for best accuracy;
2. a scheme code pinned in `BENCHMARKS[...]["scheme_code"]`;
3. **auto-discovery**: the plain Direct-Growth index fund tracking that index
   with the longest NAV history (momentum/quality/ETF/Regular-plan variants excluded).

Option 3 is only a **proxy**: an index fund's NAV runs slightly below the true
TRI (expense ratio + tracking error), so excess return is overstated by roughly
that gap. The run prints which proxy was used and every output row records it.
A benchmark that is missing, stale (`BENCHMARK_MAX_STALENESS_DAYS`) or too short
leaves the metrics empty.

### Portfolio quality (`portfolio_quality.py`)

A 0–100 score from the equity holdings in the AMC's monthly portfolio
disclosure, from five sub-criteria, each mapped linearly between a "worst" and
a "best" value (`PQ_CRITERIA` in `config.py`):

| Sub-criterion    | Meaning                                              | Better |
|------------------|------------------------------------------------------|--------|
| `top10_pct`      | % of NAV in the ten largest equity holdings          | lower  |
| `n_holdings`     | number of equity holdings                            | higher |
| `top_sector_pct` | % of NAV in the largest industry                     | lower  |
| `largemid_pct`   | % of equity in large+mid caps (liquidity proxy)      | higher |
| `cash_pct`       | cash, TREPS, net receivables as % of NAV             | lower  |

The score is the weighted average of the sub-criteria that could be measured,
and is left **missing** if less than `PQ_MIN_COVERAGE` of the weight is
measurable. It is also left missing for: no matching file, a non-equity scheme
(fewer than `PQ_MIN_EQUITY_HOLDINGS` equity holdings), weights that don't add
up to ~100%, or a statement older than `PQ_MAX_AGE_DAYS`. `pq_note` in the CSV
says why. The thresholds are this toolkit's defaults, **not an industry
standard** — tune them. Concentrated-by-design funds (focused, sectoral) score
lower on concentration by construction; compare within a category.

`largemid_pct` needs `data/amfi_market_cap.csv` (columns `isin,category`,
category = large/mid/small), built from AMFI's half-yearly stock
categorisation. Without it that criterion is skipped.

**Where the holdings files come from.** Drop `.xls/.xlsx` (or `.zip` of them)
anywhere under `data/holdings/`; every sheet that looks like a SEBI-style
portfolio statement is parsed and matched to funds by scheme name. Debug a
folder of real files with:

```bash
python portfolio_quality.py data/holdings
```

Automation per AMC is limited (`amc_registry.py`, `python holdings_fetch.py --list`):

| Mode                 | AMCs | Meaning |
|----------------------|------|---------|
| `auto` (3)           | Nippon India, DSP, Baroda BNP Paribas | `holdings_fetch.py` scrapes the page for the file link. **Not tested against live downloads.** |
| `manual` (12)        | SBI, HDFC, Aditya Birla Sun Life, Axis, Mirae, Tata, Motilal Oswal, LIC, Mahindra Manulife, Samco, Abakkus, JioBlackRock | Official page found, but the file list is script-rendered/filtered; download in a browser and drop the file in `data/holdings/<amc>/` |
| `manual_unconfirmed` (3) | ICICI Prudential, UTI, Invesco | Candidate page only |
| `gated` (2)          | Edelweiss, PPFAS | Behind a folio/PAN/citizenship form with restrictions on reuse — deliberately **not** automated |
| `not_found` (12)     | Kotak, Bandhan, Canara Robeco, Franklin Templeton, HSBC, Quant, Bank of India, WhiteOak, 360 ONE, Groww, Bajaj Finserv, AlphaGrep | No official monthly-portfolio page located |

AMC sites change; if a scraper finds no matching link it says so rather than
guessing. Funds from AMCs not in this registry (e.g. IDBI, ITI, Union,
Sundaram, PGIM India) simply have no portfolio score.

## 3. Extracting your holdings from a CDSL CAS PDF

`cdsl_holdings_to_xls.py` is a standalone script (it does not use the other
modules or `config.py`). It reads a CDSL Consolidated Account Statement PDF and
writes **two Excel files** next to the PDF:

| Output file | Contents |
|---|---|
| `<input-file-name>_holdings.xls` | Every stock / ETF in the demat "HOLDING STATEMENT" tables |
| `<input-file-name>-MF.XLS` | Every mutual fund in the "MUTUAL FUND UNITS HELD AS ON ..." table |

For `Kiran_2026-06.pdf` that gives `Kiran_2026-06_holdings.xls` and
`Kiran_2026-06-MF.XLS`. NPS sections are ignored. It reports what is printed in
the statement; it does not fetch prices or give advice.

```bash
pip install pdfplumber xlwt                       # xlwt only for .xls output
python cdsl_holdings_to_xls.py Kiran_2026-06.pdf
python cdsl_holdings_to_xls.py Kiran_2026-06.pdf -o my_holdings.xls     # -> my_holdings.xls + my_holdings-MF.xls
python cdsl_holdings_to_xls.py Kiran_2026-06.pdf --mf-output funds.xlsx
python cdsl_holdings_to_xls.py Kiran_2026-06.pdf --skip-mf              # stocks only
python cdsl_holdings_to_xls.py cas.pdf --password ABCDE1234F            # CDSL password = PAN in capitals
python cdsl_holdings_to_xls.py cas.pdf --pages 17-29 --force-ocr
```

| Flag | Default | Meaning |
|---|---|---|
| `-o`, `--output` | `<pdf name>_holdings.xls` | Stock file (`.xls` or `.xlsx`) |
| `--mf-output` | `<pdf name>-MF.XLS`, or `<-o name>-MF.<ext>` when `-o` is given | Mutual fund file (`.xls` or `.xlsx`) |
| `--skip-mf` | off | Stocks only |
| `--password` | — | PDF password |
| `--pages` | all | Restrict the scan, e.g. `17-29` |
| `--dpi`, `--workers` | 300, 4 | OCR render resolution and parallelism |
| `--force-ocr` | off | Ignore any text layer and OCR the page images |
| `--tesseract-cmd` | — | Full path to the tesseract executable (Windows) |

**Stock file** — sheet *Holdings*: ISIN, Security, Current Bal, Frozen Bal,
Pledge Bal, Pledge Setup Bal, Free Bal, Market Price / Face Value, Value (Rs),
Demat Account (DP), PDF Page, Check, and a TOTAL row. Sheet *Reconciliation*
compares each demat account's sum with the "Portfolio Value" printed in the
statement.

**Mutual fund file** — sheet *Mutual Funds*, one row per scheme and folio:
Scheme Name (as printed, including the leading scheme code), ISIN, Folio No.,
Closing Bal (Units), NAV (Rs), Cumulative Amount Invested (INR), Valuation (Rs),
Unrealised Profit/Loss, Unrealised Profit/Loss (%), PDF Page, Check, and a TOTAL
row. Sheet *Reconciliation* compares the sum of invested and valuation with the
statement's "Grand Total" row.

**Accuracy safeguards**

- Every ISIN is validated with its check digit. Look-alike characters
  (O/0, I/1/L, S/5, B/8 …) are corrected only if the check digit then passes;
  if several corrections fit equally well the ISIN is kept as read and flagged.
- Stock rows: Current Bal × Price = Value. Mutual fund rows: Units × NAV =
  Valuation, Valuation − Invested = Profit/Loss, Profit/Loss ÷ Invested =
  Profit/Loss %.
- Rows that fail a check, or whose ISIN was corrected, are marked in the
  *Check* column and shaded yellow; the console lists them too.

Tested on one statement with a text layer (`Kiran_2026-06.pdf`): 48 stock rows
and 75 mutual fund rows, with all totals matching the statement.

**Limitations**

- Scanned PDFs (no text layer) are read with OCR (needs `pytesseract` and the
  Tesseract program). Numbers read well, but ISINs and folio numbers are
  noticeably less reliable — check every flagged row.
- A scanner's text layer can contain misread characters that are copied through
  (e.g. a scheme code `162` came out as `16Z`). Scheme names are not
  spell-checked.
- A printed ISIN can itself fail the check digit; it is then kept as printed and
  flagged.
- Mutual funds held *in demat form* appear in the stock file; the MF file covers
  only the folio-based table.
- Column positions are measured from the current CDSL CAS layout; if CDSL changes
  it, the layout constants near the top of the script need adjusting.

## Tests

```bash
python test_benchmark.py
python test_portfolio_quality.py
```

Both run offline on synthetic data (the portfolio test builds SEBI-style
workbooks, including fraction-style weights, a zip, stale and malformed files).
They check the logic; they have **not** been run against real AMC files or the
live mfapi.in API. `cdsl_holdings_to_xls.py` has no automated tests; it was
checked by running it on one real statement and reconciling against the
printed totals.

## Mapping to `mutual_fund_scoring_specification.md`

| Spec parameter | Status |
|---|---|
| 1. 3-year return | ✅ `cagr_3y` |
| 2. 5-year return | ✅ `cagr_5y` |
| 3. Rolling consistency vs benchmark | ✅ `rolling_beat_benchmark_pct` (benchmark = index-fund proxy unless you supply a TRI CSV) |
| 4. Benchmark excess return | ✅ `benchmark_excess_return` (same caveat) |
| 5. Risk-adjusted return | ✅ Sharpe-style ratio + Sortino (computed from 3y CAGR and monthly volatility, not a full excess-return series) |
| 6. Maximum drawdown | ✅ `max_drawdown` |
| 7. Expense ratio | ⛔ not implemented (excluded on request) |
| 8. Portfolio quality | ✅ needs holdings files (see above); missing for funds without one |

Not implemented from the spec: percentile scoring (this toolkit z-scores),
renormalising weights over available metrics with a minimum-coverage flag
(missing metrics are scored as average instead), an external JSON weights file
(weights live in `config.py`), and the `ranked_funds.md` / run-log outputs.

## Notes & caveats

- This is a screening tool, not investment advice — check exit loads, expense
  ratios, fund manager tenure, portfolio overlap and your own risk profile
  before investing.
- Past returns (which is mostly what this measures) don't guarantee future
  performance.
- mfapi.in is free/community-run; if it's unavailable, cached data under
  `data/` still lets you re-run `shortlist.py` without `--refresh`.
