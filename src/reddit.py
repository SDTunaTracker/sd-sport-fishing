"""Fetch recent Reddit posts about SD sportfishing and store them in the DB."""
from __future__ import annotations

import sqlite3
import time
from datetime import date

import requests

# Subreddits known to have San Diego sportfishing content.
# Searched with restrict_sr=1 so results stay on-topic.
SUBREDDIT_QUERIES = [
    ('sportfishing',       'San Diego'),
    ('sportfishing',       'bluefin'),
    ('sportfishing',       'yellowfin'),
    ('sportfishing',       'yellowtail'),
    ('SaltWaterFishing',   'San Diego'),
    ('SaltWaterFishing',   'bluefin San Diego'),
    ('fishing',            'San Diego tuna'),
    ('fishing',            'San Diego sportfishing'),
    ('CaliforniaFishing',  'San Diego'),
    ('CaliforniaFishing',  'bluefin'),
    ('sandiego',           'sportfishing'),
    ('sandiego',           'fishing report'),
    ('sandiego',           'tuna'),
]

_HEADERS = {'User-Agent': 'TheTunaTracker/1.0 (thetunatracker.com)'}


def _known_boats(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT boat FROM trips ORDER BY boat"
    ).fetchall()]


def detect_boat_mention(text: str, boat_names: list[str]) -> str | None:
    lower = text.lower()
    for boat in boat_names:
        if boat.lower() in lower:
            return boat
    return None


def _fetch_subreddit(subreddit: str, query: str, limit: int = 15) -> list[dict]:
    try:
        resp = requests.get(
            f'https://www.reddit.com/r/{subreddit}/search.json',
            params={
                'q': query,
                'sort': 'new',
                'limit': limit,
                't': 'month',
                'type': 'link',
                'restrict_sr': '1',   # stay within this subreddit
            },
            headers=_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return []
        return [c['data'] for c in resp.json().get('data', {}).get('children', [])]
    except Exception:
        return []


def fetch_reddit_reports(conn: sqlite3.Connection) -> int:
    """Fetch posts from targeted fishing subreddits, deduplicate, and upsert."""
    boats = _known_boats(conn)
    today = date.today().isoformat()
    seen_ids: set[str] = set()
    rows: list[tuple] = []

    for i, (subreddit, query) in enumerate(SUBREDDIT_QUERIES):
        if i > 0:
            time.sleep(1)
        for p in _fetch_subreddit(subreddit, query):
            pid = p.get('id', '')
            if not pid or pid in seen_ids:
                continue
            if p.get('score', 0) < 1:
                continue
            seen_ids.add(pid)
            selftext = (p.get('selftext') or '').strip()
            title    = (p.get('title') or '').strip()
            text     = f"{title} {selftext}"
            # Store up to 2000 chars of body so Claude has enough context
            snippet  = selftext[:2000] if selftext else ''
            rows.append((
                pid,
                title,
                f"https://reddit.com{p.get('permalink', '')}",
                p.get('subreddit', ''),
                p.get('score', 0),
                p.get('num_comments', 0),
                int(p.get('created_utc', 0)),
                p.get('author', ''),
                snippet,
                f"r/{subreddit}: {query}",
                detect_boat_mention(text, boats),
                today,
            ))

    if not rows:
        return 0
    conn.executemany(
        """INSERT OR REPLACE INTO reddit_reports
           (id, title, url, subreddit, score, num_comments, created_utc,
            author, snippet, search_term, boat_mentioned, fetched_date)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    return len(rows)
