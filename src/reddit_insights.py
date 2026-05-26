"""Reddit intelligence pipeline — Claude API extracts structured fishing insights."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

KNOWN_LOCATIONS = [
    '60-Mile Bank', '9-Mile Bank', 'Tanner Bank',
    'Cortez Bank', 'San Clemente Island',
    'Catalina Island', 'Coronado Islands',
    'Point Loma', 'La Jolla', 'Oceanside',
    'offshore', 'inshore', 'the islands',
]

KNOWN_SPECIES = [
    'Bluefin', 'Yellowfin', 'Yellowtail',
    'Dorado', 'Albacore', 'Skipjack',
    'White Sea Bass', 'Halibut', 'Rockfish',
    'Calico Bass', 'Bonito', 'Barracuda',
]

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def analyze_reddit_post(post_title: str, post_text: str) -> dict | None:
    """Call Claude to extract structured fishing data from one Reddit post."""
    prompt = f"""Analyze this fishing report from Reddit and extract structured information.

POST TITLE: {post_title}
POST TEXT: {post_text or '(no body text)'}

Extract and return ONLY a JSON object with these exact keys:
{{
  "is_fishing_report": true/false,
  "report_date": "YYYY-MM-DD or null",
  "report_quality": 1-5,
  "species": [
    {{"name": "Bluefin", "status": "hot/active/slow/none", "count": number_or_null}}
  ],
  "locations": ["60-Mile Bank", "San Clemente Island"],
  "primary_location": "most mentioned location or null",
  "bait": ["live mackerel", "sardine"],
  "lures": ["surface iron", "knife jig"],
  "techniques": ["fly-lining", "kite fishing"],
  "boats_mentioned": [
    {{"name": "Pacific Queen", "sentiment": "positive/negative/neutral", "context": "brief quote"}}
  ],
  "summary": "1-2 sentence plain English summary of what was caught where",
  "confidence": "high/medium/low",
  "community_mood": "optimistic/neutral/pessimistic"
}}

Return ONLY the JSON, no other text."""

    client = _get_client()
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[1:end]).strip()
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.warning("JSON parse error for '%s': %s", (post_title or '')[:60], e)
        return None
    except Exception as e:
        log.error("Claude API error for '%s': %s", (post_title or '')[:60], e)
        return None


def process_unanalyzed_posts(conn: sqlite3.Connection) -> int:
    """Analyze all reddit_reports not yet in reddit_insights. Returns count processed."""
    analyzed = {r[0] for r in conn.execute(
        "SELECT reddit_post_id FROM reddit_insights"
    ).fetchall()}

    rows = conn.execute(
        "SELECT id, title, snippet FROM reddit_reports ORDER BY created_utc DESC"
    ).fetchall()

    unprocessed = [r for r in rows if r[0] not in analyzed]
    if not unprocessed:
        return 0

    today = date.today().isoformat()
    n = 0
    for post in unprocessed:
        post_id, title, snippet = post[0], post[1], post[2]
        result = analyze_reddit_post(title or '', snippet or '')
        if result is None:
            time.sleep(1)
            continue

        sp_list = result.get('species', [])
        sp_names = [s['name'] for s in sp_list if isinstance(s, dict) and s.get('name')]
        sp_sentiment = {
            s['name']: s['status']
            for s in sp_list
            if isinstance(s, dict) and s.get('name') and s.get('status')
        }
        boats_raw = result.get('boats_mentioned', [])
        boat_names = [b['name'] for b in boats_raw if isinstance(b, dict) and b.get('name')]
        boat_sent = {
            b['name']: b.get('sentiment', 'neutral')
            for b in boats_raw
            if isinstance(b, dict) and b.get('name')
        }

        conn.execute(
            """INSERT OR REPLACE INTO reddit_insights
               (reddit_post_id, processed_date,
                species_mentioned, species_sentiment,
                locations_mentioned, primary_location,
                bait_mentioned, lures_mentioned, techniques,
                boats_mentioned, boat_sentiment,
                report_quality, report_date, confidence, summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                post_id, today,
                json.dumps(sp_names), json.dumps(sp_sentiment),
                json.dumps(result.get('locations', [])),
                result.get('primary_location'),
                json.dumps(result.get('bait', [])),
                json.dumps(result.get('lures', [])),
                json.dumps(result.get('techniques', [])),
                json.dumps(boat_names), json.dumps(boat_sent),
                result.get('report_quality', 1),
                result.get('report_date'),
                result.get('confidence', 'low'),
                result.get('summary', ''),
            ),
        )
        conn.commit()
        n += 1
        log.info("Analyzed post %s (quality=%s)", post_id, result.get('report_quality'))
        time.sleep(1)

    return n


