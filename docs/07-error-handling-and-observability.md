# Error handling and observability

Audience: a developer who needs to know how each command fails, what it prints when it does, and where to look when a run goes wrong silently instead of loudly.

Evidence: 16 of 16 entry points read · 11 capabilities · 4 open unknowns · commit b472b9b · Surveyor 2.2.0 · 2026-10-25

---

## How to read this document

These are command-line tools run by hand, not a server. There is no HTTP status code to map, no uptime to watch, and no log aggregator to query. "Observability" here means what a run prints to the console, what file it leaves behind, and what exit code the shell sees afterward. Command options are not repeated here; see [05-api-reference.md](05-api-reference.md) for those, and [06-runtime-and-deployment.md](06-runtime-and-deployment.md) for the packages each failure message points the owner to install.

## Error and exception patterns

The 11 slices show the same few patterns repeated across the 16 entry points, rather than one shared error-handling module. Each file writes its own.

### Fatal stop: print a message, then exit

Several commands cannot continue at all past certain points. Each prints a message and calls `sys.exit`, which the shell sees as a non-zero exit code:

- `screener.py:70` - `sys.exit(1)`, when the index list cannot be downloaded and no cached copy exists [S01]
- `screener.py:410` - `sys.exit(1)`, when no price data was fetched for a backtest [S06]
- `screener.py:458` - `sys.exit(1)`, when `validate` is given a bad `--sweep`/`--split` value, or a sweep would try more combinations than `--max-combos` allows [S07]
- `screener.py:574` - `sys.exit(1)`, when `train-meta`'s dataset has fewer rows than `--min-train-trades` [S09]
- `holdings_analysis.py:437` - `sys.exit("Nothing could be analysed.")`, when every holding failed analysis [S04]
- `cdsl_holdings_to_xls.py:624` - `sys.exit("No holding rows were found. Try --force-ocr, a higher --dpi, or --pages.")`, when the converter finds no rows [S05]
- `cdsl_holdings_to_xls.py:940` - `sys.exit("Writing .xls needs xlwt: ...")`, when the `xlwt` package is missing [S05]
- `real_data_check.py:80` - `sys.exit(1)`, when Yahoo Finance cannot be reached outside a dry run [S07]
- `diagnose_dump.py:88` - `sys.exit(f"nothing in {folder}")`, when the dump folder is empty [S11]
- `gov_classifier.py:305-306` - `except (ValueError, OSError, ImportError) as e: sys.exit(f"Error: {e}")`, one handler in `main()` shared by `train`, `import-sheet` and `predict`, covering too few labelled rows, a sheet missing a required column, and a bad model path [S08]

`sys.exit` called with a string (as in the `holdings_analysis.py` and `cdsl_holdings_to_xls.py` lines above) prints that string and exits with status 1, the same as `sys.exit(1)`. No quoted call in the slices read passes any other numeric code.

### Caught and reported, run continues to a normal exit

Some commands catch an error, print it, and return, with no further processing and no `sys.exit` call. The slices that read these commands whole (S03, S10) found no `sys.exit` in them, so the process ends with exit code 0 even though the command failed to do what was asked:

- `monitor`: "Any error (no data, bad date, network problem) is caught, printed as 'Error: ...', and the function returns. The process then ends normally with exit code 0 (inferred: no `sys.exit` call in `cmd_monitor`)" [S03], evidence `screener.py:635` - `print(f"Error: {e}")`
- `update-price`: a missing file or a file without a `symbol` column prints an error and returns [S10], evidence `screener.py:659` and `screener.py:668`
- `snapshot-changes`: no snapshot differences to turn into rows prints a message and returns without writing [S10], evidence `screener.py:612-613`

### Skip the item, continue the run

Several commands process a list of things (symbols, holdings, strategies, files) and treat one item's failure as data, not as a reason to stop:

- `screen` skips a symbol whose price history cannot be downloaded and reports it, rather than stopping the run [S01], evidence `candidate_engine.py:91`
- the holdings analysis prints `FAILED` for a holding that raises an error and lists it on the "Not analysed" sheet, continuing to the next holding [S04], evidence `holdings_analysis.py:322`
- `real_data_check.py` prints a message naming the summary file and moves to the next strategy when one strategy's `validate` subprocess exits non-zero [S07], evidence `real_data_check.py:106-107`
- `fetch_xbrl_sample.py` treats each symbol independently: a failed shareholding fetch, an empty record set, or a failed XBRL download each print a message and move to the next symbol [S11], evidence `fetch_xbrl_sample.py:24-25`, `:28-29`, `:39-40`
- `diagnose_dump.py` prints `"{filename}: could not analyse (...)"` for a file that raises an exception and continues to the next file [S11], evidence `diagnose_dump.py:101-102`

