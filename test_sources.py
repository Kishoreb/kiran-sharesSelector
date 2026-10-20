"""
Offline tests for the screener.in / NSE / news layers. Fixtures follow the page and JSON
structures these modules EXPECT; they prove the parsing and maths, not that the live sites
still look like this (use --debug-dump on a real run to check that).

    python test_sources.py
"""
import json, os, re, tempfile
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime

import fundamentals as fund
import nse_client, ownership, qualitative as q, screener_in as si

TMP = tempfile.mkdtemp()
for mod in (si, nse_client, q):
    mod.CACHE_DIR = os.path.join(TMP, mod.__name__)
fund.CACHE_DIR = os.path.join(TMP, "fund")
si.MIN_DELAY = nse_client.MIN_DELAY = 0

# ------------------------------------------------------------------ screener.in page fixture
YEARS = [f"Mar {y}" for y in range(2015, 2026)] + ["TTM"]            # 11 annual columns + TTM
def grow(base, g, n=11): return [round(base * (1 + g) ** i, 1) for i in range(n)]
def tbl(cols, rows, cls="data-table"):
    h = "<thead><tr><th></th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead>"
    b = "".join(f'<tr><td class="text"><button class="button-plain">{l}&nbsp;<span class="blue-icon">+</span></button></td>'
                + "".join(f"<td>{v:,}</td>" if v is not None else "<td></td>" for v in vals) + "</tr>" for l, vals in rows)
    return f'<table class="{cls}">{h}<tbody>{b}</tbody></table>'
def ranges(title, d):
    return (f'<table class="ranges-table"><tr><th colspan="2">{title}</th></tr>'
            + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in d.items()) + "</table>")

sales, profit = grow(1000, .10), grow(100, .12)
interest = [20.0] * 11
pbt = [p * 1.3 for p in profit]
QCOLS = ["Dec 2023", "Mar 2024", "Jun 2024", "Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025", "Sep 2025"]
PROM = [58.0, 58.0, 57.5, 57.0, 56.2, 55.6, 55.2, 54.9]            # fell in the last 3+ quarters
FII = [10.0, 10.2, 10.5, 10.4, 10.6, 10.9, 11.0, 11.4]
DII = [8.0, 8.1, 8.3, 8.6, 8.9, 9.0, 9.2, 9.4]
def page(with_ranges=True):
    top = ('<ul id="top-ratios">'
           '<li class="flex flex-space-between" data-source="default"><span class="name">Market Cap</span>'
           '<span class="nowrap value">₹ <span class="number">12,345</span> Cr.</span></li>'
           '<li class="flex flex-space-between"><span class="name">Stock P/E</span>'
           '<span class="nowrap value"><span class="number">24.5</span></span></li>'
           '<li class="flex flex-space-between"><span class="name">ROCE</span>'
           '<span class="nowrap value"><span class="number">19.0</span> %</span></li></ul>')
    pl = ((ranges("Compounded Sales Growth", {"10 Years:": "11%", "5 Years:": "12%", "3 Years:": "13%", "TTM:": "9%"})
           + ranges("Compounded Profit Growth", {"10 Years:": "15%", "5 Years:": "16%", "3 Years:": "17%", "TTM:": "5%"})
           + ranges("Return on Equity", {"10 Years:": "17%", "5 Years:": "18%", "3 Years:": "19%", "Last Year:": "20%"}))
          if with_ranges else "")
    pl += tbl(YEARS, [("Sales", sales + [1200.0]), ("Interest", interest + [22.0]),
                      ("Profit before tax", [round(x, 1) for x in pbt] + [200.0]),
                      ("Net Profit", profit + [160.0])])
    bs = tbl(YEARS[:-1], [("Equity Capital", [50.0] * 11), ("Reserves", grow(400, .1)),
                          ("Borrowings", grow(100, .05))])
    ra = tbl(YEARS[:-1], [("Debtor Days", [30] * 11), ("ROCE %", grow(15, .02))])
    sh = tbl(QCOLS, [("Promoters", PROM), ("FIIs", FII), ("DIIs", DII), ("Public", [24.0] * 8)])
    return (f"<html><body>{top}<section id='profit-loss'>{pl}</section><section id='balance-sheet'>{bs}</section>"
            f"<section id='ratios'>{ra}</section><section id='shareholding'>{sh}</section></body></html>")

raw = si.parse_page(page())
assert raw["top"]["Stock P/E"] == "24.5" and si.num(raw["top"]["Market Cap"]) == 12345.0, raw["top"]
assert raw["ranges"]["compounded sales growth"]["5 years"] == 12.0
assert len(raw["pl"]["cols"]) == 12 and raw["pl"]["cols"][-1] == "TTM"
assert "sales" in raw["pl"]["rows"] and raw["holding"]["rows"]["promoters"][-1] == 54.9
m = si.metrics_from_raw(raw, 5)
assert m["history_years"] == 11, m["history_years"]
assert (m["sales_growth"], m["sales_growth_basis"]) == (12.0, "5Y CAGR") and m["pat_growth"] == 16.0
assert si.pick_growth(dict(m), 10)["sales_growth_basis"] == "10Y CAGR" and si.pick_growth(dict(m), 10)["sales_growth"] == 11.0
assert si.pick_growth(dict(m), 3)["pat_growth"] == 17.0
assert m["roe_avg"] == 18.0 and m["roe_years"] == 5 and abs(m["roce"] - grow(15, .02)[-1]) < 1e-6
e, r, d = 50.0, grow(400, .1)[-1], grow(100, .05)[-1]
assert abs(m["de"] - d / (e + r)) < 1e-9
assert abs(m["icr"] - (round(pbt[-1], 1) + 20) / 20) < 1e-6
assert m["pe"] == 24.5 and abs(m["peg"] - 24.5 / 16.0) < 1e-9 and m["market_cap_cr"] == 12345.0
assert m["hold_promoters"][-1] == ["Sep 2025", 54.9]
# ranges missing -> own CAGR from the 11-point series (10 intervals)
m2 = si.metrics_from_raw(si.parse_page(page(with_ranges=False)), 10)
assert abs(m2["sales_cagr_10y"] - 10.0) < 0.2 and abs(m2["pat_cagr_10y"] - 12.0) < 0.2 and m2["sales_growth_basis"] == "10Y CAGR"
assert m2["roe_avg"] is not None and m2["roe_years"] == 5
# unrecognised page raises (so fundamentals can fall back to Yahoo)
class R:  # fake response
    def __init__(s, code, text=""): s.status_code, s.text = code, text
