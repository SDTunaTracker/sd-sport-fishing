"""Past results from PaddleGuru race results pages (paddleguru.com/races/<slug>/results).

PaddleGuru's terms forbid automated access. The owner chose to collect the public
results pages anyway for this personal, non-commercial site (decision 2026-11-28,
same footing as the fishing-report scrapers). Limits that decision came with:
  - only the public /results page of each race and year: no login, no
    registration or participant pages, no search or API calls;
  - honest user agent, no proxies, nothing that gets past a CAPTCHA;
  - one request every 4 s, every page cached on disk and fetched once;
  - stop the whole run on any 403/429/5xx, CAPTCHA or block page (polite_get raises Blocked);
  - keep prone divisions only, and per finisher only name, division, craft, time,
    place and field within the division, race, year and the results URL.
    Usernames, user ids, race numbers, age bands and contacts in the page are ignored.

Which slugs to try for each race comes from the Wayback Machine index (archive.org,
not PaddleGuru) plus the year-swapped form of the slug already on the race list.
A page only counts when its race location is within MAX_KM of the race on our
list, so a same-named race somewhere else (Tahoe's "The Loop") is never mixed in.

    python -m src.paddle.sources.paddleguru [--series waterman-challenge the-loop] [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import re
import sys

from .. import course as CO
from .. import results as RS
from ..importer import PRONE, import_rows
from . import Blocked, polite_get

BASE = "https://paddleguru.com/races/"
YEARS = range(2014, 2027)
MAX_KM = 40
SLUGS = CO.ROOT / "data" / "paddle" / "paddleguru_slugs.json"   # series -> candidate slugs (from the Wayback index)


# ---- EDN (the page's embedded state) -------------------------------------------------------------
class _Edn:
    _num = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?[MN]?")
    _sym = re.compile(r"[^\s,()\[\]{}\"]+")

    def __init__(self, s: str):
        self.s, self.i = s, 0

    def ws(self):
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c in " \t\r\n,":
                self.i += 1
            elif c == ";":
                while self.i < n and s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def val(self):
        self.ws()
        s, c = self.s, self.s[self.i]
        if c == "{":
            self.i += 1
            out = {}
            while True:
                self.ws()
                if s[self.i] == "}":
                    self.i += 1
                    return out
                k = self.val()
                out[k if not isinstance(k, (list, dict)) else repr(k)] = self.val()
        if c in "([":
            end = ")" if c == "(" else "]"
            self.i += 1
            out = []
            while True:
                self.ws()
                if s[self.i] == end:
                    self.i += 1
                    return out
                out.append(self.val())
        if c == "#":
            if s[self.i + 1] == "{":
                self.i += 1
                v = self.val()
                return list(v.keys()) if isinstance(v, dict) else v
            if s[self.i + 1] == "_":
                self.i += 2
                self.val()
                return self.val()
            self.i += 1
            self._sym.match(s, self.i)
            self.i = self._sym.match(s, self.i).end()
            return self.val()                       # tagged literal: keep the value, drop the tag
        if c == '"':
            j, buf = self.i + 1, []
            while s[j] != '"':
                if s[j] == "\\":
                    nx = s[j + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nx, nx))
                    j += 2
                else:
                    buf.append(s[j])
                    j += 1
            self.i = j + 1
            return "".join(buf)
        m = self._num.match(s, self.i)
        if m and (c.isdigit() or (c == "-" and s[self.i + 1:self.i + 2].isdigit())):
            self.i = m.end()
            t = m.group().rstrip("MN")
            return float(t) if any(x in t for x in ".eE") else int(t)
        m = self._sym.match(s, self.i)
        self.i = m.end()
        t = m.group()
        return {"nil": None, "true": True, "false": False}.get(t, t[1:] if t.startswith(":") else t)


def edn(s: str):
    return _Edn(s).val()


def state(html: str) -> dict:
    m = re.search(r'<script id="state" type="application/edn">(.*?)</script>', html, re.S)
    if not m:
        raise Blocked("PaddleGuru page without its usual state block (block page?); stopping")
    return edn(m.group(1))


# ---- one results page -----------------------------------------------------------------------------
def results_url(slug: str) -> str:
    return f"{BASE}{slug}/results"


NOT_PRONE = re.compile(r"\bsup\b|stand|outrigger|\boc[- ]?\d|\bv1\b|\bski|kayak|canoe|foil|\brow|swim|\brun\b|tandem|relay", re.I)



MINORS = re.compile(r"kid|grom|youth|junior|keiki|\bu\d{1,2}\b|under 1\d|1\d and under|mini race", re.I)   # never stored


def craft(category: str, course: str = "") -> str | None:
    """Prone craft from the division name, read together with the course name: in a SUP or OC race
    "14' Men" is a stand-up board, so a course that names another craft needs the division to say prone."""
    c = (category or "").lower()
    if NOT_PRONE.search(c):
        return None
    if NOT_PRONE.search(course or "") and not re.search(r"prone|paddleboard|paddle board", f"{c} {course}", re.I):
        return None
    if "unl" in c or re.search(r"\bul\b", c):
        return "Prone unlimited"
    if "14" in c or "fourteen" in c:
        return "Prone 14'"
    if "stock" in c or "12" in c:
        return "Prone stock"
    if any(w in c for w in ("prone", "paddleboard", "paddle board", "kapuna", "kupuna", "women", "men", "junior", "grom")):
        return "Prone"
    return None


def division(category: str, gender: str | None) -> str:
    cat = re.sub(r"\s*\(.*?\)", "", category or "").strip()
    cat = re.sub(r"\bfourteen\b", "14'", cat, flags=re.I)
    sex = {"male": "Men", "female": "Women"}.get((gender or "").lower())
    if sex and not re.search(r"\b(men|women|male|female|ladies)\b", cat, re.I):
        return f"{cat} {sex}"
    return cat


def hms(ms) -> str | None:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    s = int(round(ms / 1000))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def parse(st: dict, url: str) -> dict | None:
    """{'title', 'date', 'lat', 'lon', 'races': {race name: [rows]}} or None when PaddleGuru has no such race."""
    ps = st.get("page-state") or {}
    if ps.get("status") == "error":
        return None
    start = (ps.get("dates") or {}).get("start")
    pos = (((ps.get("location") or {}).get("loc") or {}).get("position") or {})
    out = {"title": ps.get("title"), "date": dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc).date().isoformat() if start else None,
           "lat": pos.get("latitude"), "lon": pos.get("longitude"), "races": {}, "all": {}}
    for rname, block in (ps.get("startlist") or {}).items():
        rows = []
        if MINORS.search(rname):
            continue                                        # kids' / youth races: minors are never stored
        for e in (block or {}).get("entries") or []:
            res = e.get("result") or {}
            if res.get("status") != "timed":
                continue                                    # DNF/DNS/registered-only entries are not results
            names = [a.get("full-name") for a in e.get("athletes") or [] if a.get("full-name")]
            if len(names) != 1:
                continue                                    # relays and teams: not a single paddler
            dv = e.get("division") or {}
            cat = (dv.get("category") or {}).get("name") or ""
            cr = None if MINORS.search(cat) else craft(cat, rname)
            seen = out["all"].setdefault(rname, {})
            seen[f"{cat}{' -> ' + cr if cr else ''}"] = seen.get(f"{cat}{' -> ' + cr if cr else ''}", 0) + 1
            if cr not in PRONE:
                continue
            rank = res.get("rank") or {}
            rows.append({"name": " ".join(names[0].split()), "division": division(cat, dv.get("gender")), "craft": cr,
                         "time": hms(res.get("time")), "place": str(rank["division"]) if rank.get("division") else None,
                         "field": str(res["division-size"]) if res.get("division-size") else None, "source": url})
        if rows:
            out["races"][rname] = rows
    return out


# ---- series, slugs and race entries ---------------------------------------------------------------
def km(a, b, c, d) -> float:
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def candidates(series: str, races: list[dict]) -> list[str]:
    known = json.loads(SLUGS.read_text(encoding="utf-8")).get(series, []) if SLUGS.exists() else []
    out = list(known)
    for r in races:
        pg = r.get("paddleguru") or ""
        slug = pg.rsplit("/races/", 1)[-1] if "/races/" in pg else None
        if not slug:
            continue
        out.append(slug)
        if re.search(r"20\d\d", slug):
            out += [re.sub(r"20\d\d", str(y), slug) for y in YEARS]
    seen, uniq = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return uniq


def distance_for(race: dict, rname: str, courses: list[str]) -> dict:
    """Which of the race's distances a PaddleGuru course is: by miles, then long/short, then the
    main course (the only course, or one not marked short/fun). Unmatched courses get their own id."""
    ds = race.get("distances") or []
    name = rname.strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*-?\s*(mi\b|mile|km\b|k\b)", name, re.I)
    miles = float(m.group(1)) * (0.621 if m.group(2).lower().startswith("k") else 1) if m else None
    mi = round(miles, 1) if miles else None
    if miles:
        for d in ds:
            if d.get("miles") and abs(d["miles"] - miles) <= max(1.0, 0.15 * d["miles"]):
                return d
    for word in ("long", "short"):
        if re.search(rf"\b{word}\b", name, re.I):
            return next((d for d in ds if word in d["id"]),
                        {"id": word, "label": f"{word.title()} course", "miles": mi, "courseId": None})
    minor = re.compile(r"\bfun\b|sprint|\b[1-3]\s*-?\s*mile|\bmini\b", re.I)
    main_ok = len(courses) == 1 or not minor.search(name)
    if main_ok and len(ds) == 1:
        return ds[0]
    if main_ok and not ds:
        return {"id": "main", "label": "Main race", "miles": mi, "courseId": None}
    did = RS.slug(re.sub(r"\b20\d\d\b", "", name))[:40] or "main"
    return {"id": did, "label": name, "miles": mi, "courseId": None}


def ensure_race(races_doc: dict, series: str, year: int, date: str | None, slug: str) -> dict:
    rid = f"{series}-{year}"
    race = next((r for r in races_doc["races"] if r["id"] == rid), None)
    if race:
        if not race.get("paddleguru"):
            race["paddleguru"] = BASE + slug
        return race
    tmpl = min((r for r in races_doc["races"] if r.get("series") == series and r.get("year")),
               key=lambda r: abs(r["year"] - year))
    race = copy.deepcopy(tmpl)
    race.update(id=rid, year=year, date=date, startLocal=None, startNote=None, registration=None,
                paddleguru=BASE + slug, status="draft — confirm",
                notes=f"Past results from PaddleGuru ({BASE}{slug}/results). Details copied from {tmpl['id']}; confirm.")
    race.pop("results", None)
    races_doc["races"].append(race)
    return race


def dedupe(rows: list[dict]) -> list[dict]:
    """One page can list a finisher twice: a catch-all block ("Fun Course", "Prone") repeating the
    board-class result. Same name and same time -> keep the more specific row. Different times stay
    as they are, and the importer flags them for a person to resolve."""
    from ..importer import norm_name
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(norm_name(r["name"]), []).append(r)
    out = []
    for rs in by.values():
        if len(rs) > 1 and len({r["time"] for r in rs}) == 1:
            rs = [min(rs, key=lambda r: (r["craft"] == "Prone", bool(re.search(r"fun", r.get("distance") or ""))))]
        out += rs
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--series", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    doc = json.loads(CO.RACES.read_text(encoding="utf-8"))
    by_series: dict[str, list[dict]] = {}
    for r in doc["races"]:
        by_series.setdefault(r.get("series"), []).append(r)
    series_list = a.series or sorted(s for s, rs in by_series.items() if s and any(r.get("paddleguru") for r in rs))
    found: list[tuple] = []
    try:
        for s in series_list:
            ref = next((r for r in by_series[s] if (r.get("location") or {}).get("lat")), None)
            for slug in candidates(s, by_series[s]):
                url = results_url(slug)
                page = parse(state(polite_get(url, max_age_s=3650 * 86400)), url)
                if page is None:
                    continue
                far = ref and page["lat"] is not None and km(ref["location"]["lat"], ref["location"]["lon"], page["lat"], page["lon"]) > MAX_KM
                if far or not page["date"]:
                    print(f"  {s}: skip {slug} ({page['title']!r}, {'elsewhere' if far else 'no date'})")
                    continue
                n = sum(len(v) for v in page["races"].values())
                print(f"  {s}: {slug} {page['date']} -> {n} prone finishers")
                if a.dry_run:
                    for rn, cats in page["all"].items():
                        print(f"      {rn!r}: {cats}")
                found.append((s, slug, page))
    except Blocked as e:
        print(e)
        return 1
    if a.dry_run:
        return 0
    _, res_doc = RS.load(RS.SRC)
    other = {r["race"] for r in res_doc["results"] if "paddleguru.com" not in (r.get("source") or "")}
    seen_year: dict[tuple, str] = {}
    report = {}
    for s, slug, page in sorted(found, key=lambda x: (x[0], x[2]["date"])):
        year = int(page["date"][:4])
        if not page["races"]:
            report.setdefault((s, year), 0)
            continue
        if f"{s}-{year}" in other:
            print(f"  {s} {year}: already imported from an allowed source; PaddleGuru copy skipped")
            continue
        if (s, year) in seen_year and seen_year[(s, year)] != slug:
            print(f"  {s} {year}: {slug} duplicates {seen_year[(s, year)]}; skipped")
            continue
        seen_year[(s, year)] = slug
        race = ensure_race(doc, s, year, page["date"], slug)
        for rname, rows in page["races"].items():
            d = distance_for(race, rname, list(page["races"]))
            if not any(x["id"] == d["id"] for x in race.get("distances") or []):
                race.setdefault("distances", []).append(d)
            for r in rows:
                r["distance"] = d["id"]
        CO.RACES.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows = dedupe([r for v in page["races"].values() for r in v])
        rep = import_rows(rows, race["id"], None, results_url(slug), prone_only=True, add_new=True)
        report[(s, year)] = len(rows)
        print(f"{race['id']}: {len(rows)} prone finishers ->", ", ".join(f"{k} {v}" for k, v in rep.items()))
    if report:
        pub = RS.build()
        print(f"paddle_people.json: {len(pub['paddlers'])} paddlers, {len(pub['results'])} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
