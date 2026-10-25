# Obligations

Every question the 12 documents must answer for this repository. Commit b472b9b · Surveyor 2.2.0 · 2026-10-24

Statuses: `open`, `answered`, `partial`, `unknown`, `not-applicable`, `accepted gap`. See rules section 12. `open`, `partial` and `unknown` never count as done.

## Summary

| Status | Count |
|---|---|
| answered | 93 |
| partial | 0 |
| unknown | 0 |
| not-applicable | 0 |
| accepted gap | 5 |
| open | 0 |

## Document sections

Project type is CLI and batch scripts, so the adaptations in rules section 8 for "Batch" apply to documents 3 and 5. Sections that may not apply (for example health checks, deployment) stay `open` until the reading shows whether they apply.

| ID | Document | Required section | Status | Evidence or reason | Accepted by (role, date) |
|---|---|---|---|---|---|
| O-01-01 | 01-overview | What the project does and for whom | answered | 01-overview "What the project does and for whom" section; cites S01/F001, S03/F005, S04/F008, S06/F002, S07/F003, inventory, doc-diff P1 | |
| O-01-02 | 01-overview | Capabilities table | answered | 01-overview "Capabilities" table; 11 capabilities with importance, entry points, test results and slices; source: capabilities.md, S01-S11 | |
| O-01-03 | 01-overview | System context diagram | answered | 01-overview "System context diagram" Mermaid diagram; all 9 integrations from inventory I001-I009 | |
| O-01-04 | 01-overview | High-level architecture diagram | answered | 01-overview "High-level architecture diagram" Mermaid diagram; all 35 Python files grouped by role; imports from S01-S11 | |
| O-01-05 | 01-overview | End-to-end flow diagram of the most important capability | answered | 01-overview "End-to-end flow: screen and rank candidate trades (C01)" sequence diagram and 7-step narrative; cites S01/F001, S02/F001 | |
| O-01-06 | 01-overview | Unknowns and next probes; Related documents | answered | 01-overview "Unknowns and next probes" (8 open questions) and "Related documents" (5 links) | |
| O-02-01 | 02-module-architecture | Module layout with responsibilities | answered | 02-module-architecture "Module layout with responsibilities" section; all 35 Python files grouped by role with lines, responsibility and imports; sources: inventory, S01-S11 | |
| O-02-02 | 02-module-architecture | Dependency diagram | answered | 02-module-architecture "Dependency diagram" Mermaid diagram; all import relationships from S01-S11 | |
| O-02-03 | 02-module-architecture | Patterns observed (cited) | answered | 02-module-architecture "Patterns observed" section; 6 patterns cited: flat folder, strategy pattern, never-raise, file-based cache, monkeypatching, pickle models | |
| O-02-04 | 02-module-architecture | Extension points | answered | 02-module-architecture "Extension points" table; 5 extension points with file, action and evidence | |
| O-02-05 | 02-module-architecture | Homegrown mechanisms found in the inventory | answered | 02-module-architecture "Homegrown mechanisms" table; 7 mechanisms cited from inventory and slices | |
| O-02-06 | 02-module-architecture | Unknowns and next probes; Related documents | answered | 02-module-architecture "Unknowns and next probes" (5 open questions) and "Related documents" (4 links) | |
| O-03-01 | 03-request-to-response-flow | One section per capability (job flow from trigger to output) | answered | 03-request-to-response-flow: all 11 capabilities covered with main flow, alternative flows, exception flows, business rules and test result per capability; sources S01-S11, doc-diff | |
| O-03-02 | 03-request-to-response-flow | Flow diagram for each High-importance capability | answered | 03-request-to-response-flow: Mermaid sequence diagrams for C01 (screen), C02 (monitor) and C05 (backtest); all nodes map to evidence in S01, S03, S06 | |
| O-03-03 | 03-request-to-response-flow | Unknowns and next probes; Related documents | answered | 03-request-to-response-flow "Unknowns and next probes" (10 open questions) and "Related documents" (5 links) | |
| O-04-01 | 04-screen-and-rank | Interfaces of the core mechanism | answered | 04-screen-and-rank "Interfaces" section; module interface table and enrichment module table; cites S01/F001, S02/F001, S08/F014, S09/F004 | |
| O-04-02 | 04-screen-and-rank | Implementations | answered | 04-screen-and-rank "Implementations" section; two strategies, sizing, ranking, enrichment pipeline, caching; cites S01/F001, S02/F001, S08/F014, S09/F004 | |
| O-04-03 | 04-screen-and-rank | Rules | answered | 04-screen-and-rank "Rules" section; technical, risk/sizing, 13 fundamental, anomaly, news rules with defaults; cites S01/F001, S02/F001, S08/F014, S08/F010 | |
| O-04-04 | 04-screen-and-rank | Risks | answered | 04-screen-and-rank "Risks" section; 5 risks (heat not enforced, fundamentals crash, missing function, test drift, README contradiction); cites S01/F001, S02/F001, doc-diff D2 | |
| O-04-05 | 04-screen-and-rank | Failure and recovery | answered | 04-screen-and-rank "Failure and recovery" section; data download, enrichment, no-candidates and recovery tables; cites S01/F001, S02/F001 | |
| O-04-06 | 04-screen-and-rank | Unknowns and next probes; Related documents | answered | 04-screen-and-rank "Unknowns and next probes" (8 open questions) and "Related documents" (5 links) | |
| O-05-01 | 05-api-reference | Every entry point listed (commands and parameters) | answered | 05-api-reference "All entry points" summary table and 16 per-entry sections (E001-E016); all 16 read, none marked not read; source: inventory, S01-S11 | |
| O-05-02 | 05-api-reference | Inputs and outputs per entry point | answered | 05-api-reference: Inputs table and Outputs paragraph in each of the 16 entry sections; cites S01-S11 and doc-diff N2/N3/N5/N8 for unconfirmed defaults | |
| O-05-03 | 05-api-reference | Success and error cases | answered | 05-api-reference: Success and Error cases table in each of the 16 entry sections; cites S01-S11 | |
| O-05-04 | 05-api-reference | Security (credentials, personal data) | answered | 05-api-reference: Security paragraph in each of the 16 entry sections; observed security facts for E008/E009 (personal financial data, PAN password) and E001 (secret reference, terms of use), inferred for E016, not-applicable with reason for the rest; cites S01-S11 | |
| O-05-05 | 05-api-reference | Examples taken from code or tests | answered | 05-api-reference: Example paragraph in each of the 16 entry sections, quoting a test (where one exists) or stating the search boundary that found none; cites S01-S11 | |
| O-05-06 | 05-api-reference | Unknowns and next probes; Related documents | answered | 05-api-reference "Unknowns and next probes" (20 items: U01-U13, U15, U16, N2-N5, N8) and "Related documents" (6 links) | |
| O-06-01 | 06-runtime-and-deployment | Actual stack and versions, cited from build files | answered | 06-runtime-and-deployment "Actual stack and versions" section; requirements.txt's 8 packages, no pyproject.toml/setup.py, Python 3.14.3 inferred from `.venv/pyvenv.cfg`; source: inventory | |
| O-06-02 | 06-runtime-and-deployment | Runtime dependencies | answered | 06-runtime-and-deployment "Runtime dependencies" section; declared packages table, packages needed by specific commands but undeclared (pdfplumber, xlwt, pytesseract, Tesseract, xlrd), external services; cites S01, S02, S04, S05, S08, S09, inventory | |
| O-06-03 | 06-runtime-and-deployment | Configuration model and keys | answered | 06-runtime-and-deployment "Configuration model and keys" and "Persisted state and caches" sections; 5 environment variables, 4 configuration files, caches and pickled models; cites S01, S02, S04, S08, S09, inventory | |
| O-06-04 | 06-runtime-and-deployment | Packaging | answered | 06-runtime-and-deployment "Packaging" section; no package metadata, no CI files, manual two-step install inferred; source: inventory | |
| O-06-05 | 06-runtime-and-deployment | Start commands | answered | 06-runtime-and-deployment "Start commands" section; all 16 entry points' start commands, plus E013's subprocess call to E003; cites S01-S11, inventory | |
| O-06-06 | 06-runtime-and-deployment | Deployment targets and environments (as declared) | answered | 06-runtime-and-deployment "Deployment targets and environments" section; local-machine-only, no environment-specific config, declared only (no runtime evidence); cites inventory, doc-diff P2/P3 | |
| O-06-07 | 06-runtime-and-deployment | Unknowns and next probes; Related documents | answered | 06-runtime-and-deployment "Unknowns and next probes" (U10, U16, U22, U23) and "Related documents" (5 links) | |
| O-07-01 | 07-error-handling-and-observability | Error and exception patterns | answered | 07-error-handling-and-observability "Error and exception patterns" section; 6 patterns (fatal stop, caught-and-continue, skip-and-continue, never-raise modules, training-vs-prediction swallowing in gov_classifier, one unhandled gap); cites S01-S11 and 02-module-architecture's "Never-raise pattern" | |
| O-07-02 | 07-error-handling-and-observability | Exit codes and status mappings | answered | 07-error-handling-and-observability "Exit codes and status mappings" table; all 16 entry points, with HTTP status mapping marked not-applicable (no server); cites S01-S11, inventory | |
| O-07-03 | 07-error-handling-and-observability | Logging and correlation | answered | 07-error-handling-and-observability "Logging and correlation" section; no `logging` import found in the slices read, print-only and sys.exit-message output, `gov_classifier.py`'s `log` parameter, no correlation ID (closest equivalent is real_data_check.py's timestamped output folder); cites S01-S03, S07, S08, S10 | |
| O-07-04 | 07-error-handling-and-observability | Health checks | answered | 07-error-handling-and-observability "Health checks" section; not-applicable for 15 of 16 entry points (no server, reason stated), E013's Yahoo/NSE connectivity check documented as the one exception; cites S07, inventory | |
| O-07-05 | 07-error-handling-and-observability | Retries, timeouts and fallbacks | answered | 07-error-handling-and-observability "Retries, timeouts and fallbacks" section: rate limiting (screener.in, nse_client), the one retry (NSE 401/403), 2 explicit timeouts with the rest unknown, a 7-row fallback table, and the 2 missing-package cases that are hard stops rather than fallbacks; cites S01, S02, S04, S05, S08, S09, S11 | |
| O-07-06 | 07-error-handling-and-observability | Unknowns and next probes; Related documents | answered | 07-error-handling-and-observability "Unknowns and next probes" (4 items: U09, U10, U16, U24 new) and "Related documents" (5 links) | |
| O-08-01 | 08-developer-onboarding | Repository layout | answered | 08-developer-onboarding "Repository layout" table; all 35 Python files grouped by role plus config and non-code files; sources: inventory, 02-module-architecture | |
| O-08-02 | 08-developer-onboarding | Prerequisites | answered | 08-developer-onboarding "Prerequisites" table; Python version (inferred), packages, undeclared package (xlrd), Tesseract, network access, working directory; cites 06-runtime-and-deployment, S04, doc-diff P2, inventory | |
| O-08-03 | 08-developer-onboarding | How to run locally and run tests (commands found in the repository or confirmed by a person) | accepted gap | 08-developer-onboarding "How to run locally and run tests" section; start commands and test-invocation convention from inventory and test_validation.py:5; whether pytest actually collects/passes the scripts is U01 (needs a person); 2 of 6 test files' pass/fail status blocked by U04/U05 | owner, 2026-10-25 |
| O-08-04 | 08-developer-onboarding | Where to make common changes | answered | 08-developer-onboarding "Where to make common changes" table, carried over from 02-module-architecture's "Extension points" and "Homegrown mechanisms", cites S01/F001, S02/F001, S06/F002, S08/F014 | |
| O-08-05 | 08-developer-onboarding | Troubleshooting known from code or interviews | answered | 08-developer-onboarding "Troubleshooting known from code" table; 9 symptom-cause rows from code only (no interview recorded yet); cites S01, S02, S03, S04, S05, S07, 06-runtime-and-deployment, 07-error-handling-and-observability | |
| O-08-06 | 08-developer-onboarding | Unknowns and next probes; Related documents | answered | 08-developer-onboarding "Unknowns and next probes" (12 items: U01-U06, U09, U10, U16, U22-U24) and "Related documents" (6 links) | |
| O-09-01 | 09-test-exposure-map | Per capability and flow: tests found, what they check, result, whether code was read | answered | 09-test-exposure-map: one section per capability (C01-C11), each with a Flow/Entry point/Read in/Test files/Result table and "What is tested"/"Known gaps" prose; all 16 flows covered, C01's F001 split into core and enrichment paths; cites S01-S11, inventory | |
| O-09-02 | 09-test-exposure-map | Summary counts | answered | 09-test-exposure-map "Summary counts" section: counts by test result (6 well tested, 4 tested on the surface, 6 not tested, 1 unknown, 0 switched off, 0 scan only not read) and a second table of gaps by capability importance | |
| O-09-03 | 09-test-exposure-map | Unknowns and next probes; Related documents | answered | 09-test-exposure-map "Unknowns and next probes" (8 items: U01, U04, U05, U06, U08, U09, U15, U16) and "Related documents" (4 links plus 2 forward pointers to documents 10 and 11) | |
| O-10-01 | 10-test-review | Strengths | answered | 10-test-review "Strengths" section; the shared pattern across all 6 well-tested flows (known-answer synthetic input, real production function, boundary-only mocking); cites S06/F002, S10/F007, S08/F014, S07/F003, S09/F004, S08/F010 | |
| O-10-02 | 10-test-review | Tests that prove little | answered | 10-test-review "Tests that prove little" section; 4 flows (F001 core, F005, F011, F012) with what each test actually asserts versus what it leaves unchecked; cites S01/F001, S09/F004, S03/F005, S08/F011, S08/F012 | |
| O-10-03 | 10-test-review | Disabled tests | answered | 10-test-review "Disabled tests" section; 0 found within the stated marker search, with the un-searched commented-out-code boundary stated; cites inventory "Disabled tests" row | |
| O-10-04 | 10-test-review | Level-of-test problems | answered | 10-test-review "Level-of-test problems" section; 3 problems (top-level-script execution model with no test isolation, 2 test files calling names the production code does not have, a tested helper function disguising an untested command); cites inventory, S01/F001, S02/F001, S08/F012 | |
| O-10-05 | 10-test-review | Risks ranked by importance times weakness | answered | 10-test-review "Risks ranked by importance times weakness" table; 7 ranked rows combining capability importance from capabilities.md with test weakness from 09-test-exposure-map.md; cites S01/F001, S02/F001, S04/F008, S03/F005, S05/F009, S07/F013, S08, S10/F006, S11 | |
| O-10-06 | 10-test-review | Unknowns and next probes; Related documents | answered | 10-test-review "Unknowns and next probes" (10 items: U01-U06, U08, U09, U15, U16) and "Related documents" (4 links plus 2 forward pointers to documents 11 and 12) | |
| O-11-01 | 11-developer-testing-tasks | 3 to 5 tasks, highest risk first | answered | 11-developer-testing-tasks: 5 tasks (C01 enrichment, C03 holdings analysis, C02 monitor, C04 CDSL converter, C06 real-data wrapper), each with target files, what to assert, steps and a done-when checklist, ordered by 10-test-review.md's risk ranking; cites S01-S05, S07, 10-test-review.md | |
| O-11-02 | 11-developer-testing-tasks | Unknowns and next probes; Related documents | answered | 11-developer-testing-tasks "Unknowns and next probes" (13 items: U01-U06, U08-U12, U15, U16) and "Related documents" (4 links plus 1 forward pointer to document 12) | |
| O-12-01 | 12-test-plan | Strategy by level | answered | 12-test-plan "Strategy by level" section; current offline and real-data levels cited, 3 recommended levels (unit, offline integration, real-data); cites 10-test-review.md "Strengths", S07/F013, S08 | |
| O-12-02 | 12-test-plan | Priority areas from document 10 | answered | 12-test-plan "Priority areas from document 10" table; 7 priority areas restated from 10-test-review.md's risk ranking with current state and what closes each | |
| O-12-03 | 12-test-plan | Entry and exit criteria | answered | 12-test-plan "Entry and exit criteria" section; entry table (U02/U03/U06 for priority 1, U01 for all offline/unit tests) and exit criteria tied to the rules section 9 test-result vocabulary | |
| O-12-04 | 12-test-plan | Tooling already in the repository | answered | 12-test-plan "Tooling already in the repository" section; top-level-assert convention, `.pytest_cache/` with no pytest config file, the monkeypatch-at-the-network-boundary pattern, 0 CI files; cites inventory "Tests", inventory "Configuration files", inventory "Surprising zeros" | |
| O-12-05 | 12-test-plan | Recommendations (labelled as such) | answered | 12-test-plan: 7 sentences labelled `Recommendation:` across "Strategy by level", "Entry and exit criteria" and "Tooling already in the repository" | |
| O-12-06 | 12-test-plan | Unknowns and next probes; Related documents | answered | 12-test-plan "Unknowns and next probes" (10 items: U01-U06, U08, U09, U15, U16) and "Related documents" (5 links) | |

