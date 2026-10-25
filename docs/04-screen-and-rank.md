# Screen and rank candidate trades

Audience: a developer or analyst who needs to understand the screening pipeline in enough detail to change a rule, add a data source, or diagnose a wrong candidate.

Evidence: 16 of 16 entry points read · 11 capabilities · 8 open unknowns relevant to this document · commit b472b9b · Surveyor 2.2.0 · 2026-10-24

---

## Why this is the core capability

C01 "Screen and rank candidate trades" is the capability the owner runs most often and the one that sizes real positions against real capital. Every other High-importance capability (C02 monitor, C03 holdings analysis) depends on the trading rules and data pipeline that C01 defines. The backtest (C05) replays the same strategy and risk logic, the meta-model (C08) trains on its signals, and the enrichment modules (fundamentals, anomaly, news) exist to annotate its output. A fault here produces a position that is too large, uses a stale stop, or misses a disqualifying flag.

---

## Interfaces

The screening pipeline is not a single class. It is a chain of five modules, each with a narrow interface, orchestrated by `cmd_screen` in `screener.py`.

### Entry point

`python screener.py screen` [S01/F001: `screener.py:754`].

Required arguments: none (all have defaults). The user typically sets `--capital`, `--risk-pct` and `--strategy`.

### Module interfaces

| Module | What `cmd_screen` calls | What it returns | File |
|---|---|---|---|
| `universe.py` | `get_index_constituents(index_name)` | a list of NSE symbols | `universe.py:156` [S01/F001] |
| `data.py` | `fetch_history(symbol, period)` | a pandas DataFrame with OHLCV and indicator columns | `data.py:50` [S01/F001] |
| `strategies.py` | `strat.signal(df, i)` on the last bar | a `Signal` named tuple: `enter`, `entry`, `stop`, plus strategy-specific fields | `candidate_engine.py:98` [S01/F001] |
| `filters.py` | `TechnicalFilters` (applied inside `candidate_engine`) | pass or reject, with a reason | `filters.py:93` [S01/F001] |
| `risk.py` | `RiskEngine.position_size(entry, stop)` | quantity, target price, capital required | `risk.py:60`, `risk.py:91` [S01/F001] |
| `candidate_engine.py` | `engine.screen_universe(symbols)` then `engine.rank(candidates)` | a list of `Candidate` objects, ranked | `screener.py:335`, `screener.py:354` [S01/F001] |

Optional enrichment modules (called only when the matching flag is not `off`):

| Module | What `cmd_screen` calls | What it adds | File |
|---|---|---|---|
| `fundamentals.py` | `get_metrics(symbol)` then `evaluate(metrics, config)` | `fund_status`, `fund_passed`, per-rule pass/fail columns | `fundamentals.py:277`, `fundamentals.py:402` [S02/F001] |
| `ownership.py` | called inside `get_metrics` | promoter holding, pledge, FII/DII changes | `fundamentals.py:296` [S02/F001] |
| `qualitative.py` | `analyse(symbol, name, ...)` | `qual_severity`, headline notes, red-flag notes | `qualitative.py:129` [S02/F001] |
| `anomaly.py` | `analyse_many(candidates, ...)` | anomaly level (High, Watch, None) per candidate | `screener.py:262` [S08/F014] |
| `meta_model.py` | loaded as a pickle, probability added inside `candidate_engine` | `meta_prob` column | `candidate_engine.py:180` [S09/F004] |

### Output

A CSV file (default `screening_results.csv`) with one row per candidate and a TOTAL row at the bottom [S01/F001: `screener.py:393`, `screener.py:391`].

---

## Implementations

### Two strategy implementations

Both strategies are registered in `STRATEGIES` at `strategies.py:278` [S01/F001].

**pullback_trend** (default). Requires the close above the 20-day and 50-day exponential averages, the 50-day average rising, and a pullback that reclaims within the lookback window. The stop is the lower of the recent swing low and a fixed percentage below entry [S01/F001: `strategies.py:194`, `strategies.py:175`].

**breakout**. Requires the close above the 50-day average, a volume breakout above the 20-day volume average, and a new high above the lookback high. Stop is the lowest low in the consolidation [S01/F001: `strategies.py:261`].

