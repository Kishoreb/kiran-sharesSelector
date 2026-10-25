# Inventory

Commit b472b9b · Surveyor 2.2.0 · 2026-10-24 · Scope: whole repository (top-level folder of kiran-sharesSelector; `.venv/`, `.git/`, `.pytest_cache/` and `__pycache__/` are excluded because they are not project code)

Counts come from file and text search. No source file was read beyond the lines needed to confirm a match. Write `not measured` for anything not looked for, never 0. Write `incomplete` for a category that could not be listed reliably.

## Project type

| Part | Type | Stack and version | Evidence |
|---|---|---|---|
| repository root (35 Python files, 9,550 lines in `*.py`, all in one flat folder) | CLI and batch scripts (command-line tools run by hand), plus a library of shared modules they import | Python 3.14.3 (the version of the local virtual environment, not a declared requirement). Packages: pandas, numpy, requests, yfinance; optional torch, transformers, scikit-learn, openpyxl | `requirements.txt:4` - `yfinance` (checked); `.venv/pyvenv.cfg:3` - `version = 3.14.3` (checked) |

No web server, scheduler or queue was found (see Event consumers and producers). Python version is `inferred` from the virtual environment only: no `pyproject.toml`, `setup.py` or similar declares it.

## Counts

| Category | Count | Complete? | Search boundary (patterns and folders) |
|---|---|---|---|
| Entry points | 16 (7 + 3 sub-commands plus 6 stand-alone scripts, see list) | yes, for the patterns used | `if __name__ == "__main__"`, `ArgumentParser(`, `add_parser(`, `add_subparsers`, `@app.route`, `@app.get`, `@router.`, `FastAPI`, `Flask(`, `click`, `typer`, `sys.argv` in `*.py` at the repository root. Web, Celery and Django patterns returned 0. |
| Configuration files | 4 | yes | Root listing for `.env*`, `*.ini`, `*.toml`, `*.cfg`, `pytest.ini`, `tox.ini`, `conftest.py`, `pyproject.toml`, `setup.py`, `.github/`, `Jenkinsfile` and similar CI files: none found. Counted instead: `requirements.txt`, `install-commands.txt`, `fundamental_weights.csv`, `index_changes.example.csv`. |
| External integrations | 9 | yes, for the patterns used | `import requests/urllib/yfinance/sqlite3/smtplib/subprocess/...` and `https?://` strings in `*.py` that are not tests, at the repository root |
| Event consumers and producers | 0 found | yes, for the patterns used | `threading`, `multiprocessing`, `asyncio`, `queue`, `ThreadPoolExecutor`, `schedule`, `apscheduler`, `while True`, `time.sleep` in `*.py` at the root. Only a thread pool inside `cdsl_holdings_to_xls.py` and retry pauses (`time.sleep`) were found. No queues, listeners or schedulers. |
| Test files | 6 | yes | `test_*.py` at the repository root |
| Tests | incomplete | incomplete: the tests are plain scripts with top-level `assert` lines, not test functions | `def test_*`, `class Test*`, `unittest` returned 0 in all `*.py`. 268 top-level `assert` statements exist across the 6 files (a count of checks, not of tests). |
| Disabled tests | 0 found | yes, for pytest and unittest markers only | `pytest.mark.skip/skipif/xfail`, `unittest.skip`, `pytest.skip`, `importorskip`, `xfail` in all root `*.py`. Commented-out checks were not searched: not measured. |

Also at the root (not counted as code): 3 documentation pairs (`README`, `HoldingToExcel`, `stock_shortlisting_parameters_for_indian_markets`, each as `.md` and `.docx`), 1 Word lock file (`~$README.docx`), 1 results file (`screening_results.csv`). Not read, per the rules.

## Entry points

All are run by hand from a command line. The commands below come from the argument parser definitions, not from documentation.

| ID | Kind | Name or path | Location |
|---|---|---|---|
| E001 | CLI sub-command | `screener.py screen` | `screener.py:754` |
| E002 | CLI sub-command | `screener.py backtest` | `screener.py:817` |
| E003 | CLI sub-command | `screener.py validate` | `screener.py:824` |
| E004 | CLI sub-command | `screener.py train-meta` | `screener.py:840` |
| E005 | CLI sub-command | `screener.py monitor` | `screener.py:855` |
| E006 | CLI sub-command | `screener.py update-price` | `screener.py:867` |
| E007 | CLI sub-command | `screener.py snapshot-changes` | `screener.py:872` |
| E008 | CLI script | `holdings_analysis.py` | `holdings_analysis.py:386` (parser), `:472` (main guard) |
| E009 | CLI script | `cdsl_holdings_to_xls.py` | `cdsl_holdings_to_xls.py:1107` (parser), `:1172` (main guard) |
| E010 | CLI sub-command | `gov_classifier.py train` | `gov_classifier.py:281` |
| E011 | CLI sub-command | `gov_classifier.py import-sheet` | `gov_classifier.py:287` |
| E012 | CLI sub-command | `gov_classifier.py predict` | `gov_classifier.py:291` |
| E013 | CLI script (live-data check) | `real_data_check.py` | `real_data_check.py:61` (parser), `:115` (main guard) |
| E014 | script | `anomaly.py` | `anomaly.py:257` (main guard) |
| E015 | script | `diagnose_dump.py` | `diagnose_dump.py:105` (main guard) |
| E016 | script | `fetch_xbrl_sample.py` | `fetch_xbrl_sample.py:58` (main guard) |