si._http_get = lambda url: R(200, "<html><body>login required</body></html>")
try:
    si.get_raw("ZZZ", refresh=True); raise AssertionError("should have raised")
except RuntimeError as ex:
    assert "layout" in str(ex)
print("screener.in parsing ok: 11y series, 3/5/10Y CAGR (site blocks and own fallback), ROE, D/E, ICR, PEG, shareholding")

# ---- page-structure variants seen / suspected on real pages (V-Mart, JSFB, Bajaj Housing failed to parse)
plain = si.metrics_from_raw(si.parse_page(page()), 5)
nested = page().replace('<button class="button-plain">Sales&nbsp;<span class="blue-icon">+</span></button>',
    '<button class="button-plain">Sales&nbsp;<span class="blue-icon">+</span></button>'
    '<table class="inner"><thead><tr><th>a</th><th>b</th><th>c</th></tr></thead><tbody><tr><td>1</td><td>2</td><td>3</td></tr></tbody></table>')
mn = si.metrics_from_raw(si.parse_page(nested), 5)                        # a nested table must not swallow the outer rows
assert mn["sales_growth"] == plain["sales_growth"] and mn["roce"] == plain["roce"] and "net profit" in si.parse_page(nested)["pl"]["rows"]
no_th = re.sub(r"<th>(.*?)</th>", r"<td>\1</td>", page())                # header row marked up with <td>, no <th> at all
rn = si.parse_page(no_th)
assert rn["pl"] and len(rn["pl"]["cols"]) == 12 and si.metrics_from_raw(rn, 5)["sales_growth"] == plain["sales_growth"]
moved = page().replace("<section id='profit-loss'>", "<section id='quarters'>" + tbl(QCOLS, [("Sales", [1.0] * 8), ("Net Profit", [1.0] * 8)])
                       + "</section><section id='x-unknown'>")           # annual P&L outside its section; a quarterly table before it
rm = si.parse_page(moved)
assert rm["pl"] and len(rm["pl"]["cols"]) == 12, rm["pl"] and rm["pl"]["cols"]   # picked the annual table by labels, not the quarterly one
print("screener.in parser variants ok: nested tables, <td> header rows, tables outside their section")

# ---- company WITHOUT consolidated statements: /consolidated/ answers 200 with an empty page (V-Mart, JSFB, Bajaj Housing)
empty_consol = "<html><body><ul id='top-ratios'></ul><section id='profit-loss'></section><section id='shareholding'>" + tbl(QCOLS, [("Promoters", PROM), ("Public", [24.0] * 8)]) + "</section></body></html>"
calls = []
si._http_get = lambda url: (calls.append(url), R(200, empty_consol if url.endswith("/consolidated/") else page()))[1]
si.CACHE_DIR = os.path.join(TMP, "si_nocons")
rn_ = si.get_raw("NOCONS")
assert rn_["pl"] and len(rn_["pl"]["cols"]) == 12 and rn_["_basis"] == "standalone" and len(calls) == 2, (calls,)
assert si.metrics_from_raw(rn_, 5)["statements"] == "standalone" and si.metrics_from_raw(rn_, 5)["sales_growth"] == 12.0
si._http_get = lambda url: R(200, page())
si.CACHE_DIR = os.path.join(TMP, "si_cons")
assert si.metrics_from_raw(si.get_raw("HASCONS"))["statements"] == "consolidated"
print("no-consolidated fallback ok: empty /consolidated/ page -> standalone page, labelled in the output")

# ---- consolidated page with only 4 years + standalone with 11 -> long horizons come from standalone, and are labelled
def short_page():
    cols = YEARS[7:11] + ["TTM"]
    pl = tbl(cols, [("Sales", sales[7:] + [1200.0]), ("Interest", interest[7:] + [22.0]),
                    ("Profit before tax", [round(x, 1) for x in pbt[7:]] + [200.0]), ("Net Profit", profit[7:] + [160.0])])
    return f"<html><body><section id='profit-loss'>{pl}</section></body></html>"
def urls(url):
    return R(200, short_page() if url.endswith("/consolidated/") else page(with_ranges=False))
si._http_get = urls
si.CACHE_DIR = os.path.join(TMP, "si_alt")
rawa = si.get_raw("SHORT")
assert "alt" in rawa and len(rawa["alt"]["pl"]["cols"]) == 12
ma = si.metrics_from_raw(rawa, 10)
assert ma["history_years"] == 4 and ma["sales_cagr_3y"] is not None                       # own 3Y from 4 points
assert abs(ma["sales_cagr_10y"] - 10.0) < 0.2 and "sales_10y" in ma["growth_from_standalone"]   # filled from standalone
assert ma["sales_growth_basis"] == "10Y CAGR"
si._http_get = lambda url: R(200, page())                                                   # long page: no second request needed
si.CACHE_DIR = os.path.join(TMP, "si_long")
assert "alt" not in si.get_raw("LONGCO") and si.metrics_from_raw(si.get_raw("LONGCO"))["growth_from_standalone"] is None
si.CACHE_DIR = os.path.join(TMP, nse_client.__name__ and "screener_in")
# transient DNS error is retried, not fatal
calls = []
def flaky(url):
    calls.append(1)
    if len(calls) < 3: raise si.requests.ConnectionError("NameResolutionError")
    return R(200, page())
