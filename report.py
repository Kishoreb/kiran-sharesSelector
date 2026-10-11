"""
Self-contained HTML validation report: inline SVG charts and tables, no
JavaScript, no external files or fonts -- opens fine on an air-gapped machine.
"""

import html
from datetime import datetime
from typing import List, Optional, Sequence

import numpy as np

CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--accent:#2563eb;--bad:#cf222e;--good:#1a7f37;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--accent:#58a6ff;--bad:#ff7b72;--good:#3fb950;--warn:#d29922}}
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg);max-width:980px;margin:0 auto;padding:24px 16px;line-height:1.5}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.15rem;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.muted{color:var(--muted);font-size:.9rem}.verdict{border-left:4px solid var(--accent);padding:6px 12px;margin:8px 0;background:rgba(127,127,127,.08)}
table{border-collapse:collapse;width:100%;font-size:.88rem;margin:8px 0}th,td{border:1px solid var(--line);padding:4px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}th{background:rgba(127,127,127,.1)}
.scroll{overflow-x:auto}svg{width:100%;height:auto;color:var(--fg)}.note{font-size:.85rem;color:var(--muted)}
.pos{color:var(--good)}.neg{color:var(--bad)}
"""


def _fmt(v, nd=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        if v == float("inf"):
            return "inf"
        return f"{v:,.{nd}f}"
    return html.escape(str(v))


def table(headers: Sequence[str], rows: Sequence[Sequence], signed_cols: Sequence[int] = ()) -> str:
    out = ['<div class="scroll"><table><tr>' + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr>"]
    for r in rows:
        tds = []
        for i, v in enumerate(r):
            cls = ""
            if i in signed_cols and isinstance(v, (int, float)) and v is not None:
                cls = ' class="pos"' if v > 0 else ' class="neg"' if v < 0 else ""
            tds.append(f"<td{cls}>{_fmt(v)}</td>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    out.append("</table></div>")
    return "".join(out)


def svg_series(values: List[float], labels: List[str], height: int = 240, color: str = "#2563eb",
               fill_to: Optional[float] = None, vline_index: Optional[int] = None,
               vline_label: str = "", y_fmt: str = "{:,.0f}") -> str:
    width, pl, pr, pt, pb = 900, 72, 14, 12, 26
    n = len(values)
    if n < 2:
        return "<p class='note'>Not enough data to chart.</p>"
    lo, hi = min(values), max(values)
    if fill_to is not None:
        lo, hi = min(lo, fill_to), max(hi, fill_to)
    if hi == lo:
        hi = lo + 1
    X = lambda i: pl + (width - pl - pr) * i / (n - 1)
    Y = lambda v: pt + (height - pt - pb) * (1 - (v - lo) / (hi - lo))
    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        y = Y(v)
        parts.append(f'<line x1="{pl}" x2="{width - pr}" y1="{y:.1f}" y2="{y:.1f}" stroke="currentColor" stroke-opacity=".15"/>')
        parts.append(f'<text x="{pl - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="currentColor" fill-opacity=".7">{y_fmt.format(v)}</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(values))
    if fill_to is not None:
        base = Y(fill_to)
        parts.append(f'<polygon points="{X(0):.1f},{base:.1f} {pts} {X(n - 1):.1f},{base:.1f}" fill="{color}" fill-opacity=".25"/>')
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"/>')
    for idx in (0, n // 2, n - 1):
        anchor = "start" if idx == 0 else "end" if idx == n - 1 else "middle"
        parts.append(f'<text x="{X(idx):.1f}" y="{height - 8}" text-anchor="{anchor}" font-size="11" fill="currentColor" fill-opacity=".7">{html.escape(labels[idx])}</text>')
    if vline_index is not None and 0 <= vline_index < n:
        x = X(vline_index)
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{pt}" y2="{height - pb}" stroke="#d29922" stroke-dasharray="5 4"/>')
        parts.append(f'<text x="{x + 4:.1f}" y="{pt + 11}" font-size="11" fill="#d29922">{html.escape(vline_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_hist(samples: List[float], marker: Optional[float] = None, bins: int = 30, height: int = 200,
             x_fmt: str = "{:.0f}%") -> str:
    width, pl, pr, pt, pb = 900, 40, 14, 12, 26
    counts, edges = np.histogram(np.asarray(samples, float), bins=bins)
    top = max(counts.max(), 1)
    bw = (width - pl - pr) / bins
    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img">']
    for i, c in enumerate(counts):
        h = (height - pt - pb) * c / top
        parts.append(f'<rect x="{pl + i * bw + 1:.1f}" y="{height - pb - h:.1f}" width="{bw - 2:.1f}" height="{h:.1f}" fill="#2563eb" fill-opacity=".7"/>')
    lo, hi = edges[0], edges[-1]
    for v, anchor in ((lo, "start"), ((lo + hi) / 2, "middle"), (hi, "end")):
        x = pl + (width - pl - pr) * (v - lo) / (hi - lo if hi > lo else 1)
        parts.append(f'<text x="{x:.1f}" y="{height - 8}" text-anchor="{anchor}" font-size="11" fill="currentColor" fill-opacity=".7">{x_fmt.format(v)}</text>')
    if marker is not None and hi > lo and lo <= marker <= hi:
        x = pl + (width - pl - pr) * (marker - lo) / (hi - lo)
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{pt}" y2="{height - pb}" stroke="#cf222e" stroke-width="2"/>')
        parts.append(f'<text x="{x + 4:.1f}" y="{pt + 11}" font-size="11" fill="#cf222e">your actual</text>')
    parts.append("</svg>")
    return "".join(parts)


def _stat_row(label, s):
    return [label, s["trades"], s["win_rate_pct"], s["avg_r"], s["median_r"], s["expectancy"], s["net_pnl"], s["profit_factor"]]


STAT_HEADERS = ["", "Trades", "Win %", "Avg R", "Median R", "Expectancy Rs", "Net P&L Rs", "Profit factor"]


def build_report(path: str, ctx: dict) -> None:
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>Backtest validation</title><style>{CSS}</style></head><body>"]
    h.append("<h1>Backtest validation report</h1>")
    h.append(f"<div class='muted'>Generated {datetime.now():%Y-%m-%d %H:%M} &middot; " + html.escape(ctx["meta"]) + "</div>")
    h.append("<p class='note'>A rule-checking tool, not investment advice. Survivorship bias (today's index list) "
             "still applies to everything below, and a backtest is not a promise of future performance.</p>")

    # equity + drawdown
    eq = ctx["equity_curve"]
    vals, labels = [p["equity"] for p in eq], [p["date"] for p in eq]
    peak, dd = vals[0], []
    for v in vals:
        peak = max(peak, v)
        dd.append(-(peak - v) / peak * 100 if peak else 0)
    cut_idx = None
    if ctx.get("split"):
        cut_idx = next((i for i, d in enumerate(labels) if d >= ctx["split"]["cut"]), None)
    h.append("<h2>Equity curve</h2>")
    h.append(svg_series(vals, labels, vline_index=cut_idx, vline_label="in/out-of-sample split"))
    h.append("<h2>Drawdown (daily, mark-to-market)</h2>")
    h.append(svg_series(dd, labels, color="#cf222e", fill_to=0.0, y_fmt="{:.1f}%"))
    h.append(table(["Metric", "Value"], [[k, v if not isinstance(v, dict) else ", ".join(f"{a}: {b}" for a, b in v.items())]
                                          for k, v in ctx["metrics"].items()]))

    sp = ctx.get("split")
    if sp:
        h.append(f"<h2>1. In-sample vs out-of-sample (split at {html.escape(sp['cut'])})</h2>")
        h.append(table(STAT_HEADERS + ["Max DD %"],
                       [_stat_row("In-sample", sp["in_sample"]) + [sp["in_sample"]["max_dd_pct"]],
                        _stat_row("Out-of-sample", sp["out_of_sample"]) + [sp["out_of_sample"]["max_dd_pct"]]],
                       signed_cols=(3, 4, 6)))
        h.append(f"<div class='verdict'>{html.escape(sp['verdict'])}</div>")

    if ctx.get("yearly"):
        h.append("<h2>2. By calendar year (trades grouped by entry date)</h2>")
        h.append(table(STAT_HEADERS, [_stat_row(r["period"], r) for r in ctx["yearly"]], signed_cols=(3, 4, 6)))
    if ctx.get("regime"):
        h.append("<h2>3. By market regime at entry</h2>")
        h.append(table(STAT_HEADERS, [_stat_row(r["period"], r) for r in ctx["regime"]], signed_cols=(3, 4, 6)))
        h.append("<p class='note'>If the regime filter was on during the run, the 'below' group will be empty or tiny by design.</p>")

    mc = ctx.get("mc")
    h.append("<h2>4. Monte Carlo: how bad could the drawdown have been?</h2>")
    if not mc:
        h.append("<p class='note'>Not run.</p>")
    elif mc["too_few"]:
        h.append(f"<div class='verdict'>Only {mc['n']} usable trades; need {mc['min']}+ for a meaningful simulation.</div>")
    else:
        h.append(table(["Measure", "Median", "95th pct (bad luck)", "99th pct"],
                       [["Max drawdown, trades reshuffled %", mc["shuffle_dd"]["p50"], mc["shuffle_dd"]["p95"], mc["shuffle_dd"]["p99"]],
                        ["Max drawdown, trades resampled %", mc["bootstrap_dd"]["p50"], mc["bootstrap_dd"]["p95"], mc["bootstrap_dd"]["p99"]]]))
        h.append(table(["Resampled final return %", "5th pct", "Median", "95th pct"],
                       [["", mc["bootstrap_return"]["p5"], mc["bootstrap_return"]["p50"], mc["bootstrap_return"]["p95"]]]))
        h.append(svg_hist(mc["dd_samples"], marker=mc["observed_trade_dd_pct"]))
        h.append(f"<p>{mc['sims']:,} simulations over {mc['n']} trades. Chance of finishing below the start: "
                 f"<b>{mc['prob_loss_pct']}%</b>. Chance of a drawdown over 20%: <b>{mc['prob_dd_over_20_pct']}%</b>.</p>")
        h.append("<p class='note'>Plan for the 95th-percentile drawdown, not the one that happened. Drawdown here is "
                 "trade-to-trade (not daily mark-to-market) and treats overlapping trades as sequential, so it is an approximation.</p>")

    if ctx.get("sweep_rows"):
        sm = ctx["sweep_summary"]
        h.append("<h2>5. Parameter sensitivity</h2>")
        names = list(ctx["sweep_rows"][0]["params"])
        rows = [[*[r["params"][n] for n in names], r["trades"], r["win_rate_pct"], r["avg_r"], r["net_pnl"],
                 r["profit_factor"], r["max_dd_pct"], r["return_pct"]]
                for r in sorted(ctx["sweep_rows"], key=lambda r: (r["avg_r"] is None, -(r["avg_r"] or 0)))]
        h.append(table(names + ["Trades", "Win %", "Avg R", "Net P&L Rs", "PF", "Max DD %", "Return %"], rows,
                       signed_cols=(len(names) + 2, len(names) + 3)))
        if sm.get("valid"):
            h.append(f"<p>{sm['profitable']} of {sm['valid']} parameter sets (with enough trades) were profitable "
                     f"({sm['share_profitable_pct']}%). Avg R: median {sm['median_avg_r']}, best {sm['best_avg_r']}, worst {sm['worst_avg_r']}.</p>")
        h.append(f"<div class='verdict'>{html.escape(sm['verdict'])}</div>")
        if sm.get("inert_params"):
            h.append("<div class='verdict'>No effect: changing " + html.escape(", ".join(sm["inert_params"])) +
                     " produced identical trades at every value. That parameter is probably not doing anything in the strategy logic.</div>")
        h.append("<p class='note'>The best row is the most likely to be luck: you picked it BECAUSE it was the best of many. "
                 "Look at whether its neighbours are also good.</p>")

    wf = ctx.get("wf")
    if wf:
        h.append("<h2>6. Walk-forward</h2>")
        rows = [[w["train"], w["test"], str(w["chosen"]), w["train_avg_r"], w["test_trades"], w["test_avg_r"],
                 w["test_net_pnl"], w["base_test_trades"], w["base_test_avg_r"]] for w in wf["windows"]]
        h.append(table(["Train window", "Test window", "Chosen params", "Train avg R", "Test trades", "Test avg R",
                        "Test net Rs", "Base trades", "Base avg R"], rows, signed_cols=(5, 6)))
        h.append(table(STAT_HEADERS, [_stat_row("Walk-forward (out-of-sample, stitched)", wf["oos"]),
                                      _stat_row("Fixed base params, same windows", wf["base_oos"])], signed_cols=(3, 4, 6)))
        if wf["efficiency"] is not None:
            h.append(f"<p>Walk-forward efficiency (out-of-sample avg R / training avg R): <b>{wf['efficiency']}</b>. "
                     "Near or above 1 is good; well below ~0.5 suggests the in-window results were mostly fit.</p>")
        h.append(f"<div class='verdict'>{html.escape(wf['verdict'])}</div>")

    if ctx.get("ablation"):
        h.append("<h2>7. What is driving the result? (one feature switched off at a time)</h2>")
        h.append(table(["Variant", "Trades", "Win %", "Avg R", "Median R", "Net P&L Rs", "PF", "Max DD %", "Return %"],
                       [[r["label"], r["trades"], r["win_rate_pct"], r["avg_r"], r["median_r"], r["net_pnl"],
                         r["profit_factor"], r["max_dd_pct"], r["return_pct"]] for r in ctx["ablation"]],
                       signed_cols=(3, 4, 5)))
        h.append("<p class='note'>If the result is only positive with costs off, or only with one filter on, "
                 "that feature (not the strategy) is carrying it. Compare each row with 'As configured'.</p>")

    for note in ctx.get("notes", []):
        h.append(f"<p class='note'>{html.escape(note)}</p>")
    h.append("</body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(h))