def generate_weekly_summary(conn: sqlite3.Connection, week_start: str, week_end: str) -> dict | None:
    """Generate and store a plain-English weekly fishing summary using Claude."""
    rows = conn.execute(
        """SELECT summary, species_mentioned, locations_mentioned, community_mood, report_quality
           FROM reddit_insights
           WHERE processed_date BETWEEN ? AND ? AND report_quality >= 2
           ORDER BY report_quality DESC""",
        (week_start, week_end),
    ).fetchall()

    if not rows:
        return None

    sp_counts: dict[str, int] = {}
    loc_counts: dict[str, int] = {}
    moods: list[str] = []
    summaries: list[str] = []

    for r in rows:
        for sp in _safe_json(r[1]):
            sp_counts[sp] = sp_counts.get(sp, 0) + 1
        for loc in _safe_json(r[2]):
            loc_counts[loc] = loc_counts.get(loc, 0) + 1
        if r[3]:
            moods.append(r[3])
        if r[0]:
            summaries.append(r[0])

    top_species = sorted(sp_counts, key=lambda k: -sp_counts[k])[:3]
    top_location = sorted(loc_counts, key=lambda k: -loc_counts[k])[0] if loc_counts else None
    opt = moods.count('optimistic')
    pes = moods.count('pessimistic')
    mood = 'optimistic' if opt > pes else ('pessimistic' if pes > opt else 'neutral')

    client = _get_client()
    prompt = (
        f"Based on these San Diego sportfishing community reports from {week_start} to {week_end}, "
        f"write a 2-3 paragraph fishing summary for San Diego sportfishing anglers.\n\n"
        f"Top species: {', '.join(top_species) or 'mixed'}\n"
        f"Top location: {top_location or 'varies'}\n"
        f"Community mood: {mood}\n"
        f"Reports analyzed: {len(rows)}\n\n"
        f"Trip summaries:\n" + "\n".join(f"- {s}" for s in summaries[:10])
        + "\n\nWrite in a friendly, informative tone like a fishing newsletter. "
        "Include: what was biting, where, standout trips, and outlook. "
        "Keep it under 200 words. Return only the summary text, no headers."
    )

    try:
        resp = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        summary_text = resp.content[0].text.strip()
    except Exception as e:
        log.error("Weekly summary generation failed: %s", e)
        summary_text = (
            f"{len(rows)} fishing reports for {week_start} to {week_end}. "
            f"Top species: {', '.join(top_species)}. "
            f"Community mood: {mood}."
        )

    generated_at = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO weekly_summaries
           (week_start, week_end, summary_text, top_species, top_location,
            community_mood, report_count, generated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (week_start, week_end, summary_text,
         json.dumps(top_species), top_location, mood, len(rows), generated_at),
    )
    conn.commit()
    return {
        'week_start': week_start, 'week_end': week_end,
        'summary_text': summary_text, 'top_species': top_species,
        'top_location': top_location, 'community_mood': mood,
        'report_count': len(rows), 'generated_at': generated_at,
    }


def build_bite_report(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Species activity status from analyzed posts in the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT species_mentioned, species_sentiment, primary_location
           FROM reddit_insights WHERE processed_date >= ? AND report_quality >= 2""",
        (cutoff,),
    ).fetchall()

    counts: dict[str, int] = {}
    statuses: dict[str, list[str]] = {}
    locations: dict[str, list[str]] = {}

    for r in rows:
        sp_list = _safe_json(r[0])
        sent_map = _safe_json(r[1], as_dict=True)
        for sp in sp_list:
            counts[sp] = counts.get(sp, 0) + 1
            if sp in sent_map:
                statuses.setdefault(sp, []).append(sent_map[sp])
            if r[2]:
                locations.setdefault(sp, []).append(r[2])

    result = []
    for sp in sorted(counts, key=lambda k: -counts[k]):
        all_st = statuses.get(sp, [])
        best = max(set(all_st), key=all_st.count) if all_st else 'active'
        loc_list = locations.get(sp, [])
        top_loc = max(set(loc_list), key=loc_list.count) if loc_list else None
        result.append({'name': sp, 'status': best, 'reports': counts[sp], 'where': top_loc})
    return result


def build_hotspot_report(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Location rankings weighted by report quality."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT locations_mentioned, species_mentioned, report_quality
           FROM reddit_insights WHERE processed_date >= ? AND report_quality >= 2""",
        (cutoff,),
    ).fetchall()

    loc_score: dict[str, int] = {}
    loc_species: dict[str, list[str]] = {}

    for r in rows:
        locs = _safe_json(r[0])
        species = _safe_json(r[1])
        quality = r[2] or 1
        for loc in locs:
            loc_score[loc] = loc_score.get(loc, 0) + quality
            loc_species.setdefault(loc, []).extend(species)

    result = []
    for loc in sorted(loc_score, key=lambda k: -loc_score[k]):
        sp_list = loc_species.get(loc, [])
        top_sp = sorted(set(sp_list), key=sp_list.count, reverse=True)[:3]
        result.append({'location': loc, 'mentions': loc_score[loc], 'species': top_sp})
    return result


