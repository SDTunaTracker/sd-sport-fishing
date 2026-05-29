#!/usr/bin/env python3
"""
Verify that all JSX files in web/ are referenced in web/index.html,
that version strings are recent (within 7 days), and that no file
exceeds the Cloudflare Pages 25 MiB per-file limit.

Run before committing or as part of CI pre-flight.
Exit code 0 = all good. Exit code 1 = problems found.
"""
import os, re, sys
from datetime import date, timedelta
from pathlib import Path

here = os.path.dirname(os.path.abspath(__file__))
web  = Path(os.path.normpath(os.path.join(here, "..", "web")))
html = web / "index.html"

text = html.read_text(encoding="utf-8")

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

# ── 3. File size guard — Cloudflare Pages hard limit is 25 MiB per file ──────
WARN_MB = 20.0
FAIL_MB = 24.0
oversized  = []  # will block commit
size_warns = []  # advisory only

for fpath in sorted(web.rglob("*")):
    if not fpath.is_file():
        continue
    size_mb = fpath.stat().st_size / (1024 * 1024)
    rel = fpath.relative_to(web.parent)
    if size_mb >= FAIL_MB:
        oversized.append((rel, size_mb))
    elif size_mb >= WARN_MB:
        size_warns.append((rel, size_mb))

# ── Report ────────────────────────────────────────────────────────────────────
fail = False

if size_warns:
    print(f"File size warnings (> {WARN_MB:.0f} MiB — approaching 25 MiB Cloudflare limit):")
    for rel, mb in size_warns:
        print(f"  {rel}  {mb:.1f} MiB")

if oversized:
    print(f"OVERSIZED files (> {FAIL_MB:.0f} MiB — will fail Cloudflare Pages deploy):")
    for rel, mb in oversized:
        print(f"  {rel}  {mb:.1f} MiB")
    print("  Fix: python -m src.main --export-only  (re-runs export reductions)")
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
    print(f"OK: all {len(jsx_files)} JSX files referenced, versions fresh, files within size limits.")

sys.exit(1 if fail else 0)
