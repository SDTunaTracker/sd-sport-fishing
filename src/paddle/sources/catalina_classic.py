"""Catalina Classic results from the organiser's own site (catalinaclassicpaddleboardrace.com).

robots.txt allows everything and the site has no terms page (checked 2026-11-27).
Years with an inline results table on the organiser's site are read from it
(2018, 2019, 2021-2023). 2014, 2015 and 2017 are PDFs on the same site; those were
transcribed once into data/paddle/imports/catalina-classic-<year>.csv (name,
division, craft, time, source only) and are imported from there. 2016's PDF has
times cut to tenths of a minute and split name columns, so it is not imported.
2020 was not raced. 2024 onward are hosted on Webscorer, whose terms forbid
scraping, so those are not fetched.

Kept per finisher: name, division ("Stock Men", "Unlimited Women", from the
table's class and gender columns), craft, time, and place and field size
WITHIN that division (computed from the finish times). Age, hometown, race
number and "previous finishes" columns are ignored. DNF/DNS rows are skipped.

    python -m src.paddle.sources.catalina_classic [--years 2018 2019 2021] [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys

from bs4 import BeautifulSoup

from .. import course as CO
from .. import results as RS
from ..importer import import_rows
from . import Blocked, polite_get

BASE = "https://catalinaclassicpaddleboardrace.com"
YEARS = (2018, 2019, 2021, 2022, 2023)          # inline tables on the organiser's site
PDF_YEARS = (2014, 2015, 2017)                    # organiser PDFs, transcribed to data/paddle/imports/
CLASS = {"s": "Stock", "stock": "Stock", "u": "Unlimited", "ul": "Unlimited", "unlimited": "Unlimited", "unl": "Unlimited"}
SEX = {"m": "Men", "male": "Men", "f": "Women", "female": "Women", "w": "Women"}
CRAFT = {"Stock": "Prone stock", "Unlimited": "Prone unlimited"}
TRANSCRIBED = CO.ROOT / "data" / "paddle" / "imports"
TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}(\.\d+)?$")
GARBLED_RE = re.compile(r"^\d{1,2}:\d{2}[.:]\d+$")


def url(year: int) -> str:
    return f"{BASE}/{year}-race-results/"


def nice(name: str) -> str:
    name = " ".join(name.split())
    if name.isupper() or name.islower():
        name = name.title()
        name = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), name)
    return name


def parse(html: str, source: str) -> list[dict]:
    """Finisher rows from one year's page (division place/field computed)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []
    trs = table.find_all("tr")
    head = [c.get_text(" ", strip=True).lower() for c in trs[0].find_all(["th", "td"])]

    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return None
    i_time, i_name = col("time"), col("name")
    i_first, i_last = col("first name", "first"), col("last name", "last")
    i_class, i_sex = col("class", "s/u"), col("gender", "m/f")
    i_notes, i_place = col("notes"), col("place")
    out = []
    for tr in trs[1:]:
        c = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(c) < len(head) - 1 or i_time is None:
            continue
        t = fix_time(c[i_time] if i_time < len(c) else "")
        notes = (c[i_notes] if i_notes is not None and i_notes < len(c) else "").lower()
        if "dnf" in notes or "dns" in notes or "dq" in notes or "dnf" in t.lower():
            continue
        overall = _place(c[i_place]) if i_place is not None and i_place < len(c) else None
        if not TIME_RE.match(t):
            # "05:55.1": a finisher (real place) whose time cell is garbled -> keep, without a time.
            # "Unofficial Time", "DNF", place 999 and anything else with words -> not a finisher.
            if overall is None or overall >= 900 or not GARBLED_RE.match(t):
                continue
            t = None
        name = c[i_name] if i_name is not None else f"{c[i_first]} {c[i_last]}"
        klass = CLASS.get((c[i_class] if i_class is not None else "").strip().lower())
        sex = SEX.get((c[i_sex] if i_sex is not None else "").strip().lower())
        if not name.strip() or not klass:
            continue
        out.append({"name": nice(name), "division": f"{klass} {sex}" if sex else klass, "craft": CRAFT[klass],
                    "time": t, "source": source, "_overall": overall})
    return divisional(out)


def fix_time(t: str) -> str:
    """'5:48 32' (a missing colon in the source table) -> '5:48:32'."""
    t = " ".join((t or "").split())
    return re.sub(r"^(\d{1,2}:\d{2}) (\d{2})$", r"\1:\2", t)


def _place(v):
    try:
        return int(str(v).strip().rstrip("."))
    except ValueError:
        return None


def divisional(rows: list[dict]) -> list[dict]:
    """Place and field WITHIN each division: by finish time, or by the source's overall order
    when a finisher's time is missing (garbled in the source)."""
    by_div: dict[str, list[dict]] = {}
    for r in rows:
        by_div.setdefault(r["division"], []).append(r)
    for rs in by_div.values():
        if all(r.get("time") for r in rs):
            rs.sort(key=lambda r: RS.seconds(r["time"]))
        elif all(r.get("_overall") for r in rs):
            rs.sort(key=lambda r: r["_overall"])
        else:
            rs.sort(key=lambda r: RS.seconds(r["time"]) if r.get("time") else float("inf"))
        for n, r in enumerate(rs, 1):
            r["place"], r["field"] = str(n), str(len(rs))
    for r in rows:
        r.pop("_overall", None)
    return rows


def read_transcribed(year: int) -> list[dict]:
    """PDF-only years: rows transcribed from the organiser's PDF into data/paddle/imports/ (same fields)."""
    import csv
    f = TRANSCRIBED / f"catalina-classic-{year}.csv"
    with open(f, newline="", encoding="utf-8") as fh:
        rows = [{k: (v or None) for k, v in r.items()} for r in csv.DictReader(fh)]
    for n, r in enumerate(rows, 1):
        r["_overall"] = n           # the PDFs list finishers in overall order
    return divisional(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--years", type=int, nargs="*", default=list(PDF_YEARS + YEARS))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    total = {}
    for y in a.years:
        try:
            rows = read_transcribed(y) if y in PDF_YEARS else parse(polite_get(url(y)), url(y))
        except Blocked as e:
            print(e)
            return 1
        if not rows:
            print(f"{y}: no inline results table")
            continue
        if a.dry_run:
            print(f"{y}: {len(rows)} finishers")
            continue
        rep = import_rows(rows, f"catalina-classic-{y}", "main", url(y), prone_only=True, add_new=True)
        total[y] = rep
        print(f"{y}: {len(rows)} finishers ->", ", ".join(f"{k} {v}" for k, v in rep.items()))
    if total:
        pub = RS.build()
        print(f"paddle_people.json: {len(pub['paddlers'])} paddlers, {len(pub['results'])} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
