"""Quick smoke-test for the 976-tuna.com parser before running full backfill."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests
from src.scrape_ocla import parse_page, LANDINGS

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
s = requests.Session()
hdrs = {"User-Agent": UA}

tests = [
    ("22nd Street Landing", 8, 2025),
    ("Dana Wharf Sportfishing", 8, 2025),
    ("Oceanside Sea Center", 7, 2025),
    ("Channel Islands Sportfishing", 8, 2025),
]

for lname, month, year in tests:
    rec = next(l for l in LANDINGS if l[0] == lname)
    name, lid, slug, region = rec
    url = f"https://www.976-tuna.com/landing/{lid}/{slug}/counts?m={month}&y={year}"
    r = s.get(url, headers=hdrs, timeout=20)
    trips = parse_page(r.text, name, url)
    print(f"\n{lname} {year}-{month:02d}: {len(trips)} trips parsed (region={region})")
    for t in trips[:4]:
        print(f"  {t['date']}  {t['boat'][:22]:22s}  {t['trip_length']:12s}  "
              f"ang={t['anglers']:3d}  bf={t['bluefin']}  yt={t['yellowtail']}  "
              f"trophy={t['trophy_count']}")