## Capabilities

Five rows for every High- and Medium-importance capability (C01 to C07).

| ID | Capability | Required answer | Status | Evidence or reason | Accepted by (role, date) |
|---|---|---|---|---|---|
| O-C01-main | C01 Screen and rank candidate trades | Main flow | answered | S01 F001 | |
| O-C01-alt | C01 | Alternative flows | accepted gap | S01, S02 cover both strategies and the three enrichment modes; the `--fundamentals` path is blocked by U02 and U03 | owner, 2026-10-25 |
| O-C01-exc | C01 | Exception flows | accepted gap | S01, S02 cover data and cache failures; the fundamentals path is blocked by U02 | owner, 2026-10-25 |
| O-C01-rules | C01 | Business rules | accepted gap | S01, S02 give thresholds; P/E versus industry blocked by U03; intent of the heat ceiling is U07 | owner, 2026-10-25 |
| O-C01-test | C01 | Test result per flow | answered | S01: tested on the surface; S02 enrichment: unknown (U04, U05) | |
| O-C02-main | C02 Monitor an open position | Main flow | answered | S03 F005 | |
| O-C02-alt | C02 | Alternative flows | answered | S03: six verdicts in order (`monitor.py:84-96`) | |
| O-C02-exc | C02 | Exception flows | accepted gap | S03: errors are printed; whether real Yahoo data triggers one is U09 | owner, 2026-10-25 |
| O-C02-rules | C02 | Business rules | answered | S03: breakeven, trail, time-stop thresholds; the stop-comparison question is U08 | |
| O-C02-test | C02 | Test result per flow | answered | S03: tested on the surface | |
| O-C03-main | C03 Analyse existing holdings | Main flow | answered | S04 F008 (anomaly step is read in S08) | |
| O-C03-alt | C03 | Alternative flows | answered | S04: skipped funds, symbol map order, CSV fallback, optional switches | |
| O-C03-exc | C03 | Exception flows | answered | S04: failed holdings go to "Not analysed"; run stops when nothing is analysed | |
| O-C03-rules | C03 | Business rules | answered | S04: trend states, stop, flag thresholds | |
| O-C03-test | C03 | Test result per flow | answered | S04: not tested (search boundary stated) | |
| O-C04-main | C04 Convert a CDSL account statement to Excel | Main flow | answered | S05 F009 | |
| O-C04-alt | C04 | Alternative flows | answered | S05: text layer or OCR, `--skip-mf`, `.xls` or `.xlsx` | |
| O-C04-exc | C04 | Exception flows | answered | S05: exits, flagged rows, no wrong-password handling | |
| O-C04-rules | C04 | Business rules | answered | S05: ISIN check digit, row arithmetic, reconciliation tolerances | |
| O-C04-test | C04 | Test result per flow | answered | S05: not tested (search boundary stated) | |
| O-C05-main | C05 Backtest the trading rules on history | Main flow | answered | S06 F002 | |
| O-C05-alt | C05 | Alternative flows | answered | S06: both strategies and stop modes, --no-costs, --no-trailing, time-stop off, membership on/off | |
| O-C05-exc | C05 | Exception flows | answered | S06: no-data exit 1, per-signal skips by reason, end_of_backtest close | |
| O-C05-rules | C05 | Business rules | answered | S06: gap-aware exits (stop before target), breakeven/swing-low trail, 14-day time-stop, equity sizing with heat 8% / max 5, costs + slippage | |
| O-C05-test | C05 | Test result per flow | answered | S06: well tested (test_toolkit.py A-O, test_membership.py) | |
| O-C06-main | C06 Validate a backtest | Main flow | answered | S07 F003 (validate), F013 (real_data_check.py wrapper) | |
| O-C06-alt | C06 | Alternative flows | answered | S07: seven tests, sweep/split/report/sweep-out options; real_data_check --quick / --check-only / --dry-run | |
| O-C06-exc | C06 | Exception flows | answered | S07: bad sweep/split and too-many-combos exit 1, no-equity-curve early return, too-few-trades verdicts; real_data_check Yahoo unreachable exit 1 | |
| O-C06-rules | C06 | Business rules | answered | S07: split degradation thresholds, sweep robust/mixed/fragile, walk-forward efficiency, max 60 combos, Monte Carlo needs 20+ trades | |
| O-C06-test | C06 | Test result per flow | answered | S07: F003 well tested (test_validation.py); F013 not tested (U16) | |
| O-C07-main | C07 Check companies for red flags | Main flow | answered | S08: F010/F011/F012 (gov classifier), F014 (anomaly) | |
| O-C07-alt | C07 | Alternative flows | answered | S08: TF-IDF vs embedder, import-sheet, predict, anomaly from CLI vs screen/holdings, flag vs filter | |
| O-C07-exc | C07 | Exception flows | answered | S08: classifier too-few-rows/ImportError/prediction-error swallowed; anomaly never raises, n/a on unreadable or bank/NBFC | |
| O-C07-rules | C07 | Business rules | answered | S08: demote one step below 0.35, never promote/delete; anomaly thresholds and High/Watch/None levels | |
| O-C07-test | C07 | Test result per flow | answered | S08: classifier (TF-IDF) and anomaly well tested; import-sheet/predict tested on the surface; embedder path and real-data accuracy are known gaps | |