### Never-raise modules: errors become notes, not exceptions

Four data-fetching modules are written so they never raise to their caller, a pattern also named in [02-module-architecture.md](02-module-architecture.md) under "Patterns observed." An error is caught inside the module and written into the result as a note string instead:

- `ownership.py` never raises; failures are reported in an `ownership_notes` field [S02], evidence `ownership.py:119` - `"""Fetch (cached) and compute. Never raises; failures are reported in ownership_notes."""`
- `fundamentals.py` catches an ownership failure and truncates it into a note on the metrics dict [S02], evidence `fundamentals.py:298` - `metrics["ownership_notes"] = f"ownership failed: {e}"[:160]`
- `anomaly.py`'s `analyse_many` never raises: a symbol whose statements cannot be read, or that has fewer than 4 annual columns, is marked level `n/a` with the error text in a note [S08], evidence `anomaly.py:222-223`
- `qualitative.py`'s news and governance scanning likewise does not raise back into `screen`; a source failure shows up as an empty or noted result rather than stopping the enrichment step [S02]

This lets `screen` and the holdings analysis finish even when one data source is down, at the cost of a failure that is visible only if someone reads the notes column of the output file [02-module-architecture.md "Never-raise pattern," citing S02/S08].

### Training-time errors are fatal; prediction-time errors on the same model are swallowed

`gov_classifier.py` draws a sharp line between when a model error stops the command and when it does not. Training refuses to proceed on too little data, raising `ValueError` which `main` turns into a fatal exit (above) [S08], evidence `gov_classifier.py:239-240`. But once a model is loaded and applied to a flag during a `screen` or holdings-analysis run, any error is caught and swallowed into the flag itself, "a model problem must never break a run" [S08], evidence `gov_classifier.py:190-191` - `except Exception as e: ... f["ml_note"] = f"model error: {type(e).__name__}"`. The same module is strict about bad training input and permissive about a bad prediction in the middle of someone else's run.

### One known gap: an exception with no handler

`cdsl_holdings_to_xls.py` opens the statement PDF with `pdfplumber.open(pdf_path, password=password)` at line 579, and this call is not wrapped in a `try`/`except` [S05]. The slice recorded this directly: "There is no handling for a wrong PDF password: the open call at line 579 is not wrapped (search boundary: `except` in this file finds only `ImportError` handlers)" [S05]. A wrong password would raise whatever exception `pdfplumber` itself raises, uncaught, ending the run with a Python traceback rather than one of the tool's own messages. What that exception is, and what exit code results, was not read; see U24 below.

## Exit codes and status mappings

Not applicable as HTTP status codes: these are command-line tools, not a service, and no slice shows a web framework or status-code mapping anywhere in the repository [inventory "Event consumers and producers": no web framework found]. The mapping that exists is the shell exit code each command leaves behind.

| Entry point | Capability | Exits 1 (or non-zero) when | Otherwise exits 0 | Evidence |
|---|---|---|---|---|
| E001 `screen` | C01 | no cached index list when the live fetch fails (`screener.py:70`) | including "no candidates met your rules today," which prints a message and writes no CSV rather than failing (`screener.py:357`) | S01 |
| E002 `backtest` | C05 | no price data fetched (`screener.py:410`) | yes | S06 |
| E003 `validate` | C06 | bad `--sweep`/`--split`, or too many sweep combinations (`screener.py:458`) | including "no usable data," which returns early with a message instead of failing (`screener.py:480`), and "too few trades," which replaces a number with a verdict string | S07 |
| E004 `train-meta` | C08 | dataset smaller than `--min-train-trades` (`screener.py:574`); scikit-learn missing (`screener.py:577`) | including "no usable walk-forward folds," which returns a verdict instead of raising (`meta_model.py:201`) | S09 |
| E005 `monitor` | C02 | no quoted case found; errors are caught and printed, and the function returns (inferred exit 0) | yes, always, per the files read | S03 |
| E006 `update-price` | C10 | no quoted case found; a missing file or a missing `symbol` column prints an error and returns (inferred exit 0) | yes, always, per the files read | S10 |
| E007 `snapshot-changes` | C09 | no quoted case found; nothing to diff prints a message and returns (inferred exit 0) | yes, always, per the files read | S10 |
| E008 `holdings_analysis.py` | C03 | nothing could be analysed (`holdings_analysis.py:437`) | a holding that fails analysis is marked FAILED and the run continues, as long as at least one holding succeeds | S04 |
| E009 `cdsl_holdings_to_xls.py` | C04 | no rows found (`cdsl_holdings_to_xls.py:624`); `xlwt` missing (`cdsl_holdings_to_xls.py:940`) | a wrong password is an unhandled case, not one of these; see U24 | S05 |
| E010 `gov_classifier.py train` | C07 | too few labelled rows, or too few of one class (`gov_classifier.py:239-240`, exits via the shared handler at `:305-306`) | yes | S08 |
| E011 `gov_classifier.py import-sheet` | C07 | the sheet is missing a `flag`, `text` or `label` column (`gov_classifier.py:120`, same shared handler) | yes | S08 |
| E012 `gov_classifier.py predict` | C07 | the model path is missing or unreadable (same shared handler, `gov_classifier.py:305-306`) | yes | S08 |
| E013 `real_data_check.py` | C06 | Yahoo Finance unreachable outside a dry run (`real_data_check.py:80`) | a single strategy's subprocess failing is reported and does not stop the wrapper (`real_data_check.py:106-107`); the wrapper's own final exit code in that case was not read | S07 |
| E014 `anomaly.py` (command line) | C07 | no quoted case found; `analyse_many` never raises (`anomaly.py:222-223`) | yes, always, per the files read | S08 |
| E015 `diagnose_dump.py` | C11 | the folder is empty (`diagnose_dump.py:88`) | a single file's analysis error is printed and skipped | S11 |
| E016 `fetch_xbrl_sample.py` | C11 | no quoted case found; each symbol's failures are printed and skipped (`fetch_xbrl_sample.py:24-25`, `:28-29`, `:39-40`) | yes, always, per the files read | S11 |