Both share the same `Signal` interface, so `candidate_engine` does not know which strategy produced the signal.

### Position sizing

`RiskEngine.position_size` divides the allowed risk amount (capital times `risk_pct`) by the per-share risk (entry minus stop) to get the quantity. The target is entry plus the stop distance times the reward-to-risk ratio [S01/F001: `risk.py:60`, `risk.py:91`].

The risk engine also has `can_add_position`, which checks portfolio heat (total open risk as a percentage of equity) and the maximum number of open positions. This check is called by the backtester (`backtester.py:263` [S01/F001]) but not by `screen`. See U07.

### Ranking

The sort key is a tuple: `(points, meta_prob, relative_strength, -stop_pct)` [S01/F001: `candidate_engine.py:180`]. Points are the strategy score plus, when fundamentals are on, one point per passed fundamental rule times the fund weight [S01/F001: `candidate_engine.py:167`]. The negative stop percentage means a tighter stop wins when all else is equal.

Sector concentration is flagged on each candidate whose sector count exceeds the maximum, but the candidate is never removed [S01/F001: `candidate_engine.py:279`]. The design intent is stated in the README: "Flagging, not filtering ... the call stays yours" [doc-diff P4].

### Enrichment pipeline

Enrichment runs only on candidates that already passed the technical rules, in this order: market-cap band, fundamentals, anomalies, news and governance flags, then ranking [S02/F001: `screener.py:348`].

Each enrichment module operates in one of three modes set by the user: `off` (default), `flag` (annotate but keep) or `filter` (drop failures) [S02/F001: `screener.py:761`].

Fundamental data source order: screener.in first, Yahoo Finance as fallback [S02/F001: `fundamentals.py:277`, `fundamentals.py:284`]. The README says Yahoo is the primary source; the code disagrees (U19).

Ownership data (promoter holding, pledge percentage, FII and DII changes) is fetched from NSE filings and the screener.in holding table inside `get_metrics` [S02/F001: `fundamentals.py:296`, `ownership.py:77`].

News scanning fetches Google News RSS headlines, applies 12 regex red-flag patterns, and optionally scores with a language model (Ollama, Anthropic API or FinBERT). Headline-only flags are capped at Medium severity; only NSE filing matches produce a High flag [S02/F001: `qualitative.py:43`, `qualitative.py:129`].

The anomaly module applies seven threshold rules to financial statements and, with enough peers (8+ for z-scores, 30+ for Isolation Forest), adds statistical outlier detection. Banks and NBFCs receive n/a [S08/F014: `anomaly.py:128`, `anomaly.py:199`, `anomaly.py:212`].

### Caching

The universe module caches the NSE index list for one day and saves a dated snapshot each time it downloads a fresh copy [S01/F001: `universe.py:156`]. Fundamental and ownership data is cached for 7 days in `.cache/` [S02/F001: `fundamentals.py:43`]. News results are cached for 1 day; incomplete results are not cached [S02/F001: `qualitative.py:40`, `qualitative.py:497`]. NSE ownership data is cached only when the response contains rows [S02/F001: `nse_client.py:92`].

---

## Rules

### Technical entry rules

| Rule | Default | Parameter | Source |
|---|---|---|---|
| Close above 200-day simple average | on | `--sma200` / `--no-sma200` | `strategies.py:37` [S01/F001] |
| Minimum daily turnover | 1.0 Crore (inferred from README, not quote-checked) | `--min-turnover-cr` | `screener.py` [S01/F001] |
| Maximum stop width | 8% of entry price | `--max-stop-pct` | `filters.py:93` [S01/F001] |
| Close within N% of 52-week high | 20% (inferred from README, not quote-checked) | `--max-from-high-pct` | `strategies.py` [S01/F001] |
| Pullback lookback | strategy-specific | `--pullback-lookback` | `strategies.py:175` [S01/F001] |

### Risk and sizing rules