si._http_get = flaky; _sleep = si.time.sleep; si.time.sleep = lambda s: None
assert "Mar 2015" in si.fetch_html("FLAKY") and len(calls) == 3
si.time.sleep = _sleep
si._http_get = lambda url: R(200, page())
print("screener.in fallbacks ok: standalone fills long CAGR horizons (labelled), retries on DNS errors")

# ------------------------------------------------------------------ NSE parsing
today = date.today()
fmt = lambda d: d.strftime("%d-%b-%Y").upper()
hold_js = [{"symbol": "TEST", "date": fmt(date(2025, 3, 31)), "pr_and_prgrp": "55.6", "public_val": "44.4", "xbrl": "x"},
           {"symbol": "TEST", "date": fmt(date(2025, 6, 30)), "pr_and_prgrp": "55.2", "public_val": "44.8"},
           {"symbol": "TEST", "date": fmt(date(2025, 9, 30)), "pr_and_prgrp": "54.9", "public_val": "45.1"},
           {"symbol": "TEST", "date": fmt(date(2024, 12, 31)), "pr_and_prgrp": "56.2", "public_val": "43.8"},
           {"symbol": "TEST", "date": fmt(date(2024, 9, 30)), "pr_and_prgrp": "57.0", "public_val": "43.0"}]
sh = nse_client.parse_shareholding(hold_js)
assert [h["promoter"] for h in sh] == [54.9, 55.2, 55.6, 56.2, 57.0] and sh[0]["date"] == date(2025, 9, 30)
assert nse_client.parse_shareholding({"data": hold_js})[0]["promoter"] == 54.9     # {"data": [...]} wrapper
pl_js = [{"date": "30-Sep-2025", "per_promoter_shares_pledged": "3.5", "per_total_shares_pledged": "1.9"}]
pg = nse_client.parse_pledge(pl_js)
assert pg[0]["pledged_pct"] == 3.5 and "promoter" in pg[0]["field"]
ann_js = [{"an_dt": (today - timedelta(days=5)).strftime("%d-%b-%Y %H:%M:%S"), "desc": "Resignation of Statutory Auditors",
           "attchmntText": "The Company has received the resignation of M/s XYZ & Co as statutory auditors.",
           "attchmntFile": "https://nsearchives.nseindia.com/a.pdf"},
          {"an_dt": (today - timedelta(days=200)).strftime("%d-%b-%Y %H:%M:%S"), "desc": "Old thing", "attchmntText": "x"}]
an = nse_client.parse_announcements(ann_js, 90)
assert len(an) == 1 and an[0]["link"].endswith("a.pdf") and "statutory auditors" in an[0]["text"]
print("NSE parsing ok: shareholding, pledge, announcements (90-day window)")

# pledge endpoint: first query empty -> date-range query -> bulk query filtered by symbol (real responses were all empty)
import datetime as _dt
seen_q = []
def pledge_api(path, params):
    seen_q.append(dict(params))
    if "from_date" in params and "symbol" not in params:                  # bulk answer: many companies
        return {"comNameList": ["A", "B"], "data": [dict(pl_js[0], symbol="OTHER"), dict(pl_js[0], symbol="WANTED", per_promoter_shares_pledged="12.5")]}
    return {"comNameList": [], "data": []}
nse_client._http_json = pledge_api
os.makedirs(nse_client.CACHE_DIR, exist_ok=True)
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
nse_client._bulk_pledge = None
got = nse_client.pledge("WANTED")
assert got and got[0]["pledged_pct"] == 12.5 and len(seen_q) == 3, (got, seen_q)
assert "symbol" in seen_q[0] and "from_date" not in seen_q[0] and "from_date" in seen_q[1] and "symbol" in seen_q[1] and "symbol" not in seen_q[2]
assert nse_client.pledge("NOBODY") == []                                  # not in the bulk list -> empty, not someone else's data
print("pledge probing ok: plain -> symbol+dates -> bulk list filtered by symbol")

# ------------------------------------------------------------------ ownership maths
assert ownership.decline_streak([58, 57.9, 57.0, 56.0, 55.0]) == 4
assert ownership.decline_streak([55, 56, 55.5, 55.0]) == 2 and ownership.decline_streak([55, 55.02, 54.98]) == 0
o = ownership.compute(sh, pg, m)
assert o["promoter_pct"] == 54.9 and o["promoter_decline_streak"] == 4 and o["promoter_change_4q"] == -2.1
assert o["pledged_pct"] == 3.5 and o["fii_pct"] == 11.4 and o["dii_pct"] == 9.4
assert o["inst_change_1q"] == round((11.4 + 9.4) - (11.0 + 9.2), 2)
o2 = ownership.compute([], [], m)                      # NSE down: falls back to screener.in table
assert o2["promoter_pct"] == 54.9 and o2["pledged_pct"] is None and o2["ownership_src"].startswith("screener.in")
o3 = ownership.compute(sh, [], dict(m, pledged_pct_screener=7.5))       # NSE pledge empty -> screener.in ratio
assert o3["pledged_pct"] == 7.5 and "screener.in pledge" in o3["ownership_src"]
print("ownership ok:", {k: o[k] for k in ("promoter_pct", "promoter_decline_streak", "pledged_pct", "inst_change_1q")})

