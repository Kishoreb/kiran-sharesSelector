#!/usr/bin/env python3
"""
Summarise a --debug-dump folder so that parser problems can be diagnosed from one short paste.

    python diagnose_dump.py dump                  # one line per file + detail for a few
    python diagnose_dump.py dump VMART POLYCAB    # also full detail for these symbols

For each saved screener.in page it reports which sections / tables the parser found and how many
annual columns the P&L has; for each NSE response it reports the JSON shape, the field names of the
first record and what the tolerant parser extracted from it.
"""

import glob
import json
import os
import re
import sys

import nse_client as nc
import screener_in as si


def squeeze(text):
    return re.sub(r"\s+", " ", text).strip()


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def screener_line(path, detail):
    html = read(path)
    raw = si.parse_page(html)
    sections = re.findall(r'<section[^>]*\bid=["\']([^"\']+)["\']', html)
    pl = si.annual_only(raw["pl"]) if raw["pl"] else None
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    line = (f"{os.path.basename(path):<34} {len(html):>7}B  pl_cols={len(pl['cols']) if pl else 0:<3} "
            f"bs={'y' if raw['bs'] else 'n'} ratios={'y' if raw['ratios'] else 'n'} holding={'y' if raw['holding'] else 'n'} "
            f"blocks={len(raw['ranges'])} top={len(raw['top'])}")
    print(line)
    if detail or not pl:
        print("    title: " + (squeeze(title.group(1))[:90] if title else "-"))
        print(f"    sections: {sections}")
        if pl:
            print(f"    P&L columns: {pl['cols']}")
            print(f"    P&L rows: {list(pl['rows'])[:14]}")
        print(f"    growth blocks: {list(raw['ranges'])}")
        print(f"    top ratios: {list(raw['top'])}")
        if not pl:                           # parser found no statement table: show what the section looks like
            for t in si.tables_in_section(html, "profit-loss")[:6]:
                first = t["rows"][0] if t["rows"] else []
                print("    table in profit-loss: head=" + str([squeeze(c)[:14] for c in (t["head"] or [])[:5]])
                      + " rows=" + str(len(t["rows"])) + " class=" + repr(t["cls"][:30])
                      + " first_row=" + str([squeeze(c)[:14] for c in first[:4]]))
            i = html.find('id="profit-loss"')
            if i >= 0:
                print("    raw start of section: " + squeeze(html[i:i + 700]))
        hits = [m.start() for m in re.finditer(r"pledg", html, re.I)][:3]
        for h in hits:
            ctx = squeeze(re.sub(r"<[^>]+>", " ", html[max(0, h - 70):h + 90]))
            print("    'pledg' context: ..." + ctx + "...")


def nse_line(path, detail):
    name = os.path.basename(path)
    kind = re.match(r"nse_([a-z]+)_", name).group(1)
    js = json.loads(read(path))
    rows = nc._rows(js)
    parsed = {"shareholding": nc.parse_shareholding, "pledge": nc.parse_pledge,
              "announcements": lambda j: nc.parse_announcements(j, 3650)}[kind](js)
    shape = f"list[{len(js)}]" if isinstance(js, list) else f"dict keys={list(js)[:6]}"
    print(f"{name:<34} {shape:<28} records={len(rows):<4} parsed={len(parsed)}")
    if detail or (rows and not parsed) or not rows:
        print(f"    raw (first 300 chars): {json.dumps(js)[:300]}")
        if rows:
            print(f"    first record keys: {list(rows[0])}")
            print(f"    first record: {json.dumps(rows[0])[:400]}")
        if parsed:
            print(f"    first parsed: {parsed[0]}")


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "dump"
    want = {s.upper() for s in sys.argv[2:]}
    files = sorted(glob.glob(os.path.join(folder, "*")))
    if not files:
        sys.exit(f"nothing in {folder}")
    shown = {"html": 0, "shareholding": 0, "pledge": 0, "announcements": 0}
    for p in files:
        n = os.path.basename(p)
        sym = re.sub(r"^(screener_|nse_[a-z]+_)|(_consolidated|_standalone)?\.(html|json)$", "", n).upper()
        try:
            if n.startswith("screener_") and n.endswith(".html"):
                shown["html"] += 1
                screener_line(p, detail=sym in want or shown["html"] <= 2)
            elif n.startswith("nse_") and n.endswith(".json"):
                kind = re.match(r"nse_([a-z]+)_", n).group(1)
                shown[kind] += 1
                nse_line(p, detail=sym in want or shown[kind] <= 1)
        except Exception as e:
            print(f"{n}: could not analyse ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
