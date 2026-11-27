"""Daily live check for the Surftracker cam page (/sd/surf/cams).

Reads the hand-edited cam list in web/api/v1/surf_cams.json and writes
web/api/v1/surf_cams_status.json, which the page uses to show "Cam offline"
instead of a broken player.

No API key and no watch-page scraping. Two public, keyless endpoints:
  1. YouTube oEmbed: 200 = the video exists and may be embedded;
     401/403 = embedding turned off; 400/404 = removed, private or deleted.
  2. The video's thumbnail (i.ytimg.com/vi/<id>/hqdefault.jpg): a 404 means
     the video is gone even if oEmbed answered.

What this can't see: a stream that ended but stays up as a recording (oEmbed
and the thumbnail still answer). Thumbnails can't tell us either: some live
streams keep their start-of-stream thumbnail for months (The Rooftop Bar's
still shows Aug 2025 while it is live), so a "picture hasn't changed" rule
would hide working cams. Telling live from ended needs the YouTube Data API
(videos.list liveBroadcastContent), i.e. an owner API key.

A failed check (network, 5xx) keeps the cam's previous status rather than
hiding a cam that is probably fine. Never raises: the scrape must not fail.

Run:  python -m src.surf.cams
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CAMS = ROOT / "web" / "api" / "v1" / "surf_cams.json"
OUT = ROOT / "web" / "api" / "v1" / "surf_cams_status.json"

OEMBED = "https://www.youtube.com/oembed"
THUMB = "https://i.ytimg.com/vi/{id}/hqdefault.jpg"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; surftracker-cam-check)"}


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_cam(cam: dict, prev: dict | None, now: datetime, get=requests.get) -> dict:
    """Return this cam's new status entry. `get` is injectable for tests."""
    prev = prev or {}
    vid = cam["youtube"]
    out = {"checkedAt": _iso(now), "lastSeen": prev.get("lastSeen")}

    def keep(reason):   # check failed: keep what we knew, say why
        return dict(prev, checkedAt=_iso(now), checkError=reason) if prev.get("status") else \
            dict(out, status="unknown", checkError=reason)

    try:
        r = get(OEMBED, params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
                headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        return keep(f"oEmbed request failed: {type(e).__name__}")
    if r.status_code in (401, 403):
        return dict(out, status="offline", reason="The operator has turned off embedding.")
    if r.status_code in (400, 404):
        return dict(out, status="offline", reason="This stream has ended or been removed.")
    if r.status_code != 200:
        return keep(f"oEmbed HTTP {r.status_code}")
    try:
        title = (r.json() or {}).get("title")
    except ValueError:
        title = None

    try:
        t = get(THUMB.format(id=vid), headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        return keep(f"thumbnail request failed: {type(e).__name__}")
    if t.status_code == 404:
        return dict(out, status="offline", reason="This stream has ended or been removed.")
    out["title"] = title
    out.update(status="online", lastSeen=_iso(now))
    return out


def run(cams_path: Path = CAMS, out_path: Path = OUT, now: datetime | None = None,
        get=requests.get, pause: float = 1.0) -> dict:
    now = now or datetime.now(timezone.utc)
    cams = json.loads(cams_path.read_text(encoding="utf-8"))["cams"]
    try:
        prev = json.loads(out_path.read_text(encoding="utf-8")).get("cams", {})
    except (OSError, ValueError):
        prev = {}
    status = {}
    for i, cam in enumerate(cams):
        if i and pause:
            time.sleep(pause)   # one request a second: be polite
        try:
            status[cam["id"]] = check_cam(cam, prev.get(cam["id"]), now, get=get)
        except Exception as e:   # never let one cam stop the file being written
            log.warning("cam %s: check crashed: %s", cam.get("id"), e)
            status[cam["id"]] = dict(prev.get(cam["id"]) or {"status": "unknown"}, checkError=str(e)[:120])
        log.info("cam %-18s %s %s", cam["id"], status[cam["id"]].get("status"),
                 status[cam["id"]].get("reason") or status[cam["id"]].get("checkError") or "")
    payload = {"generatedAt": _iso(now), "staleAfterHours": 72,
               "method": "YouTube oEmbed (exists and embeddable) plus a thumbnail check (not removed). No API key; cannot tell a live stream from an ended one that stays up as a recording.",
               "cams": status}
    out_path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        p = run()
    except Exception as e:
        log.warning("surf cams check failed: %s", e)
        return 0
    ok = sum(1 for s in p["cams"].values() if s.get("status") == "online")
    log.info("surf cams: %d of %d online", ok, len(p["cams"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