# ------------------------------------------------------------------ end to end: fundamentals.get_metrics with mocked network
si._http_get = lambda url: R(200, page())
def fake_nse(path, params):
    return {"/api/corporate-share-holdings-master": hold_js, "/api/corporate-pledgedata": pl_js,
            "/api/corporate-announcements": ann_js}[path]
nse_client._http_json = fake_nse
fund.configure(provider="screener", growth_years=5, use_nse=True, fallback=True)
met, note = fund.get_metrics("TEST")
assert met["source"] == "screener.in" and met["sales_growth_basis"] == "5Y CAGR" and met["promoter_pct"] == 54.9
res = fund.evaluate(met, "Capital Goods", fund.FundamentalFilters(), None)
assert "promoter_holding" in res["passed"] and "pledging" in res["passed"] and "institutional_trend" in res["passed"]
assert "promoter_trend" in res["failed"], res            # fell 3 quarters in a row
fund.configure(growth_years=10)
met10, _ = fund.get_metrics("TEST")                       # served from cache, growth re-picked
assert met10["sales_growth_basis"] == "10Y CAGR" and met10["sales_growth"] == 11.0
fund.configure(growth_years=5)
# a stricter pledge limit fails the pledging rule; no-promoter company -> promoter rules n/a
assert "pledging" in fund.evaluate(met, "x", fund.FundamentalFilters(max_pledge=2), None)["failed"]
widely = dict(met, promoter_pct=0.0)
assert {"promoter_holding", "promoter_trend", "pledging"} <= set(fund.evaluate(widely, "x", fund.FundamentalFilters(), None)["unknown"])
# NSE down -> metrics still returned, ownership from screener.in, reason recorded
nse_client._http_json = lambda p, a: (_ for _ in ()).throw(RuntimeError("403 blocked"))
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
met_b, _ = fund.get_metrics("TEST")
assert met_b["promoter_pct"] == 54.9 and met_b["pledged_pct"] is None and "403" in met_b["ownership_notes"]
# screener.in down -> falls back to Yahoo path with a note
si._http_get = lambda url: R(500)
fund.CACHE_DIR = os.path.join(TMP, "fund2")
fund._yahoo_metrics = lambda s: ({"roce": 10.0, "source": "yahoo"}, "")
met_c, note_c = fund.get_metrics("OTHER")
assert met_c["source"] == "yahoo" and "screener.in" in note_c and "Yahoo" in note_c, note_c
fund.configure(fallback=False)
assert fund.get_metrics("OTHER2")[0] is None
fund.configure(fallback=True)
print("fundamentals.get_metrics ok: screener+NSE, growth re-pick from cache, NSE-down and screener-down fallbacks")

# ------------------------------------------------------------------ news, sentiment, red flags
now = datetime.now(timezone.utc)
def item(days, title, src="ET"):
    return (f"<item><title>{title} - {src}</title><link>https://n.example/{abs(hash(title)) % 9999}</link>"
            f"<pubDate>{format_datetime(now - timedelta(days=days))}</pubDate><source>{src}</source></item>")
rss = ("<rss><channel>" + "".join([
    item(3, "Test Industries shares plunge after SEBI probe into disclosures"),
    item(8, "Test Industries misses estimates as profit falls"),
    item(12, "Test Industries CFO resigns amid concerns"),
    item(20, "Test Industries slips on weak demand"),
    item(45, "Test Industries shares surge on record order win"),
    item(60, "Test Industries profit beats estimates, brokerages upgrade"),
    item(75, "Test Industries announces dividend, strong growth outlook"),
    item(80, "Test Industries stock rallies as demand recovery boosts outlook"),
    item(5, "Totally unrelated headline about cricket")]) + "</channel></rss>")
items = q.parse_rss(rss, "TEST INDUSTRIES LIMITED")
assert len(items) == 8 and items[0]["title"].startswith("Test Industries shares plunge") and not items[0]["title"].endswith("- ET")
scores = [q.lexicon_score(i["title"]) for i in items]
sm = q.sentiment_summary(items, scores)
assert sm["news_n_30d"] == 4 and sm["news_n_prev"] == 4 and sm["sentiment_30d"] < -0.3 and sm["sentiment_prev"] > 0.3
assert sm["sentiment_trend"] < -0.6 and sm["sentiment_label"] == "Negative"
assert q.sentiment_summary(items[:3], scores[:3])["sentiment_trend"] is None      # too few headlines: no trend claim
assert q.lexicon_score("Company denies fraud allegations") >= 0 and q.lexicon_score("Not a good quarter: profit falls") < 0
cases = {"Auditor resigns citing lack of information": "auditor_resignation",
         "SEBI slaps penalty on promoter of Test": "sebi_action", "SEBI probe into insider trading": "sebi_action",
         "ED raids offices of Test Ltd": "fraud_probe", "Lenders invoke pledge on promoter shares": "pledge_invocation",
         "NCLT admits insolvency plea against Test": "insolvency_default", "CRISIL downgrades rating on Test's bonds": "rating_downgrade",
         "Test delays submission of financial results": "results_delay", "CFO of Test resigns": "mgmt_exit",
         "Promoters sell 2% stake in Test via block deal": "promoter_selling", "Test hit by short seller report": "short_seller",
         "Auditor flags qualified opinion on FY25 accounts": "qualified_audit"}
for text, want in cases.items():
    got = [f[0] for f in q.scan_text(text)]
    assert want in got, (text, got)
