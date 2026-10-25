# Developer onboarding

Audience: a developer setting this toolkit up for the first time, who needs to know what to install, how to run a command, how to run the tests, and where the known rough edges are.

Evidence: 16 of 16 entry points read · 11 capabilities · 12 open unknowns relevant to this document · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

## How to read this document

This is a set of command-line tools run by hand from one folder, not a service with an install wizard. There is no setup script, so the steps below are pieced together from the dependency files and the commands' own code, not from a written install guide. Command options are not repeated here; see [05-api-reference.md](05-api-reference.md) for those.

## Repository layout

The repository is one flat folder: 35 Python files, about 9,550 lines, with no sub-folders for code, no `__init__.py` and no package structure [inventory "Project type"]. There is nothing to change into beyond the repository root itself.

| Group | Count | Files | Evidence |
|---|---|---|---|
| CLI entry-point files | 8 files, 16 commands (7 sub-commands of `screener.py`, 3 of `gov_classifier.py`, 6 standalone scripts) | `screener.py`, `holdings_analysis.py`, `cdsl_holdings_to_xls.py`, `gov_classifier.py`, `anomaly.py`, `real_data_check.py`, `diagnose_dump.py`, `fetch_xbrl_sample.py` | [inventory "Entry points"] |
| Supporting modules (no command line of their own) | 21 | screening and ranking (`candidate_engine.py`, `strategies.py`, `risk.py`, `filters.py`, `market.py`); data sources (`data.py`, `universe.py`, `fundamentals.py`, `fund_weights.py`, `screener_in.py`, `ownership.py`, `nse_client.py`, `qualitative.py`); backtesting and validation (`backtester.py`, `costs.py`, `exits.py`, `validation.py`, `report.py`); `meta_model.py`; `monitor.py`; `membership.py` | [02-module-architecture.md](02-module-architecture.md) |
| Test files | 6 | `test_toolkit.py`, `test_membership.py`, `test_ml.py`, `test_screen_enrich.py`, `test_sources.py`, `test_validation.py`, run as plain scripts (below) | [inventory "Tests"] |
| Configuration and data files | 4 | `requirements.txt`, `install-commands.txt`, `fundamental_weights.csv`, `index_changes.example.csv` | [inventory "Configuration files"] |
| Other root files, not counted as code | 8 | 3 documentation pairs (`README`, `HoldingToExcel`, `stock_shortlisting_parameters_for_indian_markets`, each as `.md` and `.docx`), one Word lock file (`~$README.docx`), and one results file (`screening_results.csv`) left over from a past run | [inventory] |

`.venv/`, `.git/` and `.pytest_cache/` sit alongside the project but were excluded from the survey as not project code [inventory "Project type"]. The presence of `.pytest_cache/` shows pytest has been run in this repository at least once, even though the test files are not pytest-style (below) [inventory "Tests"].

## Prerequisites

| Prerequisite | What is needed | Evidence |
|---|---|---|
| Python | No version is declared anywhere in the repository. The only evidence found is the developer's own virtual environment, 3.14.3, which is `inferred`, not a stated requirement | `.venv/pyvenv.cfg:3` - `version = 3.14.3` (checked) [06-runtime-and-deployment.md](06-runtime-and-deployment.md); U22 below |
| Python packages | Eight packages in `requirements.txt` (pandas, numpy, requests, yfinance, torch, transformers, scikit-learn, openpyxl); three more in `install-commands.txt`, needed only for the CDSL converter, C04 (pdfplumber, xlwt, pytesseract) | [inventory "Configuration files"; 06-runtime-and-deployment.md] |
| An undeclared package | `xlrd`, which `holdings_analysis.py` needs so that pandas can open the converter's default `.xls` output, is named in no requirements file in the repository | [S04; U10 below] |
| A program outside Python | Tesseract, the OCR (optical character recognition: turning an image of text into text) engine that `pytesseract` only wraps. Whether its own install is documented anywhere in the repository is unknown | [06-runtime-and-deployment.md "Needed by specific commands"; U23 below] |
| Network access | Most commands reach NSE's archives, Yahoo Finance or screener.in during a normal run. Existing documentation states the toolkit "must be run on your own computer with normal internet access" | [P2, source: existing documentation, README.md; inventory "External integrations"] |
| Working directory | Every module imports its neighbours by bare name (`import data`, `from strategies import ...`), which only resolves when the current directory is the repository root | [02-module-architecture.md "Flat folder, no package structure"] |

Two integrations are optional and chosen by command-line option rather than needed by every run: the Anthropic API (needs the environment variable `ANTHROPIC_API_KEY`, `[secret reference: ANTHROPIC_API_KEY]`) and a local Ollama server [inventory I006-I007; 06-runtime-and-deployment.md "Environment variables"].

## How to run locally and run tests

### Running a command

There is no setup script in the repository. The install sequence is inferred from the dependency files themselves: install the packages named in `requirements.txt`, then separately install the three packages named in `install-commands.txt` if the CDSL converter (C04) will be used [06-runtime-and-deployment.md "Packaging"].

