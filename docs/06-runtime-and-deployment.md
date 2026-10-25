# Runtime and deployment

Audience: a developer who needs to set up, run or move this toolkit, and the exact runtime dependencies behind each command.

Evidence: 16 of 16 entry points read · 11 capabilities · 4 open unknowns · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

## How to read this document

This is a set of command-line tools run by hand, not a deployed service. "Deployment" here means what has to exist on the machine that runs the commands, not a server rollout. Command-line options (defaults, flags) are not repeated here; see [05-api-reference.md](05-api-reference.md) for those.

## Actual stack and versions

The repository declares one dependency file, `requirements.txt`, naming eight packages: pandas, numpy, requests, yfinance, torch, transformers, scikit-learn, openpyxl [inventory; S05 F009 boundary: `requirements.txt` "read whole: pandas, numpy, requests, yfinance, torch, transformers, scikit-learn, openpyxl"].

No `pyproject.toml`, `setup.py` or `setup.cfg` exists anywhere in the repository [inventory "Surprising zeros": "Package metadata: 0."]. The toolkit runs as loose scripts from the repository root, not as an installed package.

Python's own version is not declared in the repository. The only version evidence is the developer's local virtual environment:
- `.venv/pyvenv.cfg:3` - `version = 3.14.3` (checked) [inventory]

This is `inferred`, not `observed`: it is the version of one machine's virtual environment, not a stated requirement. Which Python versions the toolkit actually supports is unknown (U22, below).

## Runtime dependencies

### Declared in `requirements.txt`

| Package | Used by (from the slices read) |
|---|---|
| pandas | throughout: CSV/Excel reading and writing, data frames |
| numpy | indicator and statistics maths |
| requests | NSE, screener.in and Google News HTTP calls [S02] |
| yfinance | price history and market cap from Yahoo Finance [S01: `data.py:50`, `data.py:81`] |
| torch | optional: Hugging Face sentence embeddings for the governance classifier's `--embedder` path, and FinBERT sentiment scoring [S08: `gov_classifier.py:150`; inventory I008] |
| transformers | same as torch, for loading the Hugging Face model [S08: `gov_classifier.py:150` - `from transformers import AutoModel, AutoTokenizer`] |
| scikit-learn | the governance classifier (TF-IDF + logistic regression) [S08: `gov_classifier.py:222`], the meta-model (HistGradientBoostingClassifier) [S09: `meta_model.py:122`], and the anomaly detector's optional Isolation Forest layer [S08: `anomaly.py:185`] |
| openpyxl | writing `.xlsx` workbooks (holdings analysis output, CDSL mutual-fund workbook) [S04: `holdings_analysis.py:454` - `with pd.ExcelWriter(out, engine="openpyxl")`; S05] |

scikit-learn is treated as optional in two places even though it is also declared: a missing install skips the Isolation Forest layer in `anomaly.py` and the rules and z-score layers still run [S08: `anomaly.py:187` - `except ImportError:`], and a missing install stops `train-meta` with an install hint rather than crashing [S09: `screener.py:577` - `except ImportError as e:`].

### Needed by specific commands but not in `requirements.txt`

| Package or program | Declared where | Needed by | Evidence |
|---|---|---|---|
| pdfplumber | `install-commands.txt` | `cdsl_holdings_to_xls.py` (E009), to read the PDF's text layer | S05: `cdsl_holdings_to_xls.py:63` - `import pdfplumber` (checked); `cdsl_holdings_to_xls.py:36` - `pip install pdfplumber xlwt` (checked) |
| xlwt | `install-commands.txt` | `cdsl_holdings_to_xls.py` (E009), to write the default `.xls` output; the run stops with an install message if missing | S05: `cdsl_holdings_to_xls.py:940` - `sys.exit("Writing .xls needs xlwt:  pip install xlwt     (or use an output name ending in .xlsx)")` (checked) |
| pytesseract | `install-commands.txt` | `cdsl_holdings_to_xls.py` (E009), to OCR (optical character recognition) scanned PDF pages | S05: `cdsl_holdings_to_xls.py:298` - `import pytesseract` (checked) |
| Tesseract (the OCR engine `pytesseract` wraps) | not shown by the inventory | same as pytesseract | `install-commands.txt`'s recorded keys are the three Python packages above (inventory); whether that file, or any other, also documents installing the Tesseract program itself is unknown (U23, below) |
| xlrd | not declared anywhere found | `holdings_analysis.py` (E008), for pandas to open the converter's default `.xls` file | S04: searched `xlrd` in root `*.py` and `*.txt` files, no match (U10) |

