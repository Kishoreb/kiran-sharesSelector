#!/usr/bin/env python3
"""
Download the latest shareholding-pattern XBRL filing from NSE for a few symbols and list its pledge-related
tags. NSE's shareholding JSON has no pledge fields, but each record links to an XBRL file that does carry the
pledge detail. Run this once so the tag names can be read from real data:

    python fetch_xbrl_sample.py VEDL LEMONTREE TITAN
    -> saves dump_xbrl/<SYMBOL>_<date>.xml and prints the pledge/encumbrance tags with their values
"""
import os
import re
import sys
from datetime import date

import nse_client as nc


def main():
    syms = [s.upper() for s in sys.argv[1:]] or ["VEDL"]
    os.makedirs("dump_xbrl", exist_ok=True)
    for sym in syms:
        try:
            rows = nc._rows(nc.fetch("shareholding", sym))
        except Exception as e:
            print(sym + ": shareholding fetch failed: " + str(e)[:150])
            continue
        if not rows:
            print(sym + ": no shareholding records")
            continue
        rec = max(rows, key=lambda d: nc.parse_date(d.get("date")) or date.min)
        url = str(rec.get("xbrl") or "")
        print("%s  period %s  xbrl field: %r" % (sym, rec.get("date"), url[:160]))
        if not url:
            continue
        if not url.startswith("http"):
            url = "https://nsearchives.nseindia.com/" + url.lstrip("/")
        try:
            r = nc._sess().get(url, timeout=40)
        except Exception as e:
            print("   download failed: " + str(e)[:150])
            continue
        print("   HTTP %s, %s bytes, content-type %s" % (r.status_code, len(r.content), r.headers.get("content-type")))
        path = os.path.join("dump_xbrl", "%s_%s.xml" % (sym, str(rec.get("date")).replace(" ", "")))
        with open(path, "wb") as f:
            f.write(r.content)
        text = r.content.decode("utf-8", errors="replace")
        pairs = re.findall(r"<([A-Za-z0-9_.:-]*(?:[Pp]ledg|[Ee]ncumb)[A-Za-z0-9_.:-]*)\b[^>]*>([^<]*)<", text)
        seen = []
        for tag, val in pairs:
            if (tag, val.strip()) not in seen:
                seen.append((tag, val.strip()))
        print("   %d pledge/encumbrance tags, %d distinct (tag, value) pairs; first 25:" % (len(pairs), len(seen)))
        for tag, val in seen[:25]:
            print("      %-80s %s" % (tag, val[:40]))
        print("   saved " + path)


if __name__ == "__main__":
    main()
