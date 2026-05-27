"""
One-off: search Reddit (5-year history) for trip reports mentioning
each specific SD landing boat. Only stores posts where the boat name
actually appears in the title or body.

Run from project root:
    .venv\Scripts\python.exe scripts\reddit_boat_backfill.py
"""
import os, sys, sqlite3, time, json, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')

import requests
from src.db import connect
from src.reddit_insights import process_unanalyzed_posts

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / 'tracker.db'
HEADERS = {'User-Agent': 'TheTunaTracker/1.0 (thetunatracker.com)'}

# Skip names too generic to produce useful signal
SKIP_NAMES = {
    'San Diego', 'Point Loma', 'Grande', 'Pacifica', 'Pride', 'Apollo',
    'Aztec', 'Tribute', 'Voyager', 'Success', 'Independence', 'Freedom',
    'Commander', 'Cortez', 'Pacific Star', 'Pacific Voyager', 'Endeavor (Ventura)',
    'Highliner', 'Invader', 'Outer Limits', 'Sea Watch', 'New Seaforth',
    'Pacific Islander', 'Oceanside 95', 'El Gato Dos', 'Game Changer',
    'New Lo-An', 'Polaris Supreme',
}

# Subreddits most likely to have SD sportfishing trip reports
SUBREDDITS = ['sportfishing', 'saltwaterfishing', 'Fishing', 'CaliforniaFishing']


def search_boat(boat_name: str, limit: int = 25) -> list[dict]:
    results = []
    seen = set()
    for sub in SUBREDDITS:
        try:
            resp = requests.get(
                f'https://www.reddit.com/r/{sub}/search.json',
                params={
                    'q': f'"{boat_name}"',
                    'sort': 'new',
                    'limit': limit,
                    't': 'all',
                    'restrict_sr': '1',
                },
                headers=HEADERS,
                timeout=12,
            )
            if resp.status_code != 200:
                continue
            for child in resp.json().get('data', {}).get('children', []):
                p = child['data']
                pid = p.get('id', '')
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                title = (p.get('title') or '').strip()
                body  = (p.get('selftext') or '').strip()
                # Must actually mention the boat name (case-insensitive)
                if boat_name.lower() not in (title + ' ' + body).lower():
                    continue
                if p.get('score', 0) < 1:
                    continue
                results.append({
                    'id':          pid,
                    'title':       title,
                    'url':         f"https://reddit.com{p.get('permalink','')}",
                    'subreddit':   p.get('subreddit', ''),
                    'score':       p.get('score', 0),
                    'num_comments': p.get('num_comments', 0),
                    'created_utc': int(p.get('created_utc', 0)),
                    'author':      p.get('author', ''),
                    'snippet':     body[:2000],
                    'search_term': f'boat:{boat_name}',
                    'boat_mentioned': boat_name,
                })
            time.sleep(0.8)
        except Exception as e:
            log.warning("Search failed for %s in r/%s: %s", boat_name, sub, e)
    return results


def main():
    with connect(DB_PATH) as conn:
        boats = [r[0] for r in conn.execute("""
            SELECT DISTINCT boat FROM trips
            WHERE landing IN (
                'H&M Landing','Fisherman''s Landing',
                'Seaforth Sportfishing','Point Loma Sportfishing'
            )
            AND is_half_day = 0
            ORDER BY boat
        """).fetchall()]

    boats = [b for b in boats if b not in SKIP_NAMES and len(b) > 4]
    log.info("Searching %d distinctive boat names...", len(boats))

    total_new = 0
    with connect(DB_PATH) as conn:
        existing_ids = {r[0] for r in conn.execute("SELECT id FROM reddit_reports").fetchall()}

        for i, boat in enumerate(boats):
            posts = search_boat(boat)
            new_posts = [p for p in posts if p['id'] not in existing_ids]
            if new_posts:
                conn.executemany(
                    """INSERT OR IGNORE INTO reddit_reports
                       (id, title, url, subreddit, score, num_comments, created_utc,
                        author, snippet, search_term, boat_mentioned, fetched_date)
                       VALUES (:id,:title,:url,:subreddit,:score,:num_comments,:created_utc,
                               :author,:snippet,:search_term,:boat_mentioned,date('now'))""",
                    new_posts,
                )
                conn.commit()
                for p in new_posts:
                    existing_ids.add(p['id'])
                log.info("[%d/%d] %-30s → %d new posts", i+1, len(boats), boat, len(new_posts))
                total_new += len(new_posts)
            else:
                log.info("[%d/%d] %-30s → (no new posts)", i+1, len(boats), boat)

            time.sleep(0.5)

    log.info("\nTotal new posts stored: %d", total_new)

    # Now analyze only the unprocessed ones
    log.info("Running Claude analysis on unanalyzed posts...")
    with connect(DB_PATH) as conn:
        n = process_unanalyzed_posts(conn)
    log.info("Analyzed %d posts", n)

    # Show quality 3+ results
    with connect(DB_PATH) as conn:
        rows = conn.execute("""
            SELECT ri.report_quality, ri.boats_mentioned, ri.primary_location,
                   ri.summary, rr.title, rr.url
            FROM reddit_insights ri
            JOIN reddit_reports rr ON rr.id = ri.reddit_post_id
            WHERE ri.report_quality >= 3
              AND rr.search_term LIKE 'boat:%'
            ORDER BY ri.report_quality DESC, ri.processed_date DESC
        """).fetchall()

    print(f"\n{'='*70}")
    print(f"HIGH-QUALITY BOAT-SPECIFIC REPORTS ({len(rows)} found):")
    print('='*70)
    for r in rows:
        boats_raw = r[1] or '[]'
        try:
            boats_list = json.loads(boats_raw)
        except Exception:
            boats_list = [boats_raw]
        print(f"\n[{r[0]}★] {r[4]}")
        print(f"     Boats: {', '.join(boats_list)}")
        print(f"     Where: {r[2] or '—'}")
        print(f"     {r[3] or ''}")
        print(f"     {r[5]}")


if __name__ == '__main__':
    main()