### External services reached at runtime

Not Python packages, but needed for most commands to produce a result: NSE's public archive (index lists and filings), the NSE JSON API, Yahoo Finance (through yfinance), screener.in company pages, and Google News RSS. Two are optional and chosen by command-line option: the Anthropic API, and a local Ollama (a tool for running language models on your own machine) server [inventory I001-I008; S02].

## Configuration model and keys

### Environment variables

All five are read in one file, `qualitative.py` [inventory: "Environment variables read in code (names only), all in `qualitative.py`"]:

| Variable | Purpose | Evidence |
|---|---|---|
| `ANTHROPIC_API_KEY` | Key for the optional Anthropic news-sentiment scorer. `[secret reference: ANTHROPIC_API_KEY]` | S02: `qualitative.py:222` - `key = os.environ.get("ANTHROPIC_API_KEY")` (checked) |
| `ANTHROPIC_MODEL` | Which Anthropic model to call | inventory, `qualitative.py:199-268` |
| `OLLAMA_URL` | Address of a local Ollama server, overriding the built-in default | inventory I007: "default URL, overridable by `OLLAMA_URL`" |
| `OLLAMA_MODEL` | Which model the local Ollama server should use | inventory, `qualitative.py:199-268` |
| `FINBERT_MODEL` | Which local FinBERT model to load for sentiment scoring | inventory I008 |

No `.env` file, `.ini`, `.toml` or `.cfg` configuration file exists in the repository; the search covered `.env*`, `*.ini`, `*.toml`, `*.cfg`, `pytest.ini`, `tox.ini`, `conftest.py`, `pyproject.toml`, `setup.py` at the root [inventory "Configuration files"].

### Files that configure behaviour

| File | Role |
|---|---|
| `requirements.txt` | Python packages (above) |
| `install-commands.txt` | extra install and run commands for the CDSL converter: pdfplumber, xlwt, pytesseract [inventory] |
| `fundamental_weights.csv` | per-rule weights read by `fund_weights.py` for the holdings analysis (C03); if the file is missing, the loader writes a template file instead of failing [S04: `fund_weights.py:64` - `f.write(template_text())` (checked)] |
| `index_changes.example.csv` | example input for index membership changes; purpose from the file name only, not read [inventory] |

Beyond these files, almost all behaviour is chosen per run through command-line options rather than a persistent configuration file; the full option list for each command is in [05-api-reference.md](05-api-reference.md).

### Persisted state and caches

These are not configuration, but they are files the tools read and write between runs, so one run's output can be another run's input:

- `.cache/` - saved by `universe.py`: downloaded NSE index constituent lists, cached for one day, with one dated snapshot kept per day [S01: "downloads NSE index lists, caches for one day, keeps dated snapshots"]. The same directory also holds 7-day caches of company statements and ownership data, and a 1-day cache of news results, written by `fundamentals.py`, `screener_in.py` and `qualitative.py` [S02: `fundamentals.py:43` - `CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60` (checked); `qualitative.py:40` - `CACHE_TTL = 24 * 3600` (checked)].
- `.cache/equity_l.csv` - the NSE equity list downloaded by `holdings_analysis.py`, with a cached copy or a built-in list used if the download fails [S04].
- `dump_xbrl/` - created by `fetch_xbrl_sample.py` (E016) to hold downloaded XBRL filing samples [S11: `fetch_xbrl_sample.py:20` - `os.makedirs("dump_xbrl", exist_ok=True)` (checked)].
- Saved models: `gov_model.pkl` (default name, the governance classifier, written by `gov_classifier.py train`, E010) [S08: `gov_classifier.py:201` - `pickle.dump(...)` (checked)], and `meta_model.pkl` (default name, the trade-quality filter, written by `screener.py train-meta`, E004) [S09: `meta_model.py:255` - `pickle.dump(payload, f)` (checked)]. Both are loaded with Python's `pickle` module on later runs, which executes arbitrary code embedded in the file; both slices record this as a trusted-input assumption about the owner's own trained model, not an access-control mechanism [S08, S09].

