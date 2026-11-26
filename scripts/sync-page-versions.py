#!/usr/bin/env python3
"""
Keep the cache-bust ?v= tags in every other HTML page under web/ equal to
web/index.html's.

The pre-rendered pages (web/sd/boat/*/index.html, landing, species, trips,
web/sd/boats.html, web/sd/today.html, ...) copy their <script>/<link> tags
from index.html only when the scrape runs src/generate_pages.py. Until then
they keep loading the old file versions. On 2026-11-26 that kept every boat
page on a broken metric-definitions.js after the fix had shipped.

Only tags that name a file index.html also references are touched, so pages
with their own scripts (owner/admin) are left alone.

Usage:  python scripts/sync-page-versions.py           # rewrite stale tags
        python scripts/sync-page-versions.py --check   # report only; exit 1 if any
        python scripts/sync-page-versions.py --stage   # rewrite, then `git add` the pages
"""
import os, re, subprocess, sys
from pathlib import Path

here = Path(__file__).resolve().parent
repo = here.parent
web = repo / "web"
index = web / "index.html"

TAG = re.compile(r'((?:src|href)=")(/?(?:\./)?)([^"?#]+\.(?:js|jsx|css))\?v=([^"&#]+)(")')


def index_versions():
    text = index.read_text(encoding="utf-8")
    return {m.group(3): m.group(4) for m in TAG.finditer(text)}


def pages():
    for p in sorted(web.rglob("*.html")):
        if p == index or "node_modules" in p.parts:
            continue
        yield p


def scan(write):
    want = index_versions()
    changed, stale = [], []
    for p in pages():
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = []

        def fix(m):
            path, ver = m.group(3), m.group(4)
            good = want.get(path)
            if good is None or ver == good:
                return m.group(0)
            hits.append((path, ver, good))
            return f"{m.group(1)}{m.group(2)}{path}?v={good}{m.group(5)}"

        new = TAG.sub(fix, text)
        if hits:
            stale.append((p.relative_to(repo).as_posix(), hits))
            if write:
                p.write_text(new, encoding="utf-8", newline="")
                changed.append(p)
    return changed, stale


def main():
    check = "--check" in sys.argv
    changed, stale = scan(write=not check)
    if check:
        if not stale:
            print(f"OK: generated pages use index.html's script/style versions.")
            return 0
        n_tags = sum(len(h) for _, h in stale)
        print(f"STALE script/style versions in {len(stale)} generated page(s) ({n_tags} tags) "
              f"- they would load old files that index.html no longer uses:")
        for rel, hits in stale[:8]:
            path, ver, good = hits[0]
            more = f" (+{len(hits) - 1} more)" if len(hits) > 1 else ""
            print(f"  {rel}: {path}?v={ver}, index.html has ?v={good}{more}")
        if len(stale) > 8:
            print(f"  ... and {len(stale) - 8} more pages")
        print("  Fix: python scripts/sync-page-versions.py --stage")
        return 1
    if changed:
        print(f"Synced ?v= tags in {len(changed)} generated page(s) to index.html.")
        if "--stage" in sys.argv:
            # -u: stage these tracked pages without tripping over web/sd being in
            # .gitignore (the pages are force-tracked; untracked ones stay out).
            subprocess.run(["git", "-C", str(repo), "add", "-u", "--"] + [str(p) for p in changed], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
