#!/usr/bin/env python3
"""
Post-deploy smoke test for thetunatracker.com (Cloudflare Pages).

Tests the real production URL with a browser User-Agent so Cloudflare
bot protection doesn't 403 the request.

Exit code 0 = all good. Exit code 1 = failures found.

Usage:
    python scripts/smoke-test.py
    python scripts/smoke-test.py --base-url=https://sdtunatracker.github.io/sd-sport-fishing
    python scripts/smoke-test.py --check-commit   # also verify HEAD commit is live
"""
import re, subprocess, sys, urllib.error, urllib.request

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent":      BROWSER_UA,
    "Cache-Control":   "no-cache",
    "Accept-Language": "en-US,en;q=0.9",
}

base         = "https://thetunatracker.com"
check_commit = False
for arg in sys.argv[1:]:
    if arg.startswith("--base-url="):
        base = arg.split("=", 1)[1]
    elif arg == "--check-commit":
        check_commit = True
    elif not arg.startswith("--") and arg.startswith("http"):
        base = arg


def get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


# ── Content checks ────────────────────────────────────────────────────────────
CHECKS = [
    (f"{base}/",            "Tuna Tracker",  "Homepage missing brand name"),
    (f"{base}/data.js",     "window.SD",     "data.js missing window.SD export"),
    (f"{base}/charts.jsx",  "ChartsView",    "charts.jsx missing ChartsView function"),
    (f"{base}/chatbot.jsx", "Co-Captain",    "chatbot.jsx missing Co-Captain text"),
]

fail = False
for url, needle, label in CHECKS:
    status, body = get(url)
    if status != 200:
        print(f"  FAIL  {url}  — HTTP {status}")
        fail = True
    elif needle in body:
        print(f"  OK    {url}")
    else:
        print(f"  FAIL  {url}  — {label}")
        fail = True

# ── Optional: verify the deployed commit matches git HEAD ─────────────────────
if check_commit:
    print()
    try:
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        head_sha = None

    _, html = get(f"{base}/")
    m = re.search(r'build-commit["\s]+content="([^"]+)"', html)
    deployed_sha = m.group(1) if m else None

    if not deployed_sha:
        # Cloudflare Pages doesn't run build-prod.py so tag won't exist there
        print(f"  WARN  build-commit meta not found at {base}")
        print(f"        (expected if Cloudflare Pages has no build step)")
    elif head_sha and not deployed_sha.startswith(head_sha):
        print(f"  FAIL  deployed commit {deployed_sha} != HEAD {head_sha}")
        fail = True
    else:
        print(f"  OK    build-commit: {deployed_sha}")

sys.exit(1 if fail else 0)
