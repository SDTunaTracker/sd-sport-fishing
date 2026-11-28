"""Edit the hand-maintained race list (web/api/v1/paddle_races.json) from the command line.

PaddleGuru's terms forbid automated access, so new dates are added by hand:

    python -m src.paddle.races list [--year 2027]
    python -m src.paddle.races set the-loop-2027 --date 2027-05-15 --start 07:30 \\
        --url https://paddleguru.com/races/THELOOP2027
    python -m src.paddle.races set the-loop-2027 --confirm        # owner checked it
    python -m src.paddle.races new-season 2028                    # "date TBA" entry per series
    python -m src.paddle.races check                              # validate the file

Once a race has a date inside the forecast window (7 days), the next
`python -m src.paddle.forecast` run scores it; no other step is needed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import course as CO

DRAFT, TBA, CONFIRMED = "draft — confirm", "date TBA", "confirmed"
STATUSES = {DRAFT, TBA, CONFIRMED}


def load(path: Path = CO.RACES) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(doc: dict, path: Path = CO.RACES) -> None:
    doc["updated"] = date.today().isoformat()
    doc["races"].sort(key=lambda r: (-(r.get("year") or 0), r.get("date") or "9999", r["series"]))
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(doc: dict, courses: Path = CO.COURSES) -> list[str]:
    errs, seen = [], set()
    for r in doc.get("races", []):
        rid = r.get("id")
        if not rid or rid in seen:
            errs.append(f"missing or duplicate id {rid!r}")
        seen.add(rid)
        if r.get("status") not in STATUSES:
            errs.append(f"{rid}: status {r.get('status')!r}")
        if r.get("date"):
            try:
                d = date.fromisoformat(r["date"])
            except ValueError:
                errs.append(f"{rid}: bad date {r['date']!r}")
                continue
            if d.year != r.get("year"):
                errs.append(f"{rid}: date {r['date']} not in year {r.get('year')}")
        if r.get("startLocal") and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", r["startLocal"]):
            errs.append(f"{rid}: start {r['startLocal']!r} is not HH:MM")
        url = r.get("paddleguru")
        if url and not url.startswith("https://paddleguru.com/races/"):
            errs.append(f"{rid}: paddleguru link {url!r}")
        loc = r.get("location") or {}
        if not loc.get("name"):
            errs.append(f"{rid}: no location name")
        for dist in r.get("distances", []):
            if dist.get("courseId") and not (courses / f"{dist['courseId']}.geojson").exists():
                errs.append(f"{rid}: course file {dist['courseId']}.geojson missing")
    return errs


def find(doc: dict, rid: str) -> dict:
    for r in doc["races"]:
        if r["id"] == rid:
            return r
    raise SystemExit(f"no race {rid!r}; try: python -m src.paddle.races list")


def set_fields(doc: dict, rid: str, *, day: str | None = None, start: str | None = None, url: str | None = None,
               flexible: bool | None = None, confirm: bool = False) -> dict:
    r = find(doc, rid)
    if day:
        d = date.fromisoformat(day)
        r["date"], r["year"] = d.isoformat(), d.year
        if r.get("status") == TBA:
            r["status"] = DRAFT
    if start:
        r["startLocal"] = start
        r["startNote"] = None
    if url:
        r["paddleguru"] = url.split("?")[0].split("#")[0].rstrip("/")
        for tab in ("/course", "/schedule", "/results", "/register"):
            if r["paddleguru"].endswith(tab):
                r["paddleguru"] = r["paddleguru"][: -len(tab)]
    if flexible is not None:
        r["startFlexible"] = flexible
    if confirm:
        r["status"] = CONFIRMED
    return r


def new_season(doc: dict, year: int) -> list[str]:
    """Add a 'date TBA' entry for every series that has none in `year`; returns new ids."""
    have = {r["series"] for r in doc["races"] if r.get("year") == year}
    latest: dict[str, dict] = {}
    for r in doc["races"]:
        s = r["series"]
        if s not in latest or (r.get("year") or 0) > (latest[s].get("year") or 0):
            latest[s] = r
    added = []
    for s, r in sorted(latest.items()):
        if s in have:
            continue
        n = json.loads(json.dumps(r))
        n.update(id=f"{s}-{year}", year=year, date=None, paddleguru=None, registration=None, status=TBA)
        doc["races"].append(n)
        added.append(n["id"])
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Edit web/api/v1/paddle_races.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--year", type=int)
    p = sub.add_parser("set")
    p.add_argument("id")
    p.add_argument("--date")
    p.add_argument("--start", help="local start time HH:MM")
    p.add_argument("--url", help="PaddleGuru race page")
    p.add_argument("--flexible", action="store_true", default=None, help="start time is flexible (best window shown)")
    p.add_argument("--confirm", action="store_true", help="mark as checked by the owner")
    p = sub.add_parser("new-season")
    p.add_argument("year", type=int)
    sub.add_parser("check")
    a = ap.parse_args(argv)
    doc = load()
    if a.cmd == "list":
        for r in doc["races"]:
            if a.year and r.get("year") != a.year:
                continue
            print(f"{r['id']:34} {r.get('date') or 'TBA':10} {r.get('startLocal') or '':5} {r['status']}")
        return 0
    if a.cmd == "check":
        errs = check(doc)
        print("\n".join(errs) or f"OK: {len(doc['races'])} races")
        return 1 if errs else 0
    if a.cmd == "set":
        r = set_fields(doc, a.id, day=a.date, start=a.start, url=a.url, flexible=a.flexible, confirm=a.confirm)
        print(f"{r['id']}: {r.get('date') or 'TBA'} {r.get('startLocal') or ''} {r['status']}")
    elif a.cmd == "new-season":
        print("added:", ", ".join(new_season(doc, a.year)) or "nothing")
    errs = check(doc)
    if errs:
        print("not saved:\n" + "\n".join(errs))
        return 1
    save(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