# false-positive guards seen in a real run: broker rating cuts, bids for insolvent firms, boilerplate IBC mentions
for fp in ("Nomura cuts rating on Siemens to neutral, trims target price",
           "Polycab wins bid for insolvent cable maker under IBC, resolution applicant approved",
           "Test Industries to acquire stake in firm undergoing insolvency resolution process",
           "No proceedings are pending against the company under the Insolvency and Bankruptcy Code",
           "Siemens Energy flags insolvency and bankruptcy law changes in disclosure"):
    assert not [f for f in q.scan_text(fp) if f[0] in ("rating_downgrade", "insolvency_default")], (fp, q.scan_text(fp))
assert [f[0] for f in q.scan_text("ICRA downgrades Test's long-term rating to BBB-")] == ["rating_downgrade"]
assert "insolvency_default" in [f[0] for f in q.scan_text("NCLT admits insolvency petition against Test Industries")]
nf = q.scan_items([{"title": "SEBI slaps penalty on Test", "date": "2026-10-01"}], "news")
assert nf[0]["severity"] == "Medium" and q.scan_items([{"text": "SEBI slaps penalty on Test"}], "NSE")[0]["severity"] == "High"
# ---- regression cases taken VERBATIM from a real run (flag text in the Governance flags sheet)
def fl(text, source="nse", tokens=None): return {f[0]: f[1] for f in q.scan_text(text, tokens, source)}
assert fl("Resignation: Trent Limited has informed the Exchange regarding Intimation of resignation of Non-Executive Non-Independent Director of the Company.") == {"mgmt_exit_minor": "Low"}
assert fl("Resignation: Jana Small Finance Bank Limited has informed the Exchange regarding Resignation of  Lakshmi R N as Company Secretary & Compliance Officer of the company") == {"mgmt_exit_minor": "Low"}
assert fl("General Updates: Tube Investments of India Limited has informed the Exchange about Resignation of Statutory Auditors of a Material Subsidiary") == {"auditor_resignation_subsidiary": "Medium"}
assert fl("Updates: Please refer the enclosed intimation regarding the resignation of Statutory Auditors of material subsidiary of the Company.") == {"auditor_resignation_subsidiary": "Medium"}
assert fl("Intimation: the Company has received the resignation of M/s XYZ & Co as its statutory auditors") == {"auditor_resignation": "High"}
assert fl("Disclosure of material issue: LIC Housing Finance Limited has informed regarding Clarification with respect to Media Reports concerning NCLT Order in the Personal Insolvency Proceedings of Dr. Subhash Chandra") == {}
assert fl("Corporate Insolvency Resolution Process: Polycab India Limited has informed the Exchange about Corporate Insolvency Resolution Process") == {"insolvency_default": "High"}
assert fl("Resignation of Mr X as Chief Financial Officer of the Company") == {"mgmt_exit": "Medium"}
assert "mgmt_exit" in fl("Colgate Shares Fall 1.2% As CEO Prabha Narasimhan To Step Down", "news", ["colgate"])
hd = "Edelweiss Financial promoter sells over half a percent stake; HDFC MF buys 0.51% stake in HEG"
assert fl(hd, "news", ["hdfc"]) == {} and fl(hd, "news", ["edelweiss"]) == {"promoter_selling": "Medium"}
assert q.top_severity([{"severity": "Low"}]) == "Low" and q.top_severity([{"severity": "Low"}, {"severity": "Medium"}]) == "Medium"
for clean in ("Test Industries shares surge on record order win", "Fraud detection startup raises funds", "Test launches new fine dining chain"):
    assert not q.scan_text(clean), (clean, q.scan_text(clean))
print("news ok: RSS parsing + off-topic filter, 30d vs prior sentiment and trend, 12 flag patterns, no false hits on 3 clean headlines")

# LLM scorer: parsing, batching, failure -> None
assert q.LLMScorer.parse('noise {"scores":[0.5,-2,"0.1"]} tail', 3) == [0.5, -1.0, 0.1]
assert q.LLMScorer.parse('{"scores":[0.5]}', 2) is None and q.LLMScorer.parse("not json", 1) is None
sc = q.LLMScorer("ollama", "m"); sc.batch = 2
calls = []
def fake_call(prompt):
    calls.append(prompt); n = prompt.count("\n1. ") and len([l for l in prompt.splitlines() if l[:1].isdigit() and ". " in l[:4]])
    if len(calls) == 2: raise RuntimeError("model down")
    return json.dumps({"scores": [0.4] * n})
sc._call = fake_call
out = sc.score("Test", ["a", "b", "c", "d"])
assert out == [0.4, 0.4, None, None], out
print("LLM scorer ok: JSON parse/clamp, batching, a failed batch becomes None (lexicon fallback)")

# long legal names: full-name query finds nothing, the shorter query / ticker query is tried (CAS names are mangled)
assert q.clean_company_name("ABB INDIALIMITED") == "ABB INDIA" and q.clean_company_name("CONTAINER CORPORATION OF INDIA LIMITED") == "CONTAINER CORPORATION OF INDIA"
assert q.clean_company_name("AMBUJA CEMENTS LIMITED- NEW EQUITY SHARES OF RS.2/- AFTER SPLIT") == "AMBUJA CEMENTS"
seen_terms = []
def multi(url, params=None, **kw):
    term = params["q"].split('"')[1]; seen_terms.append(term)
    return RR(rss.replace("Test Industries", "Paras Defence") if term in ("PARAS DEFENCE", "PARAS") else "<rss><channel></channel></rss>")
class RR:
    def __init__(s, t): s.text = t
    def raise_for_status(s): pass
