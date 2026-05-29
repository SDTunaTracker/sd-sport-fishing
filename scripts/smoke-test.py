#!/usr/bin/env python3
"""
Post-deploy smoke test for thetunatracker.com.

Fetches key URLs and verifies critical content is present.
Exit code 0 = all good. Exit code 1 = failures found.

Usage:
    python scripts/smoke-test.py
    python scripts/smoke-test.py --base-url https://sdtunatracker.github.io
"""
import sys, urllib.request, urllib.error

base = "https://thetunatracker.com"
for arg in sys.argv[1:]:
    if arg.startswith("--base-url="):
        base = arg.split("=", 1)[1]
    elif not arg.startswith("--") and arg.startswith("http"):
        base = arg

CHECKS = [
    (f"{base}/",             "Tuna Tracker",  "Homepage missing brand name"),
    (f"{base}/",             "hero-sunrise",  "Homepage missing hero CSS class"),
    (f"{base}/data.js",      "window.SD",     "data.js missing window.SD export"),
    (f"{base}/charts.jsx",   "ChartsView",    "charts.jsx missing ChartsView function"),
    (f"{base}/chatbot.jsx",  "Co-Captain",    "chatbot.jsx missing Co-Captain text"),
]

fail = False
for url, needle, label in CHECKS:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
        if needle in body:
            print(f"  OK  {url}")
        else:
            print(f"  FAIL  {url}  — {label}")
            fail = True
    except urllib.error.HTTPError as e:
        print(f"  FAIL  {url}  — HTTP {e.code}")
        fail = True
    except Exception as e:
        print(f"  FAIL  {url}  — {e}")
        fail = True

sys.exit(1 if fail else 0)
