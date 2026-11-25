"""Per-region data files: data.js holds San Diego only; every other region's
rows go to web/data-region-<id>.js (src/export.py split_by_region), loaded on
demand by web/region-data.js. Both kinds of file must stay under the
Cloudflare Pages 25 MiB per-file limit (export raises past 24 MiB).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src import export as E

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LIMIT = E.MAX_FILE_MIB * 1024 * 1024


def _trip(i, region, landing, date="2026-11-20", prelim=False):
    return {"id": i, "date": date, "boat": f"B{i}", "landing": landing, "region": region,
            "tripLength": "Full Day", "tripLengthDays": 1, "anglers": 20, "Bluefin": 0, "Yellowfin": 1,
            "Yellowtail": 0, "Dorado": 0, "Skipjack": 0, "Bigeye": 0, "Albacore": 0,
            "trophyCount": 1, "trophyPerAngler": 0.05, "trophyPerAnglerPerDay": 0.05,
            "isPreliminary": prelim}


def _sample():
    rows = [_trip(1, "san_diego", "H&M Landing"), _trip(2, "oc_la", "Newport Landing"),
            _trip(3, "oc_la", "Pierpoint Landing"), _trip(4, "sf_bay", "Emeryville Sportfishing"),
            _trip(5, "oc_la", "Newport Landing", prelim=True)]
    trips = [t for t in rows if not t["isPreliminary"]]
    half = [_trip(10, "oc_la", "Dana Wharf Sportfishing"), _trip(11, "san_diego", "Seaforth Sportfishing")]
    sched = [{"landing": "22nd Street Landing", "boat": "Pursuit", "departureAt": "2026-12-01T05:00:00-08:00"},
             {"landing": "H&M Landing", "boat": "Excel", "departureAt": "2026-12-01T05:00:00-08:00"}]
    return rows, trips, half, sched


LANDING_REGION = {"22nd Street Landing": "oc_la"}   # schedule-only landing in the sample


def test_split_keeps_only_base_region_in_data_js():
    base, region_js, files = E.split_by_region(*_sample(), LANDING_REGION)
    assert {t["region"] for t in base["TRIPS"] + base["HALF_DAY_TRIPS"]} == {"san_diego"}
    assert [s["boat"] for s in base["SCHEDULE"]] == ["Excel"]
    # Every non-base region gets its own file — SF Bay needs no code change.
    assert set(region_js) == set(files) == {"oc_la", "sf_bay"}
    assert files["oc_la"]["file"] == "data-region-oc_la.js" and files["oc_la"]["tripCount"] == 2


def test_region_file_defines_its_data_and_hash_is_content_based():
    _, region_js, files = E.split_by_region(*_sample(), LANDING_REGION)
    text = region_js["oc_la"]
    m = re.search(r'\(window\.SD_REGIONS = window\.SD_REGIONS \|\| \{\}\)\["oc_la"\] = (.*);\n$', text)
    assert m, text[:200]
    payload = json.loads(m.group(1))
    assert {t["id"] for t in payload["TRIPS"]} == {2, 3}
    assert [t["id"] for t in payload["HALF_DAY_TRIPS"]] == [10]
    # Schedule rows have no region field: mapped through the landing's trips / LANDINGS_META.
    assert [s["boat"] for s in payload["SCHEDULE"]] == ["Pursuit"]
    assert payload["TODAY"]["stillFishing"][0]["landing"] == "Newport Landing"
    _, region_js2, files2 = E.split_by_region(*_sample(), LANDING_REGION)
    assert files2["oc_la"]["v"] == files["oc_la"]["v"]


def test_region_extras_go_only_to_that_region_file():
    cond = {"points": {"Catalina Channel": {"lat": 33.55, "lng": -118.35}}, "landingPoint": {}, "daily": []}
    _, region_js, _ = E.split_by_region(*_sample(), LANDING_REGION, {"oc_la": {"CONDITIONS": cond}})
    assert '"CONDITIONS":{"points":{"Catalina Channel"' in region_js["oc_la"]
    assert "CONDITIONS" not in region_js["sf_bay"]


def test_size_guard_raises(tmp_path, monkeypatch):
    f = tmp_path / "data-region-oc_la.js"
    f.write_bytes(b"x" * 2048)
    monkeypatch.setattr(E, "MAX_FILE_MIB", 1 / 1024)   # 1 KiB
    with pytest.raises(RuntimeError, match="data-region-oc_la.js"):
        E._check_file_size(f)


@pytest.mark.parametrize("path", [WEB / "data.js", *sorted(WEB.glob("data-region-*.js"))],
                         ids=lambda p: p.name)
def test_live_data_files_under_cloudflare_limit(path):
    if not path.exists():
        pytest.skip(f"{path.name} not generated")
    assert path.stat().st_size < LIMIT, f"{path.name} is {path.stat().st_size / 2**20:.1f} MiB"


def test_live_data_js_lists_existing_region_files():
    data_js = WEB / "data.js"
    if not data_js.exists():
        pytest.skip("data.js not generated")
    head = data_js.read_text(encoding="utf-8")
    m = re.search(r'"REGION_FILES":(\{.*?\}\})', head)
    if not m:
        pytest.skip("data.js predates the per-region split")
    for reg, f in json.loads(m.group(1)).items():
        assert (WEB / f["file"]).exists(), f"data.js lists {f['file']} but it is missing"
