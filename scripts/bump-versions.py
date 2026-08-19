#!/usr/bin/env python3
"""
Auto-bump cache-bust version strings in web/index.html for any JSX/JS/CSS
source file that is in the current commit (staged) or, as a fallback,
modified today. Using the staged-files signal makes this reliable when
run from the pre-commit hook, where file mtimes can race with the hook.

Usage:  python scripts/bump-versions.py
        python scripts/bump-versions.py --dry-run
        python scripts/bump-versions.py --all      # bump every referenced file

The version format is ?v=YYYYMMDD-N where N starts at 1 and increments if
the date already exists in the file.
"""
import os, re, subprocess, sys
from datetime import date

dry_run = "--dry-run" in sys.argv
force_all = "--all" in sys.argv

here  = os.path.dirname(os.path.abspath(__file__))
repo  = os.path.normpath(os.path.join(here, ".."))
web   = os.path.join(repo, "web")
html  = os.path.join(web, "index.html")
today = date.today().strftime("%Y%m%d")

text = open(html, encoding="utf-8").read()
today_date = date.today()


def staged_web_files():
    """Return set of 'basename.ext' of every staged file under web/.
    Silent no-op if git isn't available or we're outside a repo."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    result = set()
    for line in out.splitlines():
        line = line.strip()
        if not line or not line.startswith("web/"):
            continue
        result.add(os.path.basename(line))
    return result


def file_modified_today(filename):
    path = os.path.join(web, filename)
    if not os.path.exists(path):
        return False
    return date.fromtimestamp(os.path.getmtime(path)) == today_date


staged = staged_web_files()


def should_bump(source_filename):
    """A source is bumped if it's staged OR (as a fallback) modified today.
    --all forces bumping every referenced file."""
    if force_all:
        return True
    # For source .jsx: check the .jsx directly. For compiled dist/*.js: check
    # both the .js (staged rebuild) and its .jsx source.
    if source_filename in staged:
        return True
    if source_filename.endswith(".jsx"):
        compiled = source_filename[:-4] + ".js"
        if compiled in staged:
            return True
    return file_modified_today(source_filename)


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

    # Compiled dist/foo.js corresponds to source foo.jsx
    source = filename.replace(".js", ".jsx") if filename.endswith(".js") else filename
    if not should_bump(source):
        continue

    if old_ver.startswith(today):
        new_tag = next_version(f"?v={old_ver}", today)
    else:
        new_tag = f"?v={today}-1"

    old_tag = f"?v={old_ver}"
    new_full = full_match.replace(old_tag, new_tag, 1)
    text = text.replace(full_match, new_full, 1)
    bumped.append(f"  {source}: ?v={old_ver} -> {new_tag[3:]}")

if bumped:
    print("Bumped versions:")
    for line in bumped:
        print(line)
    if not dry_run:
        open(html, "w", encoding="utf-8").write(text)
        print(f"Wrote {html}")
else:
    print("No source files staged or modified today — nothing to bump.")
