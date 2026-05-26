"""Boat review helpers — DB insert, approve/reject, export, CLI.

CLI usage:
    python -m src.reviews list              # show pending reviews
    python -m src.reviews approve <id>      # approve a review
    python -m src.reviews reject <id>       # reject a review
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

OVERNIGHT_LENGTHS = {
    'Overnight', '1.5 Day', '2 Day', '2.5 Day', '3 Day',
    '4 Day', '5 Day', '6 Day', '7 Day', 'Long Range',
}

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'tracker.db'


def add_review(conn, data: dict, ip: str = '') -> int:
    """Insert a new review with status='pending'. Returns row id."""
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16] if ip else None
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    cur = conn.execute(
        """INSERT INTO boat_reviews
           (boat, landing, reviewer_name, trip_date, trip_length,
            overall_rating, captain_rating, crew_rating, fish_finding_rating,
            galley_rating, bunks_rating,
            title, body, species_caught, tuna_count, would_rebook,
            status, submitted_at, ip_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get('boat'), data.get('landing'),
            data.get('reviewer_name'), data.get('trip_date'), data.get('trip_length'),
            data.get('overall_rating'), data.get('captain_rating'), data.get('crew_rating'),
            data.get('fish_finding_rating'), data.get('galley_rating'), data.get('bunks_rating'),
            data.get('title'), data.get('body'),
            data.get('species_caught'), data.get('tuna_count'), data.get('would_rebook'),
            'pending', now, ip_hash,
        ),
    )
    return cur.lastrowid


def approve_review(conn, review_id: int) -> None:
    conn.execute("UPDATE boat_reviews SET status='approved' WHERE id=?", (review_id,))


def reject_review(conn, review_id: int) -> None:
    conn.execute("UPDATE boat_reviews SET status='rejected' WHERE id=?", (review_id,))


def reviews_for_export(conn) -> dict:
    """Build the REVIEWS payload for data.js (approved reviews only)."""
    rows = conn.execute(
        "SELECT * FROM boat_reviews WHERE status='approved' ORDER BY submitted_at DESC"
    ).fetchall()

    by_boat: dict[str, list] = {}
    for r in rows:
        boat = r['boat']
        is_overnight = (r['trip_length'] or '') in OVERNIGHT_LENGTHS
        entry = {
            'id': r['id'],
            'boat': boat,
            'landing': r['landing'],
            'reviewer_name': r['reviewer_name'] or 'Anonymous',
            'trip_date': r['trip_date'],
            'trip_length': r['trip_length'],
            'overall_rating': r['overall_rating'],
            'captain_rating': r['captain_rating'],
            'crew_rating': r['crew_rating'],
            'fish_finding_rating': r['fish_finding_rating'],
            'galley_rating': r['galley_rating'],
            'bunks_rating': r['bunks_rating'] if is_overnight else None,
            'title': r['title'],
            'body': r['body'],
            'species_caught': r['species_caught'],
            'tuna_count': r['tuna_count'],
            'would_rebook': bool(r['would_rebook']),
            'submitted_at': (r['submitted_at'] or '')[:10],
        }
        by_boat.setdefault(boat, []).append(entry)

    summary: dict[str, dict] = {}
    for boat, reviews in by_boat.items():
        def _avg(field):
            vals = [rv[field] for rv in reviews if rv.get(field) is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        overnight_reviews = [rv for rv in reviews if rv.get('bunks_rating') is not None]
        rebook = [rv for rv in reviews if rv.get('would_rebook')]
        catches = [rv['tuna_count'] for rv in reviews if rv.get('tuna_count')]

        avg_bunks = None
        if overnight_reviews:
            avg_bunks = round(
                sum(rv['bunks_rating'] for rv in overnight_reviews) / len(overnight_reviews), 1
            )

        summary[boat] = {
            'avg_overall':      _avg('overall_rating'),
            'avg_captain':      _avg('captain_rating'),
            'avg_crew':         _avg('crew_rating'),
            'avg_fish_finding': _avg('fish_finding_rating'),
            'avg_galley':       _avg('galley_rating'),
            'avg_bunks':        avg_bunks,
            'total_reviews':    len(reviews),
            'would_rebook_pct': round(len(rebook) / len(reviews) * 100) if reviews else None,
            'recent_catch_avg': round(sum(catches) / len(catches), 1) if catches else None,
        }

    return {'byBoat': by_boat, 'summary': summary}


def reviews_admin_stats(conn) -> dict:
    """Review stats + pending list for the admin panel."""
    counts = {r['status']: r['n'] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM boat_reviews GROUP BY status"
    ).fetchall()}
    pending = [dict(r) for r in conn.execute(
        "SELECT id, boat, landing, reviewer_name, overall_rating, title, submitted_at"
        " FROM boat_reviews WHERE status='pending' ORDER BY submitted_at DESC LIMIT 50"
    ).fetchall()]
    return {
        'total':          sum(counts.values()),
        'pending':        counts.get('pending', 0),
        'approved':       counts.get('approved', 0),
        'rejected':       counts.get('rejected', 0),
        'pendingReviews': pending,
    }


def _cli():
    from . import db
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    with db.connect(DB_PATH) as conn:
        if cmd == 'list':
            rows = conn.execute(
                "SELECT id, boat, reviewer_name, overall_rating, title, submitted_at"
                " FROM boat_reviews WHERE status='pending' ORDER BY submitted_at DESC"
            ).fetchall()
            if not rows:
                print('No pending reviews.')
            for r in rows:
                print(f"[{r['id']}] {r['boat']} | ★{r['overall_rating']} | {r['reviewer_name']} | {r['submitted_at'][:10]} | {r['title']}")
        elif cmd == 'approve' and len(args) > 1:
            approve_review(conn, int(args[1]))
            print(f'Approved review {args[1]}.')
        elif cmd == 'reject' and len(args) > 1:
            reject_review(conn, int(args[1]))
            print(f'Rejected review {args[1]}.')
        elif cmd == 'add' and len(args) > 1:
            data = json.loads(Path(args[1]).read_text())
            rid = add_review(conn, data)
            approve_review(conn, rid)
            print(f'Added and approved review {rid} for {data.get("boat")}.')
        else:
            print(__doc__)


if __name__ == '__main__':
    _cli()