Every entry point is run as `python <file>.py [sub-command] [options]` from the repository root [inventory "Entry points"; 06-runtime-and-deployment.md "Start commands"]. Three starting points cover the toolkit's three High-importance capabilities:

- `python screener.py screen`: screen and rank candidate trades today (C01) [S01/F001]
- `python screener.py monitor`: check whether an open position is still valid (C02) [S03/F005]
- `python holdings_analysis.py <file>`: run the rules over an existing holdings file (C03) [S04/F008]

The full list of all 16 entry points, their options and their outputs is in [05-api-reference.md](05-api-reference.md) and [06-runtime-and-deployment.md](06-runtime-and-deployment.md).

### Running the tests

The six test files are plain Python scripts with top-level `assert` lines, not `def test_*` functions that pytest discovers on its own: a search for `^def test_`, `class Test` and `unittest` across all `*.py` files in the repository returned no matches [inventory "Surprising zeros"]. Each is run directly, for example `python test_toolkit.py`, following the convention stated in `test_validation.py`'s own docstring [inventory "Tests"; `test_validation.py:5`]. Whether pytest collects and passes them instead is open (U01, below).

Four of the six run against synthetic data with network calls monkeypatched (replacing a function during the test run so no real call is made), so they need no internet connection: `test_validation.py` replaces `screener.fetch_history` [S07: `test_validation.py:37`], and `test_ml.py` replaces `screener_in.get_raw` [S08: `test_ml.py:227`]. The slices that read these four whole recorded a test result of well tested for the capabilities they cover: the backtester and the index-membership checks (`test_toolkit.py`, `test_membership.py`) [S06 Conclusion], the governance classifier and the anomaly detector on their TF-IDF and threshold paths (`test_ml.py`) [S08 Conclusion], and the `validate` command end to end (`test_validation.py`) [S07 Conclusion].

The other two, `test_screen_enrich.py` and `test_sources.py`, call command options and a function that the current code does not have; whether they pass is open (U04, U05, below) [S01, S02].

No test file drives `cdsl_holdings_to_xls.py` or `real_data_check.py`; both are not tested, each with its own search boundary stated in its slice [S05 Conclusion; S07 Conclusion].

## Where to make common changes

These extension points are carried over from [02-module-architecture.md](02-module-architecture.md), where they were traced to specific lines:

| Change | Where | What to do | Evidence |
|---|---|---|---|
| Add a trading strategy | `strategies.py` | Write a class with `signal(df, i)` and `trend_intact(df, i)`, and add it to the `STRATEGIES` dict at `strategies.py:278` | [S01/F001] |
| Add a fundamental rule | `fundamentals.py` | Add the rule name to `ALL_RULES` at `fundamentals.py:82`, add the threshold field to `FundamentalFilters`, and add the evaluation logic in `evaluate` | [S02/F001] |
| Add an anomaly threshold rule | `anomaly.py` | Add the check in `rule_flags` at `anomaly.py:116`, and update `_level` if the rule-count thresholds should change | [S08/F014] |
| Add a data source for enrichment | a new file at the repository root | Follow the never-raise pattern (return a dict with a notes field on error instead of raising), wire it into `screener.py`'s enrichment section near `screener.py:229`, and add a matching `--<name>` argument | [S02/F001] |
| Add a pre-trade filter | `filters.py` | Add a check in the filter chain and a matching skip reason in the backtester's skip dict | [S01/F001, S06/F002] |

Each data-fetching module keeps its own file-based cache under `.cache/`, with its own time-to-live: 7 days for screener.in statements and NSE filings, 1 day for index lists and news [02-module-architecture.md "File-based caching"]. There is no shared caching layer, so a change to the cache format or location has to be made separately in each module that uses it [02-module-architecture.md "Homegrown mechanisms"].

## Troubleshooting known from code

No interview has been recorded for this project yet, so every row below comes from reading the code, not from a person. These are specific problems the slices found, not a general FAQ.