The other files each command writes on a normal run (`screening_results.csv`, `backtest_trades.csv`, `backtest_equity.csv`, the `_analysis.xlsx` workbook, the CDSL `.xls`/`.xlsx` outputs, the HTML validation report, the dated `real_check_*` folder) are listed per entry point in [05-api-reference.md](05-api-reference.md).

## Packaging

The project is not packaged for installation or distribution: no `pyproject.toml`, `setup.py` or `setup.cfg` was found [inventory]. All 35 Python files sit in one flat folder at the repository root and import each other directly; there are no sub-packages [inventory "Project type"; see [02-module-architecture.md](02-module-architecture.md) for the full module layout].

No continuous-integration or pipeline file exists: the search for `.github/`, `Jenkinsfile`, `azure-pipelines.yml`, `.gitlab-ci.yml` and `bitbucket-pipelines.yml` at the repository root found none [inventory "Surprising zeros"].

Installing the toolkit is a manual, two-step process, inferred from the dependency files themselves and the per-command install messages, not from a written install guide: install the packages in `requirements.txt`, then separately install the three packages in `install-commands.txt` if the CDSL converter (E009) is needed. A missing package in the second group stops that one command with its own install hint rather than failing at import time for every command, for example `cdsl_holdings_to_xls.py:940` above.

## Start commands

Every entry point is `python <file>.py [sub-command] [options]`, run from the repository root [inventory "Entry points"]. The sub-commands of `screener.py` and `gov_classifier.py` are selected by `argparse` sub-parsers; the rest are standalone scripts.

| ID | Start command | Capability | Evidence |
|---|---|---|---|
| E001 | `python screener.py screen` | C01 | S01: `screener.py:754` |
| E002 | `python screener.py backtest` | C05 | S06: `screener.py:817` |
| E003 | `python screener.py validate` | C06 | S07: `screener.py:824` |
| E004 | `python screener.py train-meta` | C08 | S09: `screener.py:840` |
| E005 | `python screener.py monitor` | C02 | S03: `screener.py:855` |
| E006 | `python screener.py update-price` | C10 | S10: `screener.py:867` |
| E007 | `python screener.py snapshot-changes` | C09 | S10: `screener.py:872` |
| E008 | `python holdings_analysis.py <file>` | C03 | S04: `holdings_analysis.py:386`, `:472` |
| E009 | `python cdsl_holdings_to_xls.py <pdf>` | C04 | S05: `cdsl_holdings_to_xls.py:1107`, `:1172` |
| E010 | `python gov_classifier.py train` | C07 | S08: `gov_classifier.py:281` |
| E011 | `python gov_classifier.py import-sheet <xlsx>` | C07 | S08: `gov_classifier.py:287` |
| E012 | `python gov_classifier.py predict "<text>" --flag <type>` | C07 | S08: `gov_classifier.py:291` |
| E013 | `python real_data_check.py` | C06 | S07: `real_data_check.py:61`, `:115` |
| E014 | `python anomaly.py SYMBOL [SYMBOL ...]` | C07 | S08: `anomaly.py:257` |
| E015 | `python diagnose_dump.py <folder> [SYMBOL ...]` | C11 | S11: `diagnose_dump.py:83-85`, `:105` |
| E016 | `python fetch_xbrl_sample.py [SYMBOL ...]` | C11 | S11: `fetch_xbrl_sample.py:19`, `:58` |