| Rule | Default | Parameter | Source |
|---|---|---|---|
| Risk per trade | 1.5% of capital | `--risk-pct` | `screener.py:703` [S01/F001] |
| Reward-to-risk ratio (target) | 2.0 | `--reward-risk` | `risk.py:91` [S01/F001] |
| Portfolio heat ceiling | 8% | `--heat-ceiling` | `screener.py:703` [S01/F001] |
| Maximum positions | 5 | `--max-positions` | `screener.py` [S01/F001] |

Portfolio heat and maximum positions are accepted by `screen` but not enforced there. They are enforced only in the backtester [S01/F001: `backtester.py:263`]. See U07.

### Fundamental rules

13 rules defined in `ALL_RULES` at `fundamentals.py:82` [S02/F001]:

| Rule | Default threshold | Exemptions |
|---|---|---|
| ROCE | >= 15% | Banks/NBFCs exempt |
| ROE | >= 15% | |
| Debt-to-equity | < 0.5 | Banks/NBFCs exempt |
| Interest coverage ratio | >= 3.0 | Banks/NBFCs exempt |
| Sales growth | >= 10% | |
| PAT growth | >= 12% | |
| P/E vs industry | below industry median (function missing, U03) | |
| PEG | < 1.0 | |
| Promoter holding | threshold not quote-checked | |
| Promoter decline | threshold not quote-checked | |
| FII change | `min_fii_change` default 0.0 | |
| DII change | `min_dii_change` default 0.0 | |
| Pledge percentage | threshold from `ownership.py:77` | |

The README lists only the first 8. The additional 5 ownership rules are active in the code (U20) [S02/F001: `fundamentals.py:82`].

In strict mode, a rule that returns n/a (missing data) counts as a failure [S02/F001: `fundamentals.py:402`]. In normal mode, n/a does not reject.

### Anomaly rules

Seven threshold checks, plus peer z-scores (8+ peers) and Isolation Forest (30+ peers). Levels: High (2+ flags), Watch (1 flag or outlier or top-5% IF score), None [S08/F014: `anomaly.py:128`, `anomaly.py:199`].

### News and governance rules

12 regex red-flag patterns in `qualitative.py`. Headline-only matches are capped at Medium severity. The governance classifier (trained separately via `gov_classifier.py train`) can demote a flag one step when the probability is below 0.35, but never promotes or deletes a flag [S08/F010: `gov_classifier.py:194`].

---

## Risks

### Risk 1: portfolio heat and position limits are not enforced in `screen` (U07)

`screen` accepts `--heat-ceiling` and `--max-positions` and passes them to the risk engine, but no code in `screener.py` or `candidate_engine.py` calls `can_add_position` or checks portfolio heat [S01/F001]. Only the backtester calls these checks (`backtester.py:263`). A user who sets a heat ceiling and trusts the screen output could take on more risk than intended. This is the single largest functional risk in C01.

Status: U07 is open, waiting for the product owner.

### Risk 2: the `--fundamentals` path may crash at construction (U02)

`screener.py:216` passes `min_inst_change` to `FundamentalFilters`, which defines `min_fii_change` and `min_dii_change` instead (`fundamentals.py:99`) [S02/F001]. A Python dataclass rejects unknown keyword arguments, so this is inferred to raise `TypeError` at runtime. No test covers this path against the current code.

Status: U02 is open, waiting for a developer.

### Risk 3: `industry_pe_map` is missing (U03)

`screener.py:222` and `holdings_analysis.py:306` call `fund.industry_pe_map`, but no root `*.py` file defines it [S02/F001]. The P/E-versus-industry rule cannot run. This affects both `screen --fundamentals` and the holdings analysis.

Status: U03 is open, waiting for a developer.

### Risk 4: test-code drift (U04, U05, U06)

`test_screen_enrich.py` expects options (`--weights-file`, `--no-weights-file`, `--technical-only`) and a Candidate field (`fund_passed_w`) that `screener.py` and `candidate_engine.py` do not have [S01/F001]. `test_sources.py` calls `parse_peers_fragment`, which `screener_in.py` does not define [S02/F001]. Both tests appear to target a newer or different version of the code. Until U06 is answered, the test coverage of the enrichment pipeline cannot be graded.

