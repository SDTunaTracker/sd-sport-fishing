"""Suggest Google place_ids for our boats and landings (one-off, owner-run).

Uses Places API (New) Text Search with a minimal field mask (id, name,
address, types). That is the Text Search Pro SKU, with 5,000 free calls a month;
~190 boats + landings costs $0. Writes CANDIDATES only. A human confirms each
match before it goes into web/api/v1/google_places.json, because many party
boats have no listing of their own, and a wrong place shows another
business's reviews.

    set GOOGLE_PLACES_API_KEY=...        (PowerShell: $env:GOOGLE_PLACES_API_KEY="...")
    .venv\\Scripts\\python.exe scripts\\match_google_places.py            # all boats + landings
    .venv\\Scripts\\python.exe scripts\\match_google_places.py --apply    # merge "suggested" ones

--apply merges only candidates whose Google name contains the boat or landing
name and that are tagged as a boat/fishing business. Review the diff before
committing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "tracker.db"
OUT = ROOT / "data" / "google_places.candidates.json"
MAP = ROOT / "web" / "api" / "v1" / "google_places.json"
URL = "https://places.googleapis.com/v1/places:searchText"
MASK = "places.id,places.displayName,places.formattedAddress,places.types"
GOOD_TYPES = {"fishing_charter", "boat_tour_agency", "tour_agency", "marina",
              "tourist_attraction", "travel_agency", "point_of_interest"}

CITY = {  # helps Text Search pick the right port
    "H&M Landing": "San Diego", "Fisherman's Landing": "San Diego",
    "Seaforth Sportfishing": "San Diego", "Point Loma Sportfishing": "San Diego",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def search(key: str, query: str) -> list[dict]:
    r = requests.post(URL, timeout=20, json={"textQuery": query, "maxResultCount": 3},
                      headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": MASK})
    r.raise_for_status()
    out = []
    for p in r.json().get("places", []):
        out.append({"place_id": p["id"], "google_name": p.get("displayName", {}).get("text", ""),
                    "address": p.get("formattedAddress", ""), "types": p.get("types", [])})
    return out


def suggest(name: str, cands: list[dict]) -> dict | None:
    n = _norm(name)
    for c in cands:
        if n and n in _norm(c["google_name"]) and set(c["types"]) & GOOD_TYPES:
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="merge suggested matches into the map")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        print("Set GOOGLE_PLACES_API_KEY first (see docs/research/OWNER_SETUP_KEYS.md).")
        return 1

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    boats = conn.execute("SELECT name, landing FROM boats WHERE last_seen >= ? ORDER BY name",
                         ((date.today().replace(year=date.today().year - 2)).isoformat(),)).fetchall()
    landings = sorted({l for _, l in boats if l})
    jobs = [("landings", l, f"{l} {CITY.get(l, '')} sportfishing") for l in landings]
    jobs += [("boats", b, f"{b} sportfishing {l or ''} {CITY.get(l, '')}") for b, l in boats]
    if args.limit:
        jobs = jobs[: args.limit]

    results = {"boats": {}, "landings": {}}
    for group, name, q in jobs:
        try:
            cands = search(key, q)
        except requests.RequestException as e:
            print(f"  {name}: {e}")
            continue
        s = suggest(name, cands)
        results[group][name] = {"query": q, "suggested": s, "candidates": cands}
        print(f"  {group[:-1]:7s} {name:28s} -> {s['google_name'] if s else '(no confident match)'}")
        time.sleep(0.2)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")

    if args.apply:
        m = json.loads(MAP.read_text(encoding="utf-8"))
        n = 0
        for group in ("boats", "landings"):
            for name, r in results[group].items():
                if r["suggested"]:
                    m[group][name] = {"place_id": r["suggested"]["place_id"],
                                      "google_name": r["suggested"]["google_name"]}
                    n += 1
        m["updated"] = date.today().isoformat()
        MAP.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Merged {n} suggested matches into {MAP}. Check each one before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