q.requests.get = multi
got = q.fetch_news("PARAS DEFENCE AND SPACE TECHNOLOGIES LIMITEDA", 90, symbol="PARAS")
assert seen_terms[:2] == ["PARAS DEFENCE AND SPACE TECHNOLOGIES", "PARAS DEFENCE"] and len(got) == 8, (seen_terms, len(got))
q.requests.get = lambda url, params=None, **kw: RR("<rss><channel></channel></rss>")
nse_client._http_json = lambda p, a: []
empty = q.analyse("NONE1", "NO NEWS CO LIMITED", days=90)
assert "no headlines found" in empty["q_notes"] and empty["news_n_30d"] == 0 and empty["sentiment_30d"] is None
# analyse(): NSE flag outranks news flags, results cached only when complete
q.requests.get = lambda url, **kw: RR(rss)
nse_client._http_json = lambda p, a: ann_js
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
res = q.analyse("TEST", "TEST INDUSTRIES LIMITED", days=90)
assert res["flag_severity"] == "High" and res["flags"][0]["source"] == "NSE" and res["flags"][0]["flag"] == "auditor_resignation"
assert res["sentiment_label"] == "Negative" and res["top_negative"] and not res["q_notes"] and res["scorer"] == "lexicon"
assert {"sebi_action", "mgmt_exit"} <= {f["flag"] for f in res["flags"]}
assert len(os.listdir(q.CACHE_DIR)) == 1                                       # cached
q.requests.get = lambda url, **kw: (_ for _ in ()).throw(ConnectionError("offline"))
assert q.analyse("TEST", "TEST INDUSTRIES LIMITED", days=90)["flag_severity"] == "High"   # served from cache
bad = q.analyse("NEW", "NEW CO", days=90)                                      # everything fails: no crash, notes explain
nse_client._http_json = lambda p, a: (_ for _ in ()).throw(RuntimeError("blocked"))
bad = q.analyse("NEW2", "NEW CO", days=90)
assert bad["flag_severity"] == "" and "news" in bad["q_notes"] and "NSE announcements" in bad["q_notes"]
print("qualitative.analyse ok: NSE filings first, cached when complete, never raises when sources are down")

# ------------------------------------------------------------------ caches vs --debug-dump / --refresh-cache
si.CACHE_DIR = os.path.join(TMP, "si_cache"); os.makedirs(si.CACHE_DIR)
fetches = []
si._http_get = lambda url: (fetches.append(url), R(200, page()))[1]
# an old-format cache file (no version) must not be trusted
with open(si._cache_path("OLD"), "w") as f_: json.dump(si.parse_page(page()), f_)
si.get_raw("OLD"); assert len(fetches) >= 1, "unversioned cache file was served"
n_after_first = len(fetches); si.get_raw("OLD"); assert len(fetches) == n_after_first, "fresh versioned cache should be served"
dump = os.path.join(TMP, "dump"); si.DEBUG_DIR = nse_client.DEBUG_DIR = dump
si.get_raw("OLD"); assert not os.path.exists(dump), "cache hit must not fetch (so nothing to dump) -- that is the situation to avoid"
fund.configure(debug_dir=dump)                           # debug dump implies cache bypass
assert si.FORCE_REFRESH and nse_client.FORCE_REFRESH and q.FORCE_REFRESH and fund.FORCE_REFRESH
si.get_raw("OLD")
assert any(n_.startswith("screener_OLD") for n_ in os.listdir(dump)), os.listdir(dump)
# NSE: an empty answer is saved to the dump but NOT cached; a non-empty one is cached
nse_client._http_json = lambda p, a: []
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
nse_client.fetch("pledge", "EMPTYCO")
assert os.path.exists(os.path.join(dump, "nse_pledge_EMPTYCO.json"))
assert not os.path.exists(nse_client._cache_file("pledge", "EMPTYCO"))
nse_client._http_json = lambda p, a: pl_js
nse_client.fetch("pledge", "FULLCO"); assert os.path.exists(nse_client._cache_file("pledge", "FULLCO"))
# reset module state for any later use
si.FORCE_REFRESH = nse_client.FORCE_REFRESH = q.FORCE_REFRESH = fund.FORCE_REFRESH = False
si.DEBUG_DIR = nse_client.DEBUG_DIR = None
print("cache handling ok: old cache files refetched, --debug-dump forces fresh fetches and fills the folder, empty NSE answers are never cached")


# ------------------------------------------------------------------ pledge: real Wockhardt XBRL values + real NSE record
def ctx(name, shares, pct):
    return (f'<in-bse-shp:NumberOfSharesEncumberedUnderPledged contextRef="{name}" decimals="INF" unitRef="shares">{shares}</in-bse-shp:NumberOfSharesEncumberedUnderPledged>'
            f'<in-bse-shp:EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares contextRef="{name}" decimals="INF" unitRef="pure">{pct}</in-bse-shp:EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares>'
            f'<in-bse-shp:NumberOfSharesEncumbered contextRef="{name}" decimals="INF" unitRef="shares">{shares}</in-bse-shp:NumberOfSharesEncumbered>')
def xbrl(flag, body):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="no"?><!--SHP V1.2--><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            f'<in-bse-shp:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged contextRef="MainI">{flag}</in-bse-shp:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged>'
            f'<in-bse-shp:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledgedForPromoterAndPromoterGroup contextRef="MainI">{flag}</in-bse-shp:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledgedForPromoterAndPromoterGroup>'
            f'{body}</xbrli:xbrl>')
WOCK = xbrl("true", ctx("IndividualsOrHinduUndividedFamily_ContextI", 0, 0) + ctx("OtherIndianShareholders_ContextI", 7992708, 0.1012)
            + ctx("Indian_ContextI", 7992708, 0.0997) + ctx("ShareholdingOfPromoterAndPromoterGroup_ContextI", 7992708, 0.0997)
            + ctx("ShareholdingPattern_ContextI", 7992708, 0.0492) + ctx("OthersIndianShareholders_Context19", 7992708, 0.1218))
