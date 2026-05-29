#!/usr/bin/env python3
"""
Verify that all JSX files in web/ are referenced in web/index.html,
and that version strings are recent (within 7 days).

Run before committing or as part of CI pre-flight.
Exit code 0 = all good. Exit code 1 = problems found.
"""
import os, re, sys
from datetime import date, timedelta

here = os.path.dirname(os.path.abspath(__file__))
web  = os.path.normpath(os.path.join(here, "..", "web"))
html = os.path.join(web, "index.html")

text = open(html, encoding="utf-8").read()

# ── 1. Every .jsx in web/ must appear in index.html ──────────────────────────
jsx_files = [f for f in os.listdir(web) if f.endswith(".jsx")]
missing = []
for f in sorted(jsx_files):
    base = f[:-4]  # strip .jsx
    # Match type="text/babel" src="name.jsx  OR  src="dist/name.js
    if not re.search(rf'src="(?:dist/)?{re.escape(base)}\.jsx?', text):
        missing.append(f)

# ── 2. Version strings must be ≤ 7 days old ──────────────────────────────────
stale = []
cutoff = date.today() - timedelta(days=7)
# Matches ?v=YYYYMMDD or ?v=YYYYMMDD-N
for m in re.finditer(r'\?v=(\d{8})(?:-\d+)?', text):
    raw = m.group(1)
    try:
        d = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        if d < cutoff:
            stale.append((raw, m.group(0)))
    except ValueError:
        pass  # non-date version string — skip

# ── 3. No file in web/ may exceed 24 MiB (Cloudflare Pages hard limit: 25 MiB) ─
CLOUDFLARE_LIMIT_MB = 24.0
oversized = []
for f in os.listdir(web):
    fpath = os.path.join(web, f)
    if not os.path.isfile(fpath):
        continue
    size_mb = os.path.getsize(fpath) / (1024 * 1024)
    if size_mb > CLOUDFLARE_LIMIT_MB:
        oversized.append((f, size_mb))

# ── Report ────────────────────────────────────────────────────────────────────
fail = False

if oversized:
    print(f"OVERSIZED files (> {CLOUDFLARE_LIMIT_MB} MiB — Cloudflare Pages limit is 25 MiB):")
    for fname, size_mb in sorted(oversized, key=lambda x: -x[1]):
        print(f"  web/{fname}  {size_mb:.1f} MiB")
    print("  Re-run: python -m src.main --export-only")
    fail = True

if missing:
    print("MISSING from index.html:")
    for f in missing:
        print(f"  {f}")
    fail = True

if stale:
    print("STALE version strings (> 7 days old):")
    for raw, tag in stale:
        print(f"  {tag}  (date: {raw})")
    fail = True

if not fail:
    print(f"OK: all {len(jsx_files)} JSX files referenced, versions are fresh.")

sys.exit(1 if fail else 0)