E013 is itself a wrapper: it checks that Yahoo Finance and the NSE archive are reachable, then starts E003 (`screener.py validate`) as a child process of the same Python interpreter, once per strategy, and streams its output to a dated summary file [S07: `real_data_check.py:88` - `cmd = [sys.executable, os.path.join(HERE, "screener.py"), "validate", ...]`; `real_data_check.py:101` - `proc = subprocess.Popen(cmd, ...)`]. It locates `screener.py` relative to its own file location (`HERE`), so both files need to stay in the same folder [S07].

The six `test_*.py` files are also started directly, `python test_toolkit.py` and so on, per the docstring in `test_validation.py:5`; they are not collected through `pytest`'s normal `def test_*` discovery, which returns 0 matches across the repository [inventory "Surprising zeros"; U01].

## Deployment targets and environments (as declared)

There is no deployment target beyond the user's own computer. Existing documentation states: "Must be run on your own computer with normal internet access" [P2, source: existing documentation, README.md]. Code evidence is consistent with this: no web server, scheduler or queue was found at the repository root, only a thread pool inside the CDSL converter and retry pauses elsewhere [inventory "Event consumers and producers"].

No environment-specific configuration (for example separate development, staging or production settings) was found. The only files that resemble configuration are `requirements.txt`, `install-commands.txt`, `fundamental_weights.csv` and `index_changes.example.csv`, described above [inventory].

No containerization file (`Dockerfile`, `docker-compose.yml`) or infrastructure-as-code file was searched for in this survey; this is `not measured`, not confirmed absent.

Existing documentation carries a disclaimer about the tool's purpose, relevant to anyone deciding whether to rely on its output: "This is a rule-checking and simulation tool, not investment advice, and a backtest is not a promise of future performance" [P3, source: existing documentation, README.md].

---

## Unknowns and next probes

| ID | Question | Why it matters | Next probe |
|---|---|---|---|
| U10 | Is `xlrd` actually installed? `holdings_analysis.py` needs it to open the converter's `.xls` output with pandas, and it is named in no requirements file. | Decides whether the two main tools (C03, C04) work together out of the box. | Ask the developer which packages are installed in `.venv`; try `pd.read_excel` on a converter output in a sandbox. |
| U16 | Do `real_data_check.py` and `validate` produce sensible numbers end to end on real Yahoo/NSE data? | No offline test drives the live-data path; decides how far a backtest or validation result can be trusted. | Run `python real_data_check.py --quick` (or `--check-only` first) with normal internet. |
| U22 | No file declares a required Python version, and `requirements.txt` was only read for package names, not version pins. The only version evidence is the developer's local `.venv` (3.14.3). Which Python and package versions does the toolkit actually support? | Someone setting up a new machine has no stated target to install against. | Ask the developer; read `requirements.txt` for version specifiers. |
| U23 | `install-commands.txt`'s recorded contents are three Python packages (pdfplumber, xlwt, pytesseract). Does it, or any other file, also cover installing the Tesseract OCR engine itself, which `pytesseract` only wraps? | Without Tesseract installed separately, OCR of scanned CDSL statements (part of C04) cannot work even with every Python package present. | Read `install-commands.txt` in full; ask the developer. |

## Related documents

- [01-overview.md](01-overview.md): what the project does, its capabilities and the system context diagram showing the same external services and files.
- [02-module-architecture.md](02-module-architecture.md): the flat-folder module layout referenced under "Packaging".
- [05-api-reference.md](05-api-reference.md): every command-line option, input and output per entry point, not repeated in this document.
- [07-error-handling-and-observability.md](07-error-handling-and-observability.md): error and exit-code patterns, including the install-time errors noted here.
- [08-developer-onboarding.md](08-developer-onboarding.md): step-by-step setup using the install sequence described here.