px = nse_client.parse_xbrl_pledge(WOCK)
assert px["flag"] is True and px["pledged_pct"] == 9.97 and px["pledged_pct_total"] == 4.92 and px["pledged_shares"] == 7992708.0, px
# VEDL-style: flag false, no figures -> a real 0, not n/a
nf = nse_client.parse_xbrl_pledge(xbrl("false", ""))
assert nf["pledged_pct"] == 0.0 and nf["pledged_shares"] == 0.0 and nf["flag"] is False
# flag true but the promoter figure missing -> n/a (None), with a note; no flag and no figures -> n/a
assert nse_client.parse_xbrl_pledge(xbrl("true", ""))["pledged_pct"] is None and nse_client.parse_xbrl_pledge(xbrl("true", ""))["note"]
assert nse_client.parse_xbrl_pledge("<xbrl></xbrl>")["pledged_pct"] is None
# tag-name exactness: ...UnderPledged must not pick up ...UnderPledgedForPromoterAndPromoterGroup
assert nse_client._xbrl_values(WOCK, "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged") == {"MainI": "true"}
# a value over 1 (not a fraction) is rejected rather than shown as >100%
assert nse_client.parse_xbrl_pledge(xbrl("true", ctx("ShareholdingOfPromoterAndPromoterGroup_ContextI", 5, 9.97)))["pledged_pct"] is None

# real NSE pledge record (Wockhardt): percPromoterShares is used and `shp` is the date
real_rec = {"broadcastDt": "19-Oct-2026 16:30:51", "comName": "Wockhardt Limited", "compBroadcastDate": "31-08-2021",
            "noOfPledgeShare": "2477.985", "noOfSecPledgeShare": "4499.061", "numSharesPledged": "21259087",
            "percPromoterHolding": "    49.08", "percPromoterShares": "    14.68", "percSharesPledged": "13.11",
            "percTotShares": "     7.21", "shp": "30-Jun-2026", "totPromoterHolding": "79758848", "totPromoterShares": "11709045"}
rp = nse_client.parse_pledge({"comNameList": ["Wockhardt Limited"], "data": [real_rec]})
assert rp[0]["pledged_pct"] == 14.68 and rp[0]["field"] == "percPromoterShares" and rp[0]["date"] == date(2026, 6, 30), rp
assert abs(11709045 / 79758848 * 100 - 14.68) < 0.01                      # the field really is pledged / promoter holding

# ownership: the XBRL figure wins over the older NSE record; stale NSE record is ignored; no pledge info stays None
hold_w = [{"date": date(2026, 9, 30), "promoter": 49.3, "public": 50.7}, {"date": date(2026, 6, 30), "promoter": 49.1, "public": 50.9}]
ow = ownership.compute(hold_w, rp, None, dict(px, asof="2026-09-30"))
assert ow["pledged_pct"] == 9.97 and ow["pledged_pct_total"] == 4.92 and ow["pledge_src"].startswith("NSE shareholding filing") and ow["pledge_asof"] == "2026-09-30"
ow2 = ownership.compute(hold_w, rp, None, None)                          # no XBRL: NSE record, one quarter old, accepted
assert ow2["pledged_pct"] == 14.68 and ow2["pledge_src"] == "NSE pledge API" and ow2["pledge_asof"] == "2026-06-30"
stale = [{"date": date(2020, 12, 30), "pledged_pct": 0.0, "field": "percPromoterShares"}]   # VEDL-style six-year-old record
ow3 = ownership.compute(hold_w, stale, None, None)
assert ow3["pledged_pct"] is None and "ignored" in ow3["pledge_note"]
ow4 = ownership.compute(hold_w, stale, {"pledged_pct_screener": 7.5}, None)   # stale NSE record -> screener.in ratio instead
assert ow4["pledged_pct"] == 7.5 and ow4["pledge_src"] == "screener.in"
ow5 = ownership.compute(hold_w, [], None, nf)                            # declared no pledge -> real 0.0
assert ow5["pledged_pct"] == 0.0

# xbrl_pledge(): link resolution, caching, non-XBRL response rejected, failures not cached
hold_xb = [{"symbol": "WOCK", "date": "30-SEP-2026", "pr_and_prgrp": "49.3", "public_val": "50.7", "xbrl": "corporate/xbrl/WOCK_SHP.xml"},
           {"symbol": "WOCK", "date": "30-JUN-2026", "pr_and_prgrp": "49.1", "public_val": "50.9", "xbrl": "corporate/xbrl/OLD.xml"}]
nse_client._http_json = lambda p, a: hold_xb
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
got_urls = []
nse_client._http_text = lambda url: (got_urls.append(url), WOCK)[1]
r1 = nse_client.xbrl_pledge("WOCK")
assert got_urls == ["https://nsearchives.nseindia.com/corporate/xbrl/WOCK_SHP.xml"], got_urls    # newest quarter, relative link made absolute
assert r1["pledged_pct"] == 9.97 and r1["asof"] == "2026-09-30"
nse_client.xbrl_pledge("WOCK"); assert len(got_urls) == 1                 # second call served from cache
nse_client._http_text = lambda url: "<html><body>Access denied</body></html>"
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
try:
    nse_client.xbrl_pledge("WOCK"); raise AssertionError("should reject a non-XBRL answer")
except ValueError as ex:
    assert "not return an XBRL" in str(ex)