| Symptom | Likely cause | Evidence |
|---|---|---|
| `holdings_analysis.py` fails to read the CDSL converter's `.xls` output | `xlrd` is needed by pandas to open old-format Excel files, and is declared in no requirements file in this repository | [06-runtime-and-deployment.md; S04; U10] |
| OCR of a scanned CDSL statement does not work even with `pytesseract` installed | `pytesseract` only wraps the Tesseract program; whether its own install step is documented anywhere in the repository is unknown | [06-runtime-and-deployment.md; U23] |
| Converting a statement with the wrong `--password` ends in a raw Python traceback, not one of the converter's own messages | `cdsl_holdings_to_xls.py:579` opens the PDF with no `try`/`except` around the call, the one failure path in this file with no handler | [S05; 07-error-handling-and-observability.md](07-error-handling-and-observability.md); U24 |
| `screen --fundamentals flag` (or `filter`) raises an error | `screener.py:216` passes `min_inst_change` to `FundamentalFilters`, which defines `min_fii_change` and `min_dii_change` instead; a related function, `industry_pe_map`, is called in two places but defined nowhere in the repository | [S01, S02; U02, U03] |
| `python test_screen_enrich.py` or `python test_sources.py` fails when run | Both call command options or a function (`--weights-file`, `fund_passed_w`, `parse_peers_fragment`) that the current `screener.py`, `candidate_engine.py` and `screener_in.py` do not have; whether some files are older than others is unresolved | [S01, S02; 02-module-architecture.md "Monkeypatching in tests"; U04, U05, U06] |
| `monitor` prints "Error: ..." and gives no verdict on a real position, but still exits 0 as if it had run cleanly | `monitor.py:65` compares the position's entry date against the price index; whether this still works once that index carries a time zone, as Yahoo's real data may, is untested | [S03; 07-error-handling-and-observability.md; U09] |
| A command returns numbers that look stale | Each data-fetching module checks its own files in `.cache/` by modification time before re-fetching (7 days for company and filing data, 1 day for index lists and news); there is no cache-clearing command, so deleting `.cache/` forces a re-fetch | [02-module-architecture.md "File-based caching"] |
| `train-meta` stops with an install hint when scikit-learn is missing, but a `screen` or holdings-analysis run with scikit-learn missing continues anyway, only without the anomaly detector's Isolation Forest layer | These are two different, intentional responses to the same missing package, not a bug in one of them | [07-error-handling-and-observability.md "Fallbacks"] |
| The one way to see the toolkit run against real, live data, `real_data_check.py`, has no automated test of its own | It needs live internet and starts `screener.py validate` as a subprocess; no offline test drives it | [S07; 06-runtime-and-deployment.md; U16] |

---

## Unknowns and next probes

| ID | Question | Why it matters | Next probe |
|---|---|---|---|
| U01 | The six test files have no `def test_*` functions. Does pytest collect and report them, and do they pass? | Decides how a developer should actually run the test suite. | Run `pytest` and `python test_toolkit.py` (and the other five) in a sandbox and compare. |
| U02 | Does `screen --fundamentals flag` (or `filter`) stop with an error, since `screener.py:216` passes a field `FundamentalFilters` does not define? | A new developer trying the main command's fundamentals option would hit this immediately. | Run it in a sandbox and read the error, or ask the developer which file is current. |
| U03 | Where is `industry_pe_map`, called at two places but defined nowhere in the repository? | Decides whether P/E-vs-industry works at all, in `screen` or the holdings analysis. | Ask the developer; check whether another branch has it. |
| U04 | Does `test_screen_enrich.py` pass, given it expects options and a field the current code does not have? | A developer running the full test suite would hit a failure here. | Run it in a sandbox, or ask the developer. |
| U05 | Does `test_sources.py` pass, given it calls `parse_peers_fragment`, which `screener_in.py` does not define? | Same as U04, for the data-source tests. | Run it in a sandbox, or ask the developer. |
| U06 | Are some files older than others, explaining U02 to U05? | One answer may settle several test failures and the fundamentals option together. | `git log --oneline -- <file>` for each file named in U02 to U05. |
| U09 | Does `monitor.py:65`'s date comparison work on real Yahoo data, whose price index may carry a time zone? | If it raises, `monitor`'s own catch-all hides the failure behind a clean-looking exit code 0. | Run `monitor` on a real symbol and read the output, or print `df.index.tz`. |
| U10 | Is `xlrd` actually installed? It is needed to open the CDSL converter's `.xls` output and is named in no requirements file. | Decides whether the converter and the holdings analysis work together out of the box. | Ask the developer which packages are installed in `.venv`. |
| U16 | Do `real_data_check.py` and `validate` produce sensible numbers on real Yahoo/NSE data, end to end? | It is the one check in the toolkit meant to catch a broken real-data path. | Run `python real_data_check.py --quick` (or `--check-only` first) with normal internet. |
| U22 | Which Python and package versions does the toolkit actually support? No file declares one. | A developer setting up a new machine has no stated target to install against. | Ask the developer; read `requirements.txt` for version specifiers. |
| U23 | Does any file document installing the Tesseract OCR engine itself, separately from the `pytesseract` Python package? | Without it, OCR of scanned CDSL statements cannot work even with every Python package installed. | Read `install-commands.txt` in full; ask the developer. |
| U24 | What does `pdfplumber` raise on a wrong PDF password, and what does the user see? | The converter handles every other failure with its own message; this is the one path found with none. | Run the converter with a deliberately wrong `--password` in a sandbox. |

## Related documents

- [01-overview.md](01-overview.md): what the project does, the capabilities table, and the architecture diagrams.
- [02-module-architecture.md](02-module-architecture.md): the full module layout, dependency diagram and extension points this document draws from.
- [05-api-reference.md](05-api-reference.md): every command, its options, inputs and outputs.
- [06-runtime-and-deployment.md](06-runtime-and-deployment.md): the full dependency, configuration and start-command tables this document summarises.
- [07-error-handling-and-observability.md](07-error-handling-and-observability.md): the error and exit-code patterns behind the troubleshooting table above.
- [09-test-exposure-map.md](09-test-exposure-map.md): per-capability test coverage.
