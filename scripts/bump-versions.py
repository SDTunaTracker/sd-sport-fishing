#!/usr/bin/env python3
"""
Auto-bump cache-bust version strings in web/index.html for any JSX or CSS
file that was modified today.

Usage:  python scripts/bump-versions.py
        python scripts/bump-versions.py --dry-run

The version format is ?v=YYYYMMDD-N where N starts at 1 and increments if
the date already exists in the file.
"""
import os, re, sys
from datetime import date

dry_run = "--dry-run" in sys.argv

here  = os.path.dirname(os.path.abspath(__file__))
web   = os.path.normpath(os.path.join(here, "..", "web"))
html  = os.path.join(web, "index.html")
today = date.today().strftime("%Y%m%d")

text = open(html, encoding="utf-8").read()
original = text
today_mtime = date.today()


def file_modified_today(filename):
    path = os.path.join(web, filename)
    if not os.path.exists(path):
        return False
    mtime = date.fromtimestamp(os.path.getmtime(path))
    return mtime == today_mtime


def next_version(current_tag, base_date):
    """Given existing ?v=YYYYMMDD-N, return ?v=BASE_DATE-(N+1). If no suffix, start at -1."""
    m = re.match(r'\?v=\d{8}-(\d+)', current_tag)
    n = int(m.group(1)) + 1 if m else 1
    return f"?v={base_date}-{n}"


bumped = []

# Match: src="filename.jsx?v=..." or src="dist/filename.js?v=..." or href="filename.css?v=..."
for m in re.finditer(r'(?:src|href)="(?:dist/)?([^"?]+\.(jsx|js|css))\?v=([^"]+)"', text):
    full_match = m.group(0)
    filename   = os.path.basename(m.group(1))
    old_ver    = m.group(3)

    # Check if the source file was modified today
    source = filename.replace(".js", ".jsx") if filename.endswith(".js") else filename
    if not file_modified_today(source):
        continue

    # Already stamped with today? bump the counter. Otherwise reset to today-1.
    if old_ver.startswith(today):
        new_tag = next_version(f"?v={old_ver}", today)
    else:
        new_tag = f"?v={today}-1"

    old_tag = f"?v={old_ver}"
    new_full = full_match.replace(old_tag, new_tag, 1)
    text = text.replace(full_match, new_full, 1)
    bumped.append(f"  {source}: ?v={old_ver} → {new_tag[3:]}")

if bumped:
    print("Bumped versions:")
    for line in bumped:
        print(line)
    if not dry_run:
        open(html, "w", encoding="utf-8").write(text)
        print(f"Wrote {html}")
else:
    print("No files modified today — nothing to bump.")