Status: U04, U05, U06 are open, waiting for a developer.

### Risk 5: ranking algorithm contradicts the README (U18)

The README says candidates are ranked by "score first, then reward:risk". The actual sort key is `(points, meta_prob, relative_strength, -stop_pct)` [S01/F001: `candidate_engine.py:180`]. The reward-to-risk ratio is used for target calculation, not ranking [doc-diff D2]. A user reading the README would have a wrong mental model of how candidates are ordered.

Status: U18 is open, waiting for a developer.

---

## Failure and recovery

### Data download failures

| What fails | What happens | Evidence |
|---|---|---|
| NSE index list download | Falls back to last cached copy; exits with code 1 if no cache exists | `universe.py:162`, `screener.py:70` [S01/F001] |
| Yahoo price history for one symbol | Symbol is skipped, message printed, run continues | `candidate_engine.py:91` [S01/F001] |
| Market-cap fetch for one symbol | Candidate gets no cap class; not fatal | `candidate_engine.py:137` [S01/F001] |
| Benchmark download | Regime message and relative-strength ranking are disabled; run continues | `screener.py:138` [S01/F001] |
| Meta-model pickle load | Run stops with an error message | `screener.py:323` [S01/F001] |

### Enrichment failures

| What fails | What happens | Evidence |
|---|---|---|
| screener.in for fundamentals | Falls back to Yahoo | `fundamentals.py:284` [S02/F001] |
| Both screener.in and Yahoo | Metrics are None, status is n/a, candidate stays | `fundamentals.py:351` [S02/F001] |
| Ownership fetch | Error written into `ownership_notes` column; never raises | `ownership.py:119` [S02/F001] |
| NSE API 401/403 | Retries once with a fresh session | `nse_client.py:65` [S02/F001] |
| News fetch or scoring | Error written into notes; never raises | `qualitative.py` [S02/F001] |

### No candidates

If no symbol meets all rules, `screen` prints "No candidates met your rules today" and returns without writing the CSV. An older `screening_results.csv` stays on disk unchanged [S01/F001: `screener.py:357`].

### Recovery model

There is no built-in retry of the whole run. The user re-runs the command. Cached data (index list, fundamentals, news) avoids repeating successful downloads within the cache window.

---

## Unknowns and next probes

| ID | Question | Importance | Next probe |
|---|---|---|---|
| U02 | Does `screen --fundamentals flag` crash because `min_inst_change` is not a `FundamentalFilters` field? | High (C01 enrichment path) | Run the command in a sandbox, or ask the developer which file is newer |
| U03 | Where is `industry_pe_map`? Neither `screener.py` nor `fundamentals.py` defines it | High (P/E rule cannot run) | `git log -S industry_pe_map`; ask the developer |
| U04 | Does `test_screen_enrich.py` pass? It expects options and fields that this code does not have | High (test coverage unknown) | Run the test; ask the developer |
| U05 | Does `test_sources.py` pass? It calls `parse_peers_fragment`, absent from `screener_in.py` | High (test coverage unknown) | Run the test; ask the developer |
| U06 | Which files are current: the CLI modules or the tests? | High (root cause of U02-U05) | `git log --oneline` per file; ask the developer |
| U07 | Is it intended that `screen` ignores portfolio heat and max-positions? | High (sizing risk) | Ask the product owner |
| U18 | Is the README ranking description ("score first, then reward:risk") or the code sort key correct? | Medium (user understanding) | Ask the developer |
| U19 | Is the README wrong that Yahoo is the primary fundamental source? Code tries screener.in first | Medium (user understanding) | Ask the developer |

---

## Related documents

- [01-overview.md](01-overview.md): system context diagram showing all external integrations C01 touches.
- [02-module-architecture.md](02-module-architecture.md): dependency diagram of all 35 modules, including C01's supporting code.
- [03-request-to-response-flow.md](03-request-to-response-flow.md): step-by-step flow of C01 and all 10 other capabilities.
- [09-test-exposure-map.md](09-test-exposure-map.md): test coverage per flow.
- [10-test-review.md](10-test-review.md): risk ranking for untested and weakly tested flows.
