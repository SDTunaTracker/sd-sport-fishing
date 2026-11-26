"""Tests for the prerendered SEO pages and the sitemap built from them."""
import sqlite3
from pathlib import Path

from src.export import _write_sitemap
from src.generate_pages import _dedupe_repeats, generate_all_pages

INDEX_HTML = """<!doctype html><html><head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-TEST"></script>
<script>gtag('config', 'G-TEST');</script>
<link href="https://fonts.googleapis.com/css2?family=Inter&display=swap" rel="stylesheet">
<link rel="stylesheet" href="styles.css?v=1"><link rel="stylesheet" href="design-system.css?v=2">
</head><body><div id="root"></div>
<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
<script src="data.js?v=9"></script>
<script src="dist/app.js?v=3"></script>
</body></html>"""


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("""CREATE TABLE trips (
        id INTEGER PRIMARY KEY, date TEXT, boat TEXT, landing TEXT, trip_length TEXT,
        anglers INTEGER, bluefin INTEGER, yellowfin INTEGER, yellowtail INTEGER,
        dorado INTEGER, trophy_count INTEGER, trophy_per_angler_per_day REAL,
        full_catch TEXT)""")
    rows = []
    # "Big Boat": 6 trips, moved from Seaforth to H&M; last two rows repeat a 2-day count.
    for i, (d, landing) in enumerate([
        ("2026-06-01", "Seaforth Sportfishing"), ("2026-06-10", "H&M Landing"),
        ("2026-07-01", "H&M Landing"), ("2026-07-15", "H&M Landing"),
        ("2026-08-01", "H&M Landing"), ("2026-08-02", "H&M Landing"),
    ]):
        rows.append((d, "Big Boat (SD)", landing, "2 Day", 20, 0, 30, 5, 0, 35, 0.9))
    # "Tiny": 1 trip only -> noindex, kept out of the sitemap.
    rows.append(("2026-08-01", "Tiny", "H&M Landing", "Full Day", 10, 0, 0, 0, 0, 0, 0.0))
    # "Far Boat": OC/LA landing -> no page, and no links to it from SD pages.
    for d in ("2026-07-20", "2026-07-25", "2026-07-30", "2026-07-31", "2026-08-01"):
        rows.append((d, "Far Boat", "Newport Landing", "Full Day", 20, 0, 40, 0, 0, 40, 2.0))
    conn.executemany("""INSERT INTO trips (date, boat, landing, trip_length, anglers, bluefin,
        yellowfin, yellowtail, dorado, trophy_count, trophy_per_angler_per_day)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
    return conn


def test_pages_and_sitemap(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    pages = generate_all_pages(_db(tmp_path), web, web / "index.html")

    by_url = {p["url"]: p for p in pages}
    big = by_url["/sd/boat/Big%20Boat%20%28SD%29/"]
    assert big == {"url": "/sd/boat/Big%20Boat%20%28SD%29/", "lastmod": "2026-08-02", "index": True}
    assert by_url["/sd/boat/Tiny/"]["index"] is False

    html = (web / "sd" / "boat" / "Big Boat (SD)" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en" data-prerendered="1">' in html
    assert '<link rel="canonical" href="https://thetunatracker.com/sd/boat/Big%20Boat%20%28SD%29/">' in html
    assert "H&amp;M Landing" in html.split("<title>")[1].split("</title>")[0]  # latest landing
    assert '"@type": "BreadcrumbList"' in html
    assert 'aria-hidden' not in html.split('<div id="root">')[0]
    assert "gtag/js?id=G-TEST" in html and "fonts.googleapis.com" in html
    # no-JS fallback is injected right after data.js
    assert '<script src="data.js?v=9"></script>\n<script>if(!window.SD)' in html
    # 2026-08-01 repeats 2026-08-02's identical 2-day count -> shown once
    assert html.count("<tr><td>Aug 2, 2026</td>") == 1
    assert "<tr><td>Aug 1, 2026</td>" not in html
    assert 'noindex' not in html
    assert 'name="robots" content="noindex, follow"' in (
        web / "sd" / "boat" / "Tiny" / "index.html").read_text(encoding="utf-8")

    landing = (web / "sd" / "landing" / "hm-landing" / "index.html").read_text(encoding="utf-8")
    assert "last 7 days" in landing
    # ranked boat (>= 5 trips) listed before the 1-trip boat
    assert landing.index("Big Boat (SD)</a></td><td>") < landing.index(">Tiny</a></td><td>")
    assert not (web / "sd" / "landing" / "seaforth").exists()  # boat moved away; no boats left

    _write_sitemap(web / "data.js", pages, "2026-08-02")
    sm = (web / "sitemap.xml").read_text(encoding="utf-8")
    assert "<loc>https://thetunatracker.com/sd/boat/Big%20Boat%20%28SD%29/</loc>" in sm
    assert "Tiny" not in sm
    assert "<loc>https://thetunatracker.com/sd/landing/hm-landing/</loc>" in sm
    assert "<changefreq>" not in sm
    assert sm.count("<loc>https://thetunatracker.com/sd/today</loc>") == 1
    assert "<loc>https://thetunatracker.com/sd/boats</loc>\n    <lastmod>2026-08-02" in sm


def test_today_boats_species_and_siblings(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    conn = _db(tmp_path)
    conn.execute("""INSERT INTO trips (date, boat, landing, trip_length, anglers, bluefin,
        yellowfin, yellowtail, dorado, trophy_count, trophy_per_angler_per_day)
        VALUES ('2026-08-02','Second Boat','H&M Landing','Full Day',10,0,1,0,0,1,0.1)""")
    conn.execute("""UPDATE trips SET full_catch='{"Rockfish": 2, "Yellowfin": 1}'
        WHERE boat='Second Boat'""")
    for d in ("2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"):
        conn.execute("""INSERT INTO trips (date, boat, landing, trip_length, anglers, bluefin,
            yellowfin, yellowtail, dorado, trophy_count, trophy_per_angler_per_day)
            VALUES (?,'Second Boat','H&M Landing','Full Day',10,0,0,0,0,0,0)""", (d,))
    pages = generate_all_pages(conn, web, web / "index.html")
    urls = {p["url"] for p in pages}
    assert {"/sd/today", "/sd/boats"} <= urls
    assert not (web / "sd" / "boat" / "Far Boat").exists()

    today = (web / "sd" / "today.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://thetunatracker.com/sd/today">' in today
    assert "San Diego fish counts for Aug 2, 2026" in today
    # Big Boat's Aug 1 row repeats its Aug 2 count -> listed once; Tiny's Aug 1 trip stays
    assert today.count(">Big Boat (SD)</a></td>") == 1
    assert "San Diego fish counts for Aug 1, 2026" in today and ">Tiny</a></td>" in today
    assert "Far Boat" not in today
    assert ">Second Boat</a></td><td>Full Day</td><td>10</td><td>2 rockfish, 1 yellowfin</td>" in today
    assert '<a href="/sd/landing/hm-landing/">H&amp;M Landing</a></h3>' in today

    boats = (web / "sd" / "boats.html").read_text(encoding="utf-8")
    assert '<a href="/sd/boat/Big%20Boat%20%28SD%29/">' in boats
    assert ">Tiny</a>" in boats and "Far Boat" not in boats

    species = (web / "sd" / "species" / "yellowfin-tuna" / "index.html").read_text(encoding="utf-8")
    assert "Far Boat" not in species
    assert "last 14 days" in species

    big = (web / "sd" / "boat" / "Big Boat (SD)" / "index.html").read_text(encoding="utf-8")
    assert "Other boats at H&amp;M Landing" in big and ">Second Boat</a>" in big
    assert ">Tiny</a>" not in big          # < 5 trips: not a sibling link


def test_dedupe_keeps_distinct_and_zero_trips():
    base = dict(boat="B", trip_length="2 Day", anglers=10, bluefin=0, yellowfin=5,
                yellowtail=0, dorado=0, trophy_count=5)
    rows = [dict(base, date="2026-08-03"), dict(base, date="2026-08-02"),
            dict(base, date="2026-07-01"),                       # same catch, weeks apart
            dict(base, date="2026-06-30", yellowfin=6, trophy_count=6),
            dict(base, date="2026-06-29", yellowfin=0, trophy_count=0),
            dict(base, date="2026-06-28", yellowfin=0, trophy_count=0)]  # zero days kept
    assert [r["date"] for r in _dedupe_repeats(rows)] == [
        "2026-08-03", "2026-07-01", "2026-06-30", "2026-06-29", "2026-06-28"]


def test_trip_length_pages(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    conn = _db(tmp_path)
    conn.execute("ALTER TABLE trips ADD COLUMN trophy_per_angler REAL")
    conn.execute("UPDATE trips SET trophy_per_angler = trophy_count * 1.0 / anglers")
    pages = {p["url"]: p for p in generate_all_pages(conn, web, web / "index.html")}

    assert pages["/sd/trips/2-day/"] == {"url": "/sd/trips/2-day/", "lastmod": "2026-08-02",
                                         "index": True}
    assert "/sd/trips/3-day/" not in pages               # no 3 Day trips in the data
    html = (web / "sd" / "trips" / "2-day" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://thetunatracker.com/sd/trips/2-day/">' in html
    assert "2 Day Fishing Trips in San Diego" in html
    assert "Far Boat" not in html                         # OC/LA trips excluded
    assert "not a forecast" in html
    # The SPA has no trips view (it would redirect to /sd/today), so the page
    # is static only, with the GA tag and a site nav
    assert 'id="root"' not in html and "unpkg.com/react" not in html
    assert "gtag/js?id=G-TEST" in html and 'href="/sd/boats">Boats</a>' in html
    # short dates with the year in the caption (all rows in one year), short
    # landing names for phones, captions outside the scroll box, 2 decimals
    assert "<td>Aug 2</td>" in html and "from San Diego landings, 2026</p>" in html
    assert '<span class="ls">H&amp;M</span>' in html
    assert '<p class="cap">' in html and "<caption>" not in html
    assert '<td class="num">1.75</td>' in html            # 35 fish / 20 anglers
    # Full Day page lists Tiny's trip but not the Newport boat
    full = (web / "sd" / "trips" / "full-day" / "index.html").read_text(encoding="utf-8")
    assert ">Tiny</a>" in full and "Far Boat" not in full
    # boat page links its trip length; /sd/today links the trip pages
    big = (web / "sd" / "boat" / "Big Boat (SD)" / "index.html").read_text(encoding="utf-8")
    assert '<li><a href="/sd/trips/2-day/">2 Day</a>: 6 trips</li>' in big
    assert '<a href="/sd/trips/overnight/">Overnight</a>' in (web / "sd" / "today.html").read_text(
        encoding="utf-8")


def test_stale_pages_pruned(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    ghost = web / "sd" / "boat" / "Ghost Boat"
    ghost.mkdir(parents=True)
    (ghost / "index.html").write_text("old", encoding="utf-8")
    keep = web / "sd" / "boat" / "not-a-page"           # no index.html: left alone
    keep.mkdir()
    generate_all_pages(_db(tmp_path), web, web / "index.html")
    assert not ghost.exists()
    assert keep.is_dir()
    assert (web / "sd" / "boat" / "Big Boat (SD)" / "index.html").is_file()


def test_prune_refuses_mass_delete(tmp_path):
    from src.generate_pages import _prune_stale
    boats = tmp_path / "sd" / "boat"
    for i in range(10):
        (boats / f"B{i}").mkdir(parents=True)
        (boats / f"B{i}" / "index.html").write_text("x", encoding="utf-8")
    # A run that only wrote 2 boat pages must not delete the other 8
    pages = [{"url": "/sd/boat/B0/"}, {"url": "/sd/boat/B1/"}]
    assert _prune_stale(tmp_path, pages) == []
    assert len(list(boats.iterdir())) == 10
