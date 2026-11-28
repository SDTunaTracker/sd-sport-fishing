"""Paddler profiles and race results: entered by hand, imported from a CSV, or from an allowed
source adapter (src/paddle/sources/). PaddleGuru, Webscorer and Athlinks forbid scraping.

Source files (hand-edited, NOT deployed; data/ is outside web/):
  data/paddle/paddle_paddlers.json  {"paddlers": [{"id", "name", "hidden", "crew", "note"}]}
  data/paddle/paddle_results.json   {"results": [{"paddler", "race", "distance", "division", "craft",
                                                   "time", "place", "field", "source"}]}
Public file (built from them, hidden paddlers and their results removed):
  web/api/v1/paddle_people.json

Rules:
  * Only paddlers the owner has listed. Only what public results show: name,
    division, craft class, time, place, field size, race and year.
  * `hidden: true` removes the person and every result of theirs from the site.
  * Rows entered by hand use a paddler id. Imports match by normalised name and flag
    anything ambiguous instead of merging (see importer.py).

    python -m src.paddle.results add-paddler "First Last" [--crew]
    python -m src.paddle.results add --paddler first-last --race the-loop-2026 --distance loop \\
        --division "Prone 14' Men 40-49" --craft "Prone 14'" --time 2:05:31 --place 3 --field 12 \\
        --source https://paddleguru.com/races/THELOOP2026/results
    python -m src.paddle.results hide first-last        # or: unhide
    python -m src.paddle.results build                  # rewrite the public file (add/hide do this too)
    python -m src.paddle.results check
    python -m src.paddle.results import-csv FILE --race RACE_ID [--distance D] [--source URL]         [--prone-only] [--add-new] [--full-results]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from . import course as CO

SRC = CO.ROOT / "data" / "paddle"
PADDLERS = SRC / "paddle_paddlers.json"
RESULTS = SRC / "paddle_results.json"
OUT = CO.ROOT / "web" / "api" / "v1" / "paddle_people.json"
CRAFTS = ["Prone stock", "Prone 14'", "Prone unlimited", "SUP", "OC1", "OC2", "OC6", "Surfski", "Other"]
CONTACT = "mailto:thetunatracker@gmail.com?subject=Remove%20my%20paddle%20profile"
TIME_RE = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)(\.\d+)?$|^([0-5]?\d):([0-5]\d)(\.\d+)?$")


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def seconds(t: str) -> float:
    m = TIME_RE.match(t.strip())
    if not m:
        raise ValueError(f"time {t!r} is not h:mm:ss or mm:ss")
    if m.group(1) is not None:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + float(m.group(4) or 0)
    return int(m.group(5)) * 60 + int(m.group(6)) + float(m.group(7) or 0)


def _read(path: Path, key: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {key: []}


def load(src: Path = SRC) -> tuple[dict, dict]:
    return _read(src / PADDLERS.name, "paddlers"), _read(src / RESULTS.name, "results")


def check(people: dict, results: dict, races: dict) -> list[str]:
    errs = []
    ids = [p.get("id") for p in people.get("paddlers", [])]
    if len(ids) != len(set(ids)):
        errs.append("duplicate paddler id")
    for p in people.get("paddlers", []):
        if not p.get("id") or not p.get("name"):
            errs.append(f"paddler needs id and name: {p}")
        elif p["id"] != slug(p["id"]):
            errs.append(f"paddler id {p['id']!r} must be lower-case-dashes")
    by_race = {r["id"]: r for r in races.get("races", [])}
    seen = set()
    for n, r in enumerate(results.get("results", [])):
        where = f"result {n + 1} ({r.get('paddler')}, {r.get('race')})"
        if r.get("paddler") not in ids:
            errs.append(f"{where}: unknown paddler")
        race = by_race.get(r.get("race"))
        if not race:
            errs.append(f"{where}: unknown race")
        elif r.get("distance") not in {d["id"] for d in race.get("distances", [])} | {None}:
            errs.append(f"{where}: race has no distance {r.get('distance')!r}")
        key = (r.get("paddler"), r.get("race"), r.get("distance"))
        if key in seen:
            errs.append(f"{where}: duplicate result")
        seen.add(key)
        if r.get("craft") not in CRAFTS:
            errs.append(f"{where}: craft {r.get('craft')!r} (one of {', '.join(CRAFTS)})")
        if r.get("time"):
            try:
                seconds(r["time"])
            except ValueError as e:
                errs.append(f"{where}: {e}")
        pl, fl = r.get("place"), r.get("field")
        if pl is not None and (not isinstance(pl, int) or pl < 1):
            errs.append(f"{where}: place {pl!r}")
        if fl is not None and (not isinstance(fl, int) or fl < 1 or (isinstance(pl, int) and pl > fl)):
            errs.append(f"{where}: field {fl!r} for place {pl!r}")
        src = r.get("source") or ""
        if src and not src.startswith("https://"):
            errs.append(f"{where}: source must be an https link")
        extra = set(r) - {"paddler", "race", "distance", "division", "craft", "time", "place", "field", "source"}
        if extra:
            errs.append(f"{where}: fields not allowed: {', '.join(sorted(extra))}")
    for p in people.get("paddlers", []):
        extra = set(p) - {"id", "name", "hidden", "crew", "note"}
        if extra:
            errs.append(f"paddler {p.get('id')}: fields not allowed: {', '.join(sorted(extra))}")
    return errs


def public(people: dict, results: dict) -> dict:
    """What the site may show: listed, not hidden."""
    shown = [p for p in people.get("paddlers", []) if not p.get("hidden")]
    ok = {p["id"] for p in shown}
    return {
        "about": "Paddlers listed by the site owner. Results typed in from public race results; each links to its source.",
        "remove": CONTACT,
        "crafts": CRAFTS,
        "paddlers": [{k: p.get(k) for k in ("id", "name", "crew", "note")} for p in shown],
        "results": [r for r in results.get("results", []) if r.get("paddler") in ok],
    }


def build(src: Path = SRC, out: Path = OUT, races_path: Path = CO.RACES) -> dict:
    people, results = load(src)
    errs = check(people, results, json.loads(races_path.read_text(encoding="utf-8")))
    if errs:
        raise ValueError("\n".join(errs))
    pub = public(people, results)
    out.write_text(json.dumps(pub, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return pub


def _save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paddler profiles and results (hand-entered)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add-paddler")
    p.add_argument("name")
    p.add_argument("--id")
    p.add_argument("--crew", action="store_true")
    p = sub.add_parser("add")
    for k in ("paddler", "race", "distance", "division", "craft", "time", "source"):
        p.add_argument("--" + k, required=k in ("paddler", "race", "craft"))
    p.add_argument("--place", type=int)
    p.add_argument("--field", type=int)
    for c in ("hide", "unhide"):
        sub.add_parser(c).add_argument("id")
    sub.add_parser("build")
    sub.add_parser("check")
    p = sub.add_parser("import-csv")
    p.add_argument("file")
    p.add_argument("--race")
    p.add_argument("--distance")
    p.add_argument("--source")
    p.add_argument("--prone-only", action="store_true")
    p.add_argument("--add-new", action="store_true", help="create profiles for names not listed yet")
    p.add_argument("--full-results", action="store_true", help="file lists every finisher (division size from it)")
    a = ap.parse_args(argv)
    people, results = load()
    if a.cmd == "add-paddler":
        pid = a.id or slug(a.name)
        if any(x["id"] == pid for x in people["paddlers"]):
            print(f"id {pid!r} exists; pass --id to add a different person with the same name")
            return 1
        people["paddlers"].append({"id": pid, "name": a.name, "hidden": False, "crew": a.crew, "note": None})
        _save(PADDLERS, people)
        print("added", pid)
    elif a.cmd == "add":
        row = {k: getattr(a, k) for k in ("paddler", "race", "distance", "division", "craft", "time", "place", "field", "source")}
        results["results"].append({k: v for k, v in row.items() if v is not None})
        errs = check(people, results, json.loads(CO.RACES.read_text(encoding="utf-8")))
        if errs:
            print("not saved:\n" + "\n".join(errs))
            return 1
        _save(RESULTS, results)
    elif a.cmd in ("hide", "unhide"):
        hit = [x for x in people["paddlers"] if x["id"] == a.id]
        if not hit:
            print(f"no paddler {a.id!r}")
            return 1
        hit[0]["hidden"] = a.cmd == "hide"
        _save(PADDLERS, people)
    elif a.cmd == "import-csv":
        from .importer import import_rows, read_csv
        rep = import_rows(read_csv(Path(a.file)), a.race, a.distance, a.source, prone_only=a.prone_only,
                          add_new=a.add_new, full_results=a.full_results)
        print("import:", ", ".join(f"{k} {v}" for k, v in rep.items()))
    elif a.cmd == "check":
        errs = check(people, results, json.loads(CO.RACES.read_text(encoding="utf-8")))
        print("\n".join(errs) or f"OK: {len(people['paddlers'])} paddlers, {len(results['results'])} results")
        return 1 if errs else 0
    pub = build()
    print(f"paddle_people.json: {len(pub['paddlers'])} paddlers, {len(pub['results'])} results shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
