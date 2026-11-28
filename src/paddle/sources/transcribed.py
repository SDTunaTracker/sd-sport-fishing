"""Import results transcribed once from an organiser's own PDF into data/paddle/imports/<race-id>.csv.

Each CSV holds only: name, division, craft, time, place, field, source (place and
field within the division, as the organiser listed them). The file name is the
race id. Files without place/field columns belong to a source adapter that works
those out itself (catalina_classic.py) and are left alone here.

Transcribed so far (terms checked 2026-11-27):
  waterman-challenge-2015..2018  watermanchallenge.weebly.com results PDFs
                                 (organiser's own site; robots allows; no site terms)

    python -m src.paddle.sources.transcribed [--only waterman-challenge-2018] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys

from .. import results as RS
from ..importer import import_rows
from .catalina_classic import TRANSCRIBED


def files(only: list[str] | None = None):
    for f in sorted(TRANSCRIBED.glob("*.csv")):
        with open(f, newline="", encoding="utf-8") as fh:
            head = next(csv.reader(fh), [])
        if "place" in head and "field" in head and (not only or f.stem in only):
            yield f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    done = 0
    for f in files(a.only):
        with open(f, newline="", encoding="utf-8") as fh:
            rows = [{k: (v or None) for k, v in r.items()} for r in csv.DictReader(fh)]
        if a.dry_run:
            print(f"{f.stem}: {len(rows)} rows")
            continue
        rep = import_rows(rows, f.stem, "main", prone_only=True, add_new=True)
        print(f"{f.stem}: {len(rows)} rows ->", ", ".join(f"{k} {v}" for k, v in rep.items()))
        done += 1
    if done:
        pub = RS.build()
        print(f"paddle_people.json: {len(pub['paddlers'])} paddlers, {len(pub['results'])} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