nse_client._http_json = lambda p, a: [dict(hold_xb[0], xbrl="-")]
assert nse_client.xbrl_pledge("NOLINK") is None
# end to end through ownership.get(): XBRL fails -> notes say so, pledge stays n/a instead of 0
nse_client._http_json = lambda p, a: hold_xb if "share-holdings" in p else {"comNameList": [], "data": []}
nse_client._http_text = lambda url: (_ for _ in ()).throw(RuntimeError("blocked"))
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
nse_client._bulk_pledge = None
g = ownership.get("WOCK", None, True)
assert g["pledged_pct"] is None and "NSE XBRL" in g["ownership_notes"], g
nse_client._http_text = lambda url: WOCK
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
g = ownership.get("WOCK", None, True)
assert g["pledged_pct"] == 9.97 and g["pledge_src"].startswith("NSE shareholding filing"), g
print("pledge ok: real Wockhardt XBRL -> 9.97% of promoter holding (4.92% of all shares); flag false -> 0; missing -> n/a; stale NSE record ignored")

# ------------------------------------------------------------------ 1-quarter changes: promoter holding and pledged %
ow_a = ownership.compute(hold_w, [], None, dict(px, asof="2026-09-30"), dict(parse_pledge_prev := nse_client.parse_xbrl_pledge(
    xbrl("true", ctx("ShareholdingOfPromoterAndPromoterGroup_ContextI", 7000000, 0.0750))), asof="2026-06-30"))
assert ow_a["promoter_change_1q"] == round(49.3 - 49.1, 2) == 0.2, ow_a["promoter_change_1q"]
assert ow_a["pledged_pct"] == 9.97 and ow_a["pledged_change_1q"] == round(9.97 - 7.5, 2) == 2.47, ow_a["pledged_change_1q"]
# previous filing not a consecutive quarter (gap of a year) -> no change claimed
ow_b = ownership.compute(hold_w, [], None, dict(px, asof="2026-09-30"), dict(parse_pledge_prev, asof="2025-09-30"))
assert ow_b["pledged_change_1q"] is None
# previous filing missing / without a figure -> None, never 0
assert ownership.compute(hold_w, [], None, dict(px, asof="2026-09-30"), None)["pledged_change_1q"] is None
assert ownership.compute(hold_w, [], None, dict(px, asof="2026-09-30"), dict(parse_pledge_prev, pledged_pct=None, asof="2026-06-30"))["pledged_change_1q"] is None
# latest figure NOT from XBRL (NSE pledge API) -> no cross-source comparison
assert ownership.compute(hold_w, rp, None, None, dict(parse_pledge_prev, asof="2026-06-30"))["pledged_change_1q"] is None
# a genuine no-change is 0.0, and a drop is negative
same = dict(px, asof="2026-09-30")
assert ownership.compute(hold_w, [], None, same, dict(px, asof="2026-06-30"))["pledged_change_1q"] == 0.0
assert ownership.compute(hold_w, [], None, dict(parse_pledge_prev, asof="2026-09-30"), dict(px, asof="2026-06-30"))["pledged_change_1q"] == round(7.5 - 9.97, 2)
# single quarter of promoter history -> no 1q change
assert ownership.compute(hold_w[:1], [], None, None)["promoter_change_1q"] is None

# xbrl_pledge(back=1): picks the previous quarter's link, separate cache file, latest still cached separately
hold_two = [{"symbol": "WOCK", "date": "30-SEP-2026", "pr_and_prgrp": "49.3", "public_val": "50.7", "xbrl": "corporate/xbrl/NEW.xml"},
            {"symbol": "WOCK", "date": "30-JUN-2026", "pr_and_prgrp": "49.1", "public_val": "50.9", "xbrl": "corporate/xbrl/OLD.xml"}]
PREV = xbrl("true", ctx("ShareholdingOfPromoterAndPromoterGroup_ContextI", 7000000, 0.0750) + ctx("ShareholdingPattern_ContextI", 7000000, 0.0370))
nse_client._http_json = lambda p, a: hold_two
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
fetched = []
nse_client._http_text = lambda url: (fetched.append(url), WOCK if url.endswith("NEW.xml") else PREV)[1]
cur, prv = nse_client.xbrl_pledge("WOCK"), nse_client.xbrl_pledge("WOCK", back=1)
assert cur["pledged_pct"] == 9.97 and cur["asof"] == "2026-09-30" and prv["pledged_pct"] == 7.5 and prv["asof"] == "2026-06-30"
assert fetched == ["https://nsearchives.nseindia.com/corporate/xbrl/NEW.xml", "https://nsearchives.nseindia.com/corporate/xbrl/OLD.xml"], fetched
nse_client.xbrl_pledge("WOCK"); nse_client.xbrl_pledge("WOCK", back=1); assert len(fetched) == 2      # both served from their own caches
assert nse_client.xbrl_pledge("WOCK", back=5) is None                                                 # not enough history
# end to end through ownership.get()
nse_client._http_json = lambda p, a: hold_two if "share-holdings" in p else {"comNameList": [], "data": []}
g2 = ownership.get("WOCK", None, True)
assert g2["pledged_change_1q"] == 2.47 and g2["promoter_change_1q"] == 0.2, g2
# previous-quarter download fails -> latest values survive, change is n/a, reason recorded
for f_ in os.listdir(nse_client.CACHE_DIR): os.remove(os.path.join(nse_client.CACHE_DIR, f_))
nse_client._http_text = lambda url: WOCK if url.endswith("NEW.xml") else (_ for _ in ()).throw(RuntimeError("blocked"))
g3 = ownership.get("WOCK", None, True)
assert g3["pledged_pct"] == 9.97 and g3["pledged_change_1q"] is None and "previous quarter" in g3["ownership_notes"], g3
print("1-quarter changes ok: promoter +0.2 pp, pledged +2.47 pp; None for non-consecutive, missing, mixed-source; failures isolated")

print("\nAll source/section-4 checks passed.")
