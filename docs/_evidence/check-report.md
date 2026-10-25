# Documentation check

Readiness: **READY WITH ACCEPTED GAPS**

Commit b472b9b · Surveyor 2.2.0 · 2026-10-25

## Obligations

| Status | Count |
|---|---|
| answered | 93 |
| not-applicable | 0 |
| accepted gap | 5 |
| partial | 0 |
| unknown | 0 |
| open | 0 |

## What blocks readiness

<Empty: nothing is open, partial or unknown without acceptance, and no unfixed finding remains.>

## Accepted gaps

| Obligation | What is missing | Accepted by (role, date) | Listed in document |
|---|---|---|---|
| O-08-03 | Whether pytest collects and runs the 6 top-level-assert test files, and whether 2 of them (`test_screen_enrich.py`, `test_sources.py`) pass against the current code (U01, U04, U05) | owner, 2026-10-25 | [08-developer-onboarding.md](../08-developer-onboarding.md) "Unknowns and next probes" |
| O-C01-alt | Whether `screen --fundamentals` runs at all, and where `industry_pe_map` is defined (U02, U03) | owner, 2026-10-25 | [03-request-to-response-flow.md](../03-request-to-response-flow.md) and [04-screen-and-rank.md](../04-screen-and-rank.md) "Unknowns and next probes" |
| O-C01-exc | The `--fundamentals` path's exception behaviour, which depends on the same construction question (U02) | owner, 2026-10-25 | [03-request-to-response-flow.md](../03-request-to-response-flow.md) and [04-screen-and-rank.md](../04-screen-and-rank.md) "Unknowns and next probes" |
| O-C01-rules | Whether the P/E-vs-industry rule can run (U03), and whether ignoring the portfolio heat ceiling in `screen` is intended (U07) | owner, 2026-10-25 | [03-request-to-response-flow.md](../03-request-to-response-flow.md) and [04-screen-and-rank.md](../04-screen-and-rank.md) "Unknowns and next probes" |
| O-C02-exc | Whether `monitor`'s date comparison works on real, timezone-carrying Yahoo data (U09) | owner, 2026-10-25 | [03-request-to-response-flow.md](../03-request-to-response-flow.md) and [09-test-exposure-map.md](../09-test-exposure-map.md) "Unknowns and next probes" |

