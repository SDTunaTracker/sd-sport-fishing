"""One-shot: refresh every stale (>7d) ?v= cache-bust tag in index.html to today.

verify-deploy.py rejects date-versioned tags older than 7 days. After a long
dev pause, most tags are stale even though the underlying files didn't change.
Since a push triggers a full Cloudflare cache purge, refreshing all tags is
truthful — every asset gets re-served fresh.

Leaves already-current tags alone.
"""
import os, re
from datetime import date, timedelta
from pathlib import Path

here = Path(__file__).resolve().parent
html = here.parent / "web" / "index.html"
today = date.today()
today_str = today.strftime("%Y%m%d")
cutoff = today - timedelta(days=7)

text = html.read_text(encoding="utf-8")


def replace(m):
    prefix = m.group(1)  # 'src="..."?v=' or 'href="..."?v='
    ver = m.group(2)
    date_part = ver[:8]
    try:
        d = date(int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8]))
    except ValueError:
        return m.group(0)
    if d >= cutoff:
        return m.group(0)
    return f'{prefix}{today_str}-1"'


pattern = re.compile(r'((?:src|href)="[^"]+\?v=)([^"]+)"')
new_text = pattern.sub(replace, text)

if new_text != text:
    html.write_text(new_text, encoding="utf-8")
    print("index.html refreshed.")
else:
    print("Nothing to refresh.")
