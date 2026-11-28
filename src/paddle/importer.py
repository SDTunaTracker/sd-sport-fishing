"""Import race results from any allowed source (a CSV the owner drops in, or a source adapter).

    python -m src.paddle.results import-csv results.csv --race the-loop-2026 [--distance loop] \\
        [--source https://...] [--prone-only] [--add-new] [--full-results]

CSV columns (header names, case-insensitive; extra columns such as age or
hometown are ignored and never stored):
  name  (or first_name + last_name)   required
  division                            e.g. "Prone 14' Men 40-49"
  craft                               optional; worked out from the division when missing
  time                                h:mm:ss or mm:ss; rows without a time or place (DNF/DNS) are skipped
  place, field                        place within the division and division size
  race, distance, source              optional per row; otherwise from the command line

Matching a row to a person (no guessing):
  1. data/paddle/paddle_overrides.json "assign": [{"name", "race", "paddler"}]  (split / pick)
  2. normalised name (accents, case, punctuation, Jr/Sr ignored) or an "aliases" entry
     {"jon smith": "john-smith"}  (merge two spellings)
  3. exactly one match whose division history fits (prone / SUP / OC / surfski) → that person
     no match → new paddler with --add-new, else skipped ("not listed")
     several matches, history doesn't fit, or the same name twice in one race → NOT imported;
     written to data/paddle/paddle_ambiguous.json for a person to resolve with an override.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

from . import course as CO
from . import results as RS

OVERRIDES = "paddle_overrides.json"
AMBIGUOUS = "paddle_ambiguous.json"
PRONE = {"Prone stock", "Prone 14'", "Prone unlimited"}
SUFFIX = {"jr", "sr", "ii", "iii", "iv"}


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z\s-]", "", s).replace("-", " ")
    words = [w for w in s.split() if w not in SUFFIX]
    return " ".join(words)


def craft_of(division: str | None) -> str | None:
    d = (division or "").lower()
    if not d:
        return None
    if "sup" in d or "stand" in d:
        return "SUP"
    if re.search(r"\boc[- ]?6\b", d):
        return "OC6"
    if re.search(r"\boc[- ]?2\b", d):
        return "OC2"
    if re.search(r"\boc[- ]?1\b|outrigger", d):
        return "OC1"
    if "ski" in d:
        return "Surfski"
    if "unlimited" in d or re.search(r"\bunl\b", d):
        return "Prone unlimited"
    if "14" in d:
        return "Prone 14'"
    if "stock" in d or "12" in d:
        return "Prone stock"
    if "prone" in d or "paddleboard" in d:
        return "Prone stock" if "stock" in d else None
    return None


def family(craft: str | None) -> str:
    if craft in PRONE:
        return "prone"
    return {"SUP": "sup", "OC1": "oc", "OC2": "oc", "OC6": "oc", "Surfski": "ski"}.get(craft or "", "other")


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = []
        for raw in csv.DictReader(f):
            r = {re.sub(r"[^a-z]", "_", (k or "").strip().lower()).strip("_"): (v or "").strip() for k, v in raw.items()}
            name = r.get("name") or " ".join(x for x in (r.get("first_name"), r.get("last_name")) if x)
            rows.append({"name": name, **{k: r.get(k) or None for k in
                                          ("division", "craft", "time", "place", "field", "race", "distance", "source")}})
        return rows


def _int(v):
    try:
        return int(str(v).strip().rstrip("."))
    except (TypeError, ValueError):
        return None


def _load(src: Path, name: str, default: dict) -> dict:
    try:
        return json.loads((src / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _save(src: Path, name: str, doc: dict) -> None:
    src.mkdir(parents=True, exist_ok=True)
    (src / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_rows(rows: list[dict], race_id: str | None = None, distance: str | None = None, source: str | None = None, *,
                prone_only: bool = False, add_new: bool = False, full_results: bool = False,
                src: Path = RS.SRC, races_path: Path = CO.RACES) -> dict:
    races = {r["id"]: r for r in json.loads(races_path.read_text(encoding="utf-8"))["races"]}
    people, results = RS.load(src)
    ov = _load(src, OVERRIDES, {"aliases": {}, "assign": []})
    amb = _load(src, AMBIGUOUS, {"ambiguous": []})
    rep = {"added": 0, "updated": 0, "newPaddlers": 0, "notListed": 0, "notProne": 0, "dnf": 0, "ambiguous": 0}

    by_norm: dict[str, list[str]] = {}
    for p in people["paddlers"]:
        by_norm.setdefault(norm_name(p["name"]), []).append(p["id"])
    for alias, pid in (ov.get("aliases") or {}).items():
        by_norm.setdefault(norm_name(alias), [])
        if pid not in by_norm[norm_name(alias)]:
            by_norm[norm_name(alias)].append(pid)
    assign = {(norm_name(a["name"]), a["race"]): a["paddler"] for a in ov.get("assign") or []}
    history: dict[str, set[str]] = {}
    for r in results["results"]:
        history.setdefault(r["paddler"], set()).add(family(r.get("craft")))

    # complete each row: race, distance, craft, numbers
    prepared = []
    for row in rows:
        rid = row.get("race") or race_id
        race = races.get(rid)
        if not race:
            raise ValueError(f"unknown race {rid!r} for {row.get('name')!r}")
        dist = row.get("distance") or distance
        if not dist:
            ds = race.get("distances") or []
            dist = ds[0]["id"] if len(ds) == 1 else None
        craft = row.get("craft") if row.get("craft") in RS.CRAFTS else craft_of(row.get("division")) or craft_of(row.get("craft"))
        if not row.get("time") and not _int(row.get("place")):
            rep["dnf"] += 1
            continue
        if prone_only and craft not in PRONE:
            rep["notProne"] += 1
            continue
        prepared.append({"name": row["name"].strip(), "norm": norm_name(row["name"]), "race": rid, "distance": dist,
                         "division": row.get("division"), "craft": craft or "Other", "time": row.get("time") or None,
                         "place": _int(row.get("place")), "field": _int(row.get("field")),
                         "source": row.get("source") or source or race.get("paddleguru") or race.get("website")})
    if full_results:   # the file is a complete list: division size from it when missing
        size: dict[tuple, int] = {}
        for r in prepared:
            k = (r["race"], r["distance"], r["division"])
            size[k] = max(size.get(k, 0) + 1, r["place"] or 0)
        for r in prepared:
            r["field"] = r["field"] or size[(r["race"], r["distance"], r["division"])]
    twice: dict[tuple, int] = {}
    for r in prepared:
        twice[(r["norm"], r["race"])] = twice.get((r["norm"], r["race"]), 0) + 1

    flagged = []
    for r in prepared:
        why, pid = None, assign.get((r["norm"], r["race"]))
        if not pid:
            cands = by_norm.get(r["norm"], [])
            if twice[(r["norm"], r["race"])] > 1:
                why = "same name twice in this race"
            elif len(cands) > 1:
                why = "several paddlers share this name"
            elif len(cands) == 1:
                hist = history.get(cands[0])
                if hist and family(r["craft"]) not in hist:
                    why = "name matches, but division history differs"
                else:
                    pid = cands[0]
            elif add_new:
                pid = RS.slug(r["name"])
                n = 2
                while any(p["id"] == pid for p in people["paddlers"]):
                    pid = f"{RS.slug(r['name'])}-{n}"
                    n += 1
                people["paddlers"].append({"id": pid, "name": r["name"], "hidden": False, "crew": False, "note": None})
                by_norm.setdefault(r["norm"], []).append(pid)
                rep["newPaddlers"] += 1
            else:
                rep["notListed"] += 1
                continue
        if why:
            flagged.append({"name": r["name"], "race": r["race"], "division": r["division"], "reason": why,
                            "candidates": by_norm.get(r["norm"], [])})
            continue
        row = {k: r[k] for k in ("race", "distance", "division", "craft", "time", "place", "field", "source") if r[k] is not None}
        row = {"paddler": pid, **row}
        hit = next((i for i, x in enumerate(results["results"])
                    if (x["paddler"], x["race"], x.get("distance")) == (pid, r["race"], r["distance"])), None)
        if hit is None:
            results["results"].append(row)
            rep["added"] += 1
        else:
            results["results"][hit] = row
            rep["updated"] += 1
        history.setdefault(pid, set()).add(family(r["craft"]))

    done = {r["race"] for r in prepared}
    amb["ambiguous"] = [a for a in amb.get("ambiguous", []) if a["race"] not in done] + flagged
    rep["ambiguous"] = len(flagged)
    errs = RS.check(people, results, {"races": list(races.values())})
    if errs:
        raise ValueError("import would leave bad data, nothing saved:\n" + "\n".join(errs[:20]))
    _save(src, RS.PADDLERS.name, people)
    _save(src, RS.RESULTS.name, results)
    _save(src, AMBIGUOUS, amb)
    if not (src / OVERRIDES).exists():
        _save(src, OVERRIDES, {"about": "aliases: other spelling -> paddler id (merge). assign: name + race -> paddler id (split / pick).",
                               "aliases": {}, "assign": []})
    return rep