def community_payload(conn: sqlite3.Connection) -> dict:
    """Build the full window.SD.COMMUNITY payload for the frontend."""
    today = date.today().isoformat()
    cutoff_7 = (date.today() - timedelta(days=7)).isoformat()

    bite = build_bite_report(conn)
    hotspots = build_hotspot_report(conn)

    ws_row = conn.execute(
        "SELECT * FROM weekly_summaries ORDER BY week_start DESC LIMIT 1"
    ).fetchone()
    weekly = None
    if ws_row:
        try:
            weekly = {
                'week_start': ws_row['week_start'],
                'week_end': ws_row['week_end'],
                'text': ws_row['summary_text'],
                'top_species': _safe_json(ws_row['top_species']),
                'top_location': ws_row['top_location'],
                'mood': ws_row['community_mood'],
                'report_count': ws_row['report_count'],
                'generated_at': ws_row['generated_at'],
            }
        except Exception:
            pass

    recent_rows = conn.execute(
        """SELECT rr.title, rr.url, ri.processed_date, ri.summary,
                  ri.primary_location, ri.report_quality
           FROM reddit_insights ri
           JOIN reddit_reports rr ON rr.id = ri.reddit_post_id
           WHERE ri.report_quality >= 3
           ORDER BY ri.processed_date DESC LIMIT 10""",
    ).fetchall()
    recent_posts = [
        {
            'title': r['title'], 'url': r['url'],
            'date': r['processed_date'], 'summary': r['summary'],
            'location': r['primary_location'], 'quality': r['report_quality'],
        }
        for r in recent_rows
    ]

    boat_rows = conn.execute(
        """SELECT ri.boats_mentioned, ri.boat_sentiment, ri.summary, ri.processed_date, rr.url
           FROM reddit_insights ri
           JOIN reddit_reports rr ON rr.id = ri.reddit_post_id
           WHERE ri.processed_date >= ? AND ri.boats_mentioned != '[]'""",
        (cutoff_7,),
    ).fetchall()
    boat_mentions: dict[str, dict] = {}
    for r in boat_rows:
        boats = _safe_json(r['boats_mentioned'])
        sents = _safe_json(r['boat_sentiment'], as_dict=True)
        for b in boats:
            if b not in boat_mentions:
                boat_mentions[b] = {'mentions': 0, 'positive': 0, 'negative': 0,
                                    'neutral': 0, 'recent_quotes': []}
            boat_mentions[b]['mentions'] += 1
            s = sents.get(b, 'neutral')
            boat_mentions[b][s] = boat_mentions[b].get(s, 0) + 1
            if r['summary'] and len(boat_mentions[b]['recent_quotes']) < 2:
                boat_mentions[b]['recent_quotes'].append({
                    'text': r['summary'], 'date': r['processed_date'], 'url': r['url'],
                })
    for data in boat_mentions.values():
        p, n = data['positive'], data['negative']
        data['sentiment'] = 'positive' if p > n else ('negative' if n > p else 'neutral')

    total_analyzed = conn.execute("SELECT COUNT(*) FROM reddit_insights").fetchone()[0]
    week_analyzed = conn.execute(
        "SELECT COUNT(*) FROM reddit_insights WHERE processed_date >= ?", (cutoff_7,)
    ).fetchone()[0]
    sp_week: dict[str, int] = {}
    loc_week: dict[str, int] = {}
    for r in conn.execute(
        "SELECT species_mentioned, locations_mentioned FROM reddit_insights WHERE processed_date >= ?",
        (cutoff_7,)
    ).fetchall():
        for sp in _safe_json(r[0]):
            sp_week[sp] = sp_week.get(sp, 0) + 1
        for loc in _safe_json(r[1]):
            loc_week[loc] = loc_week.get(loc, 0) + 1

    return {
        'biteReport': {'updated': today, 'species': bite},
        'hotspots': hotspots[:8],
        'weeklySummary': weekly,
        'recentPosts': recent_posts,
        'boatMentions': boat_mentions,
        'stats': {
            'totalAnalyzed': total_analyzed,
            'weekAnalyzed': week_analyzed,
            'topSpeciesWeek': sorted(sp_week.items(), key=lambda x: -x[1])[:5],
            'topLocsWeek': sorted(loc_week.items(), key=lambda x: -x[1])[:5],
        },
    }


def _safe_json(val, *, as_dict: bool = False):
    """Parse a JSON column value safely; returns [] or {} on failure."""
    try:
        return json.loads(val or ('{}' if as_dict else '[]'))
    except Exception:
        return {} if as_dict else []