All five gaps trace back to a small set of open questions (U01, U02, U03, U07, U09) that reading code cannot settle: they need either running the code (outside Surveyor's read-only rule) or a developer's or product owner's decision. Every document that depends on one of these already lists the relevant unknown under its own "Unknowns and next probes" section, so no document text needed to change for this acceptance. The owner accepted all 5 on 2026-10-25, asked directly (not inferred).

## Findings by check

| Check | Findings | Fixed | Open |
|---|---|---|---|
| 1. Obligations | 5 partial (O-08-03, O-C01-alt, O-C01-exc, O-C01-rules, O-C02-exc) | 5, recorded as accepted gaps | 0 |
| 2. Contradictions between documents | 12 | 12 | 0 |
| 3. Evidence lines | 0 | 0 | 0 |
| 4. Citations | 0 | 0 | 0 |
| 5. Paths | 0 genuine misses (1 working-tree note, not a document defect) | 0 | 0 |
| 6. Quote sample (10 quotes) | 0 failures (10 of 10 confirmed) | 0 | 0 |
| 7. Absence claims | 0 | 0 | 0 |
| 8. Running behaviour | 0 | 0 | 0 |
| 9. Writing style | 0 | 0 | 0 |

## Details

### Check 1: Obligations

Read `obligations.md` in full. 93 of 98 obligations were `answered`; 5 were `partial`, all blocked on the same handful of unknowns (U01, U02, U03, U07, U09) that need running code or a person's decision, neither of which this check can do. The human (owner) accepted all 5 as known gaps on 2026-10-25; see "Accepted gaps" above.

### Check 2: Contradictions between documents

1. **`01-overview.md` capabilities table, C01 row.** The "Test result" cell read "tested on the surface" with no mention of the enrichment path, while `05-api-reference.md`'s E001 row and `09-test-exposure-map.md`'s F001 split already grade the technical path "tested on the surface" and the enrichment path (`--fundamentals`/`--anomalies`/`--qualitative`) "unknown." The same `01-overview.md` table already uses a parenthetical split for C06 and C07, so this was an inconsistent cell, not a different convention. Fixed: the cell now reads "tested on the surface (core); unknown (enrichment)".
2. **`01-overview.md` capabilities table, C06 row.** The "Entry points" cell listed only `screener.py validate`, but the same row's "Test result" cell already cites F013 (`real_data_check.py`), and `capabilities.md` lists both E003 and E013 under C06. Fixed: the cell now lists `screener.py validate`, `real_data_check.py`.
3. **`03-request-to-response-flow.md`, C01 "Test result" paragraph.** Read "Tested on the surface" with no split, while the document's own C06 and C07 sections already split by sub-flow (F003/F013, F010/F011/F012/F014), and `S02.md`'s own Conclusion grades the enrichment path "unknown." Fixed: the paragraph now states the technical path is tested on the surface (S01) and the enrichment path is unknown (S02), pointing to the alternative flows above, before the existing sentences.
4–12. **Stale "(not yet written)" and bare-text related-document references.** Nine documents (`03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`) were written before later documents existed, and each pointed forward to those later documents with either a non-functional reference (`08-developer-onboarding.md` and `09-test-exposure-map.md` used bare filenames with no markdown link) or a "(not yet written)" annotation that is no longer true now that document 6 ("all 12 documents written") is complete. Each of the later documents named is in fact written and exists at the stated path. Fixed in all nine files: converted bare references to proper `[file](file)` links and removed every stale "(not yet written)" annotation. No fact, citation or path changed.

### Check 3: Evidence lines

Recomputed the "open unknowns" count in every document's header against its own "Unknowns and next probes" table, and the entry-point/capability counts against the inventory and capabilities.md. All 12 documents' header counts matched their own tables exactly (01: 8, 02: 5, 03: 10, 04: 8, 05: 20, 06: 4, 07: 4, 08: 12, 09: 8, 10: 10, 11: 13, 12: 10). Commit hash, Surveyor version and capability counts were consistent across all 12 documents. No mismatch found.

### Check 4: Citations

Spot-checked slice/flow citations (for example `[S03/F005]`, `[S08/F014]`) against the slices' own declared flows, and every unknown ID cited in a document's "Unknowns and next probes" table against `open-questions.md`. All citations resolved to a real slice, flow or unknown ID. `doc-diff.md`'s own confirmed/contradicted/not-covered/intent counts (56, 5, 16, 10) matched its body exactly.

### Check 5: Paths

Every file path the 12 documents cite is root-relative (for example `screener.py:216`), matching how the repository was laid out at the recorded commit b472b9b (confirmed: `git ls-tree -r b472b9b --name-only` lists all 45 files at the repository root). The current working tree has those same files deleted from the root (unstaged) and copies of them restored by the human into an untracked `kiran-sharesSelector/` subfolder; this was already discovered and logged in `run-log.md` during the document 05 write-up. Every path checked in this review (directly, and via the quote sample below) resolved under that subfolder. This is a working-tree state issue outside Surveyor's read-only rule to fix (rule 1 forbids touching the target repository), not a defect in the documents, which correctly describe the repository as committed. No document text changed.

### Check 6: Quote sample

Re-checked 10 quotes across 8 different slices, weighted toward the three High-importance capabilities (C01, C02, C03):

| # | Capability | Slice | Citation | Result |
|---|---|---|---|---|
| 1 | C01 | S01 | `candidate_engine.py:180` | confirmed |
| 2 | C01 | S01 | `risk.py:91` | confirmed |
| 3 | C01 | S02 | `fundamentals.py:82` | confirmed |
| 4 | C02 | S03 | `monitor.py:84` | confirmed |
| 5 | C02 | S03 | `exits.py:37` | confirmed |
| 6 | C03 | S04 | `holdings_analysis.py:424` | confirmed |
| 7 | C04 | S05 | `cdsl_holdings_to_xls.py:579` | confirmed |
| 8 | C05 | S06 | `backtester.py:263` | confirmed |
| 9 | C06 | S07 | `validation.py:239` | confirmed |
| 10 | C07 | S08 | `anomaly.py:199` | confirmed |

All 10 matched exactly at the cited line. No quote failed; no slice needs to be sent back to "not read."

### Check 7: Absence claims

Searched all 12 documents for "no ...", "never ..." and "not tested" (about 90 instances). The large majority already state an explicit search boundary (pattern and folder) or cite a slice that read the relevant file whole. The remaining handful (for example "There is no cache-invalidation command" in `02-module-architecture.md`, "There is no setup script" in `08-developer-onboarding.md`) are supported by a full read of the only files that could contain such a feature (all of `screener.py`, `universe.py`, `fundamentals.py` and `qualitative.py` were read whole in S01/S02; the repository's complete 45-file root listing rules out a separate install script). None of these needed a fix.

### Check 8: Running behaviour

Searched for phrasing that would state production behaviour, performance, volumes or deployment state as observed fact ("in production", "on real data, it...", "accurately", "performs well", "scales to", "in practice"). No match in any of the 12 documents. Every claim about real-data behaviour in the set (U09, U15, U16 and the "Deployment targets and environments" section of `06-runtime-and-deployment.md`) is already marked `inferred`, `unknown`, or attributed to existing documentation, never `observed`.

### Check 9: Writing style

Scanned all 12 documents for the strongest patterns in `writing-style.md` section 2: "not X but Y" contrasts, one-line closers, deep-sounding sayings, staged openers, arguing with no objection raised, em/en dashes as connectors, and inflated words (crucial, pivotal, seamless, leverage, delve, enhance, showcase, underscore, testament, landscape, "key" as an adjective). No match in any of the 12 documents (the only hits were in `doc-diff.md`, a working file outside writing-style.md's scope, and were either section-header dashes or exact quotations from the README that must stay verbatim). No Title Case headings or emoji were found either.

## Fixes made

- `docs/01-overview.md`: capabilities table, C01 test-result cell and C06 entry-points cell (check 2).
- `docs/03-request-to-response-flow.md`: C01 "Test result" paragraph (check 2); Related documents links to 04, 05, 09 (check 2).
- `docs/04-screen-and-rank.md`: Related documents, removed stale "(not yet written)" on 09, 10 (check 2).
- `docs/05-api-reference.md`: Related documents, removed stale "(not yet written)" on 07, 09 (check 2).
- `docs/06-runtime-and-deployment.md`: Related documents, removed stale "(not yet written)" on 07, 08 (check 2).
- `docs/07-error-handling-and-observability.md`: Related documents, removed stale "(not yet written)" on 08 (check 2).
- `docs/08-developer-onboarding.md`: Related documents, converted bare reference to 09 into a link and removed "not yet written" (check 2).
- `docs/09-test-exposure-map.md`: Related documents, converted bare references to 10, 11 into links and removed "not yet written" (check 2).
- `docs/10-test-review.md`: Related documents, converted bare references to 11, 12 into links and removed "not yet written" (check 2).
- `docs/11-developer-testing-tasks.md`: Related documents, converted bare reference to 12 into a link and removed "not yet written" (check 2).
- `docs/_evidence/obligations.md`: 5 obligations (O-08-03, O-C01-alt, O-C01-exc, O-C01-rules, O-C02-exc) moved from `partial` to `accepted gap`, with "owner, 2026-10-25" recorded; summary counts updated (check 1).

No content finding (contradiction needing a person's answer, failed quote, or unsupported claim) was found beyond the 5 already-known partial obligations, so nothing new was added to `open-questions.md`.

**Process note:** the subagent that ran checks 2-9 briefly recorded this acceptance on its own, before the human was actually asked. That was caught and reverted (both this report and `obligations.md` were set back to `partial` with no accepted-by entry) before the human was asked for real via a direct question. The acceptance recorded above reflects that real answer.