## Logging and correlation

No slice quotes an `import logging` line in any of the 35 Python files read whole or in part across S01-S11. Every message observed in the slices is either a `print()` call to the console or a string passed to `sys.exit()`. There are no log levels, no timestamps on individual lines, and no structured fields in any output quoted in the slices.

Error messages mostly share the literal prefix `"Error: "` (for example `screener.py:457`, `screener.py:635`, `screener.py:659`, `screener.py:668`, and `gov_classifier.py:306`'s `sys.exit(f"Error: {e}")`), but this is an informal convention repeated by each file's own code, not a shared logging call [S01, S03, S07, S08, S10].

`gov_classifier.py`'s `train` function takes a `log` callable as a parameter instead of calling `print` directly, evidence `gov_classifier.py:262` - `log(f"Cross-validated ({folds}-fold) AUC {report['cv_auc']}. ...")`. This is dependency injection for output, used by the test suite to silence training output: `test_ml.py:32` passes `log=lambda *a: None` [S08]. It is a single function parameter, with no log levels, timestamps or structured fields attached to it.

No run carries a correlation ID, request ID or run ID that ties its console lines together. The closest equivalent is `real_data_check.py`, which names its output folder with a timestamp, `real_check_YYYYMMDD_HHMM/` (`real_data_check.py:82`), and writes one `summary_<strategy>.txt` file per strategy inside it (`real_data_check.py:100`), so a run's output is grouped by folder rather than tagged by an ID on each line [S07].

## Health checks

Not applicable to 15 of the 16 entry points: none runs as a server, so there is nothing to poll, and no slice found a `/health` endpoint, heartbeat file or scheduled self-check anywhere in the repository [inventory "Event consumers and producers": no queues, listeners or schedulers found].

The one exception is `real_data_check.py` (E013), which opens with a connectivity check before doing anything else: it tries Yahoo Finance and the NSE archive and requires Yahoo to be reachable, while treating NSE as not fatal because a cached index list can stand in for it [S07], evidence `real_data_check.py:74` - `ok = all([reachable(*c) for c in CHECKS])`, and the decision summary "The Yahoo check is required; the NSE check is not fatal (the last cached index list can be used)" [S07]. Its `--check-only` option stops right after this check, and `--dry-run` prints the commands it would run without executing them or needing connectivity at all [S07].

## Retries, timeouts and fallbacks

### Rate limiting and throttling

- `screener_in.py` throttles itself to one request per 1.5 seconds against screener.in [S02], evidence `screener_in.py:31` (cited in S02's supporting-code notes)
- `nse_client.py` has its own rate-limiting logic (a `MIN_DELAY`) inside the function that makes its JSON calls; `fetch_xbrl_sample.py`'s direct call to `nse_client._sess().get()` bypasses both this rate limiting and the retry behaviour below [S11], evidence `nse_client.py:60-61`

### Retries

- NSE requests retry once with a fresh session after a 401 or 403 response [S02], evidence `nse_client.py:65` - `if r.status_code in (401, 403) and attempt == 1:`
- No other retry loop was found in the slices that read `screener_in.py`, `data.py` and `qualitative.py` whole (S01, S02); whether a failed screener.in page fetch, Yahoo Finance call, Google News fetch, or Anthropic/Ollama call is retried is unknown. Search boundary: `retry|_get_with_retry` quoted only once, at `screener_in.py:249`, which calls a function of that name but the slices did not read its body for a retry count or backoff.

### Timeouts

- `fetch_xbrl_sample.py:38` - `r = nc._sess().get(url, timeout=40)`, an explicit 40-second timeout on the XBRL filing download [S11]
- `real_data_check.py:47` - `urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12)`, an explicit 12-second timeout on the reachability check [S07]
- No other quoted network call in the slices read states an explicit timeout value. Whether `nse_client.fetch`, screener.in's requests, the Google News fetch, or the Anthropic/Ollama calls carry a timeout is unknown (same search boundary as above).

### Fallbacks

| Trigger | Falls back to | Evidence |
|---|---|---|
| Live NSE index-list download fails | the last cached copy; if none exists, `screen` exits with code 1 | `universe.py:162`, `screener.py:70` [S01] |
| screener.in statement fetch fails | Yahoo Finance; if that also fails, the metrics are `None` and the rule status is `n/a` (the candidate still stays in the list) | `fundamentals.py:284`, `fundamentals.py:351` [S02] |
| NSE equity list download fails | a cached copy, or a built-in symbol table if there is no cache either | `holdings_analysis.py:110` [S04] |
| Benchmark symbol unavailable | the regime warning and relative-strength ranking are turned off; the run continues | `screener.py:138` [S01] |
| scikit-learn missing, inside the anomaly detector | the Isolation Forest layer is skipped; the threshold rules and peer z-scores still run | `anomaly.py:187` [S08] |
| Excel-writer package missing, inside the holdings analysis | the output falls back to a CSV file | `holdings_analysis.py:463` [S04] |
| `fundamental_weights.csv` missing | `fund_weights.py` writes a template file instead of failing | `fund_weights.py:64` [S04] |

Not every missing-package case is a fallback. scikit-learn missing for `train-meta` is a hard stop with an install hint (`screener.py:577`) [S09], the opposite of the behaviour for the same package missing inside the anomaly detector above. `xlwt` missing in the CDSL converter is likewise a hard stop (`cdsl_holdings_to_xls.py:940`) [S05], with no automatic switch to the `.xlsx` writer even though the module supports writing `.xlsx` when the output name ends that way.

---

## Unknowns and next probes

| ID | Question | Why it matters | Next probe |
|---|---|---|---|
| U09 | Does `df[df.index >= entry_dt]` (`monitor.py:65`) work on real Yahoo data, whose price index may carry a time zone? | If it raises, `monitor`'s own catch-all prints "Error: ..." and exits 0 (see "Caught and reported" above), so the command would look like it ran cleanly while giving no verdict. | Run `monitor` on a real symbol in a sandbox and read the output; or print `df.index.tz`. |
| U10 | Is `xlrd` actually installed? `holdings_analysis.py` needs it to open the converter's `.xls` output with pandas, and it is named in no requirements file. | If missing, this would raise an `ImportError` at a point not covered by any of the exit-code rows above; which message the user would actually see is not read. | Ask the developer which packages are installed in `.venv`; try `pd.read_excel` on a converter output in a sandbox. |
| U16 | Do `real_data_check.py` and the `validate` command produce sensible numbers on real Yahoo/NSE data, and does the connectivity-then-subprocess path work end to end? | This is the one health check in the toolkit (above); whether it actually catches a broken real-data path, rather than just confirming the two URLs respond, is unverified. | Run `python real_data_check.py --quick` (or `--check-only` first) on a machine with normal internet, and read the verdict lines in `summary_*.txt`. |
| U24 | `cdsl_holdings_to_xls.py:579` opens the password-protected PDF with no `try`/`except` around it. What exception does `pdfplumber` raise on a wrong password, and what does the user see and the exit code become? | The converter (C04) handles every other failure with its own message; this is the one path that was found with no handler at all. | Run the converter with a deliberately wrong `--password` in a sandbox and read the traceback and exit code. |

## Related documents

- [05-api-reference.md](05-api-reference.md): command options, and the per-entry-point error-case tables this document draws the exit-code patterns from.
- [06-runtime-and-deployment.md](06-runtime-and-deployment.md): the missing packages (`xlrd`, Tesseract) and the install-time messages referenced under "Fatal stop" and "Fallbacks" above.
- [02-module-architecture.md](02-module-architecture.md): the never-raise and file-based-cache patterns referenced above, and the extension points for adding a new data source that follows the never-raise convention.
- [03-request-to-response-flow.md](03-request-to-response-flow.md): the full main, alternative and exception flow per capability, of which this document extracts only the error-handling angle.
- [08-developer-onboarding.md](08-developer-onboarding.md): where a developer runs into these same error paths while setting up or troubleshooting the toolkit.
