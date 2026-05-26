"""Fetch recent Reddit posts about SD sportfishing and store them in the DB."""
from __future__ import annotations

import sqlite3
import time
from datetime import date

import requests

SEARCH_TERMS = [
    'San Diego sportfishing',
    'San Diego tuna',
    'bluefin San Diego',
    'yellowfin San Diego',
    'H&M Landing fishing',
    "Fisherman's Landing San Diego",
    'Seaforth sportfishing',
    'Point Loma sportfishing',
    'SD tuna report',
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


def _fetch_term(term: str, limit: int = 10) -> list[dict]:
    try:
        resp = requests.get(
            'https://www.reddit.com/search.json',
            params={'q': term, 'sort': 'new', 'limit': limit, 't': 'month', 'type': 'link'},
            headers=_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return []
        return [c['data'] for c in resp.json().get('data', {}).get('children', [])]
    except Exception:
        return []


def fetch_reddit_reports(conn: sqlite3.Connection) -> int:
    """Fetch posts for all search terms, deduplicate, and upsert. Returns row count."""
    boats = _known_boats(conn)
    today = date.today().isoformat()
    seen_ids: set[str] = set()
    rows: list[tuple] = []

    for i, term in enumerate(SEARCH_TERMS):
        if i > 0:
            time.sleep(1)  # respect rate limits
        for p in _fetch_term(term):
            pid = p.get('id', '')
            if not pid or pid in seen_ids:
                continue
            if p.get('score', 0) < 2:
                continue
            seen_ids.add(pid)
            text = f"{p.get('title', '')} {p.get('selftext', '')}".strip()
            rows.append((
                pid,
                p.get('title', ''),
                f"https://reddit.com{p.get('permalink', '')}",
                p.get('subreddit', ''),
                p.get('score', 0),
                p.get('num_comments', 0),
                int(p.get('created_utc', 0)),
                p.get('author', ''),
                (p.get('selftext') or '')[:300].strip(),
                term,
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
