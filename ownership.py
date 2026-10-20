"""
Ownership metrics (shortlisting doc, section 2):

  promoter_pct               latest promoter holding %
  promoter_change_1q         change in percentage points vs the previous quarter
  promoter_change_4q         change in percentage points vs 4 quarters earlier
  promoter_decline_streak    number of consecutive latest quarters in which promoter holding fell
  pledged_pct                % of promoter shares pledged (latest NSE disclosure)
  pledged_change_1q          change in pledged_pct vs the previous quarter (only when both quarters come
                             from XBRL shareholding filings of consecutive quarters)
  fii_pct, dii_pct           latest FII / DII holding % (screener.in table)
  inst_change_1q / _4q       change in FII+DII holding, percentage points

Sources: NSE for promoter holding and pledging (official filings); screener.in's
quarterly table for FII / DII history and as a fallback for promoter holding.
Anything that cannot be fetched is left None (shown as n/a, never guessed), and the
reason is collected in `ownership_notes`.
"""

from datetime import date

import nse_client

DECLINE_EPS = 0.05          # pp; smaller moves are rounding noise


def _series(pairs):
    return [v for _, v in (pairs or []) if v is not None]


def decline_streak(series_oldest_first) -> int:
    s, n = series_oldest_first, 0
    for k in range(len(s) - 1, 0, -1):
        if s[k] < s[k - 1] - DECLINE_EPS:
            n += 1
        else:
            break
    return n


STALE_PLEDGE_DAYS = 200      # an NSE pledge record this much older than the latest shareholding quarter is ignored


def compute(nse_holding, pledge_rows, screener_metrics=None, xbrl_pledge=None, xbrl_pledge_prev=None) -> dict:
    """nse_holding / pledge_rows: parsed lists, newest first. screener_metrics: dict with hold_* lists."""
    sm = screener_metrics or {}
    out = {k: None for k in ("promoter_pct", "promoter_change_1q", "promoter_change_4q", "promoter_decline_streak",
                             "pledged_pct", "pledged_change_1q", "fii_pct", "dii_pct", "inst_change_1q", "inst_change_4q",
                             "ownership_src", "ownership_asof", "pledged_pct_total", "pledge_src", "pledge_asof",
                             "pledge_note")}
    srcs = []
    prom = [h["promoter"] for h in reversed(nse_holding or [])]          # oldest -> newest
    if len(prom) >= 2:
        srcs.append("NSE")
        out["ownership_asof"] = str(nse_holding[0]["date"])
    else:
        prom = _series(sm.get("hold_promoters"))
        if prom:
            srcs.append("screener.in")
            out["ownership_asof"] = (sm["hold_promoters"][-1][0])
    if prom:
        out["promoter_pct"] = round(prom[-1], 2)
        out["promoter_decline_streak"] = decline_streak(prom)
        if len(prom) >= 2:
            out["promoter_change_1q"] = round(prom[-1] - prom[-2], 2)
        if len(prom) >= 5:
            out["promoter_change_4q"] = round(prom[-1] - prom[-5], 2)

    xp = xbrl_pledge or {}
    latest_hold = nse_holding[0]["date"] if nse_holding else None
    row = pledge_rows[0] if pledge_rows else None
    if row and row.get("date") and latest_hold and (latest_hold - row["date"]).days > STALE_PLEDGE_DAYS:
        out["pledge_note"] = f"NSE pledge record is from {row['date']}, older than the latest shareholding; ignored"
        row = None
    if xp.get("pledged_pct") is not None:             # latest filing: dated, with a yes/no flag
        out["pledged_pct"] = xp["pledged_pct"]
        out["pledged_pct_total"] = xp.get("pledged_pct_total")
        out["pledge_asof"], out["pledge_src"] = xp.get("asof"), "NSE shareholding filing (XBRL)"
        srcs.append("NSE filing pledge")
    elif row:
        out["pledged_pct"] = round(row["pledged_pct"], 2)
        out["pledge_asof"], out["pledge_src"] = (str(row["date"]) if row.get("date") else None), "NSE pledge API"
        srcs.append("NSE pledge")
    elif sm.get("pledged_pct_screener") is not None:        # screener.in shows this ratio when promoters have pledged
        out["pledged_pct"] = sm["pledged_pct_screener"]
        out["pledge_src"] = "screener.in"
        srcs.append("screener.in pledge")

    pv = xbrl_pledge_prev or {}
    if ((out["pledge_src"] or "").startswith("NSE shareholding filing")
            and xp.get("pledged_pct") is not None and pv.get("pledged_pct") is not None):
        try:
            gap = (date.fromisoformat(xp["asof"]) - date.fromisoformat(pv["asof"])).days
        except (KeyError, ValueError, TypeError):
            gap = None
        if gap is not None and 60 <= gap <= 120:           # consecutive quarters only
            out["pledged_change_1q"] = round(xp["pledged_pct"] - pv["pledged_pct"], 2)

    fii, dii = _series(sm.get("hold_fiis")), _series(sm.get("hold_diis"))
    if fii:
        out["fii_pct"] = fii[-1]
    if dii:
        out["dii_pct"] = dii[-1]
    n = min(len(fii), len(dii))
    if n >= 2:
        inst = [a + b for a, b in zip(fii[-n:], dii[-n:])]
        out["inst_change_1q"] = round(inst[-1] - inst[-2], 2)
        if n >= 5:
            out["inst_change_4q"] = round(inst[-1] - inst[-5], 2)
        srcs.append("screener.in FII/DII")
    out["ownership_src"] = " + ".join(srcs) or None
    return out


def get(symbol: str, screener_metrics: dict = None, use_nse: bool = True) -> dict:
    """Fetch (cached) and compute. Never raises; failures are reported in ownership_notes."""
    notes, hold, pl = [], [], []
    if use_nse:
        for label, fn in (("shareholding", nse_client.shareholding), ("pledge", nse_client.pledge)):
            try:
                res = fn(symbol)
                if label == "shareholding":
                    hold = res
                else:
                    pl = res
                if not res:
                    notes.append(f"NSE {label}: no records")
            except Exception as e:
                notes.append(f"NSE {label}: {type(e).__name__}: {e}"[:160])
    xp = xp_prev = None
    if use_nse:
        try:
            xp = nse_client.xbrl_pledge(symbol)
            if xp is None:
                notes.append("NSE XBRL: no filing link")
            elif xp.get("note"):
                notes.append(xp["note"])
            if xp and xp.get("pledged_pct") is not None:
                try:
                    xp_prev = nse_client.xbrl_pledge(symbol, back=1)
                except Exception as e:
                    notes.append(f"NSE XBRL (previous quarter): {type(e).__name__}: {e}"[:160])
        except Exception as e:
            notes.append(f"NSE XBRL: {type(e).__name__}: {e}"[:160])
    out = compute(hold, pl, screener_metrics, xp, xp_prev)
    if out.get("pledge_note"):
        notes.append(out["pledge_note"])
    out["ownership_notes"] = " | ".join(notes)
    return out