Locations are search results, not yet quote-checked. The six `test_*.py` scripts also run when started with `python <file>`; they are counted under Tests, not here.

## Configuration

| File | Purpose | Keys of note (names only) |
|---|---|---|
| `requirements.txt` | Python packages | pandas, numpy, requests, yfinance, torch, transformers, scikit-learn, openpyxl |
| `install-commands.txt` | Extra install and run commands for the CDSL converter | pdfplumber, xlwt, pytesseract |
| `fundamental_weights.csv` | Weights for fundamental rules (purpose from file name only) | not read |
| `index_changes.example.csv` | Example input for index membership changes (purpose from file name only) | not read |

Environment variables read in code (names only), all in `qualitative.py`: `OLLAMA_MODEL`, `OLLAMA_URL`, `ANTHROPIC_MODEL`, `ANTHROPIC_API_KEY` (value is a secret, never copied), `FINBERT_MODEL`. Found at `qualitative.py:199-268`.

## External integrations

| ID | System | Kind (database, queue, service, file) | Where it is configured |
|---|---|---|---|
| I001 | NSE archives (index lists, equity list, filings) | service, HTTP download | `universe.py:25-29`, `holdings_analysis.py:47`, `nse_client.py:200`, `fetch_xbrl_sample.py:36` (URLs in code) |
| I002 | NSE website API | service | `nse_client.py:24` (URL in code) |
| I003 | Yahoo Finance through the `yfinance` package, and a direct chart URL | service | `data.py:10`, `fundamentals.py:38`, `real_data_check.py:34` |
| I004 | screener.in company pages | service, HTTP | `screener_in.py:249` (URL in code) |
| I005 | Google News RSS search | service, HTTP | `qualitative.py:43` (URL in code) |
| I006 | Anthropic API | service, needs an API key | `qualitative.py:203`, key from `ANTHROPIC_API_KEY` at `qualitative.py:222` |
| I007 | Ollama (local language model server) | service on this computer | `qualitative.py:200` (default URL, overridable by `OLLAMA_URL`) |
| I008 | FinBERT model (local sentiment model, loaded with torch) | local model files | `qualitative.py:268-280` (`FINBERT_MODEL`) |
| I009 | Local files: CSV, JSON, pickle, Excel (`.xls`, `.xlsx`), CDSL PDF statements | file | Many modules, for example `screener.py:806-874`, `gov_classifier.py:36-37`, `cdsl_holdings_to_xls.py:1110-1159` |

No database or e-mail integration was found. Searched `import sqlite3|psycopg2|sqlalchemy|smtplib|boto3` in root `*.py`: 0 matches. Message queue clients (such as `pika` or `kafka`) were not searched: not measured.

## Tests

| Test file | Tests | Disabled | Appears to target |
|---|---|---|---|
| `test_toolkit.py` | script, 35 `assert` lines | 0 markers | backtester, candidate engine, costs, filters, risk, strategies (from imports) |
| `test_membership.py` | script, 25 `assert` lines | 0 markers | index membership and backtester (from its checks) |
| `test_ml.py` | script, 44 `assert` lines | 0 markers | meta model (from file name) |
| `test_screen_enrich.py` | script, 15 `assert` lines | 0 markers | screener rule enrichment (from file name) |
| `test_sources.py` | script, 138 `assert` lines | 0 markers | data sources (from file name) |
| `test_validation.py` | script, 11 `assert` lines | 0 markers | validation tools (docstring: offline tests of `validate`, with `screener.fetch_history` replaced) |

Each file is started with `python <file>`, according to the docstring in `test_validation.py:5`. A `.pytest_cache` folder exists, so pytest has been run here at least once; how it collects these scripts is unknown.

## Needs a human look

| Marker | Times used | Declared in this repository? | Example location |
|---|---|---|---|
| Tests written as top-level scripts with `assert` and `print("... ok")` | 6 files | yes (the files themselves) | `test_validation.py:46` |
| Letter-labelled test sections ("G ok", "H ok", "M ok", "N ok") | at least 4 in `test_toolkit.py` | yes | `test_toolkit.py:119` |
| Monkeypatching (replacing a function during a test) of `screener.fetch_history` | 1 seen | yes | `test_validation.py:37` |

## Surprising zeros

- **Test functions: 0.** A Python repository normally has `def test_*`. Tried: `^def test_`, `^\s*(async )?def test`, `class Test`, `unittest`. All 0. Cause found: the tests are scripts with top-level `assert` lines. Category marked `incomplete`.
- **CI/CD files: 0.** Tried: `.github/**`, `Jenkinsfile`, `azure-pipelines.yml`, `.gitlab-ci.yml`, `bitbucket-pipelines.yml` at the root. Not searched in subfolders, but the repository has no subfolders besides excluded ones.
- **Package metadata: 0.** No `pyproject.toml`, `setup.py` or `setup.cfg`. The project is run as loose scripts, not installed as a package.
