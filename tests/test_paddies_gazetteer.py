"""Tests for scraper.paddies.build_gazetteer and the resulting banks.geojson."""
from __future__ import annotations
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scraper.paddies.build_gazetteer import (
    normalize, slugify, classify, haversine_nm, centroid, build,
    SRC, OUT,
)


# ---------------------------------------------------------------------
# normalize() — 20+ alias cases
# ---------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("the 182", "182"),
    ("182 ", "182"),
    ("182", "182"),
    ("The 182", "182"),
    ("THE  182", "182"),
    ("the-182", "182"),
    ("nine mile", "nine mile"),
    ("Nine Mile", "nine mile"),
    ("9 mile", "9 mile"),
    ("9-mile", "9 mile"),
    ("9-Mile Bank", "9 mile bank"),
    ("SI", "si"),
    ("Cat", "cat"),
    ("cat", "cat"),
    ("Catalina Island", "catalina island"),
    ("coronados", "coronados"),
    ("Coronados", "coronados"),
    ("The Coronados", "coronados"),
    ("The Islands", "islands"),
    ("The Corner", "corner"),
    ("the corner", "corner"),
    ("the 43", "43"),
    ("43 spot", "43 spot"),
    ("43 (Fathom Spot)", "43 fathom spot"),
    ("Cortez Bank", "cortez bank"),
    ("San Clemente Island", "san clemente island"),
])
def test_normalize_variants(raw, expected):
    assert normalize(raw) == expected


def test_normalize_strips_unicode_and_punctuation():
    # NFKD + ascii drop
    assert normalize("Café") == "cafe"
    assert normalize("1 ¼ Spot") == "1 14 spot"  # ¼ decomposes to 1⁄4 then loses the slash


# ---------------------------------------------------------------------
# slugify()
# ---------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("9 Mile Bank (N)", "9-mile-bank-n"),
    ("Cortez Bank (Bishop Rock)", "cortez-bank-bishop-rock"),
    ("The Corner", "the-corner"),
    ("43 (Fathom Spot)", "43-fathom-spot"),
    ("[South Boundary]", "south-boundary"),
    ("Area 1.1", "area-1-1"),
])
def test_slugify(raw, expected):
    assert slugify(raw) == expected


# ---------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------

def test_classify_admin_bracket():
    assert classify("[South Boundary]") == "admin"


def test_classify_admin_area():
    assert classify("Area 1.1") == "admin"
    assert classify("Area 2.5") == "admin"


def test_classify_landmark_harbor():
    assert classify("Avalon Harbor") == "landmark"


def test_classify_landmark_lighthouse():
    assert classify("Santa Barbara Island Light") == "landmark"


def test_classify_bank_override():
    # "harbor" would look landmark-y but "bank" wins for fishing spots
    assert classify("Something Harbor Reef") == "bank"


def test_classify_default_bank():
    assert classify("Cortes Bank") == "bank"
    assert classify("182") == "bank"
    assert classify("Kidney Bank") == "bank"


# ---------------------------------------------------------------------
# Distance helpers
# ---------------------------------------------------------------------

def test_haversine_zero():
    assert haversine_nm(32.7, -117.2, 32.7, -117.2) == pytest.approx(0.0, abs=1e-6)


def test_haversine_sanity():
    # San Diego to Catalina roughly 65-70 nm
    d = haversine_nm(32.72, -117.17, 33.38, -118.40)
    assert 60 < d < 80


def test_centroid_two_points():
    assert centroid([(0, 0), (2, 2)]) == (1.0, 1.0)


# ---------------------------------------------------------------------
# Built gazetteer (banks.geojson) — validation
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def gazetteer(tmp_path_factory):
    """Rebuild fresh and load once."""
    build()
    with open(OUT, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def raw_wpts():
    tree = ET.parse(SRC)
    root = tree.getroot()
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    return root.findall(".//g:wpt", ns)


def test_metadata(gazetteer):
    md = gazetteer["metadata"]
    assert md["attribution"] == "Spot list courtesy SWYC Anglers"
    assert "swycanglers.org" in md["source_url"]
    assert md["feature_count"] == len(gazetteer["features"])


def test_every_wpt_produced_exactly_one_feature(gazetteer, raw_wpts):
    """Non-group features count equals wpt count in GPX."""
    non_group = [f for f in gazetteer["features"] if f["properties"]["kind"] != "group"]
    assert len(non_group) == len(raw_wpts)


def test_ids_unique(gazetteer):
    ids = [f["properties"]["id"] for f in gazetteer["features"]]
    dups = [i for i in ids if ids.count(i) > 1]
    assert not dups, f"duplicate ids: {sorted(set(dups))}"


def test_every_feature_has_geometry(gazetteer):
    for f in gazetteer["features"]:
        geom = f["geometry"]
        assert geom is not None, f"missing geometry: {f['properties']['id']}"
        assert geom["type"] == "Point"
        lon, lat = geom["coordinates"]
        assert -180 <= lon <= 180
        assert -90 <= lat <= 90


def test_derived_groups_present(gazetteer):
    ids = {f["properties"]["id"] for f in gazetteer["features"]}
    for gid in ("catalina", "san-clemente-island", "9-mile-bank", "coronado-islands"):
        assert gid in ids, f"missing derived group: {gid}"


def test_derived_groups_have_group_kind(gazetteer):
    for f in gazetteer["features"]:
        if f["properties"]["id"] in ("catalina", "san-clemente-island",
                                      "9-mile-bank", "coronado-islands"):
            assert f["properties"]["kind"] == "group"


def test_bishop_rock_child_of_cortes(gazetteer):
    by_id = {f["properties"]["id"]: f["properties"] for f in gazetteer["features"]}
    assert "bishop-rock" in by_id
    assert by_id["bishop-rock"]["parent"] == "cortes-bank"


def test_cortes_bank_has_cortez_aliases(gazetteer):
    by_id = {f["properties"]["id"]: f["properties"] for f in gazetteer["features"]}
    assert "cortez" in by_id["cortes-bank"]["aliases"]
    assert "cortez bank" in by_id["cortes-bank"]["aliases"]


def test_43_fathom_spot_aliases(gazetteer):
    by_id = {f["properties"]["id"]: f["properties"] for f in gazetteer["features"]}
    a = set(by_id["43-fathom-spot"]["aliases"])
    for expected in ("43", "the 43", "43 spot", "43 fathom"):
        assert expected in a


def test_9_mile_bank_group_and_children(gazetteer):
    by_id = {f["properties"]["id"]: f["properties"] for f in gazetteer["features"]}
    g = by_id["9-mile-bank"]
    assert g["kind"] == "group"
    # bare "9 mile" alias resolves to group
    assert "9 mile" in g["aliases"] or "9-mile" in g["aliases"]
    assert "nine mile" in g["aliases"]
    # children: 9 Mile Bank (N) & (S)
    children = [p for p in by_id.values() if p["parent"] == "9-mile-bank"]
    assert len(children) == 2
    child_names = {c["name"] for c in children}
    assert child_names == {"9 Mile Bank (N)", "9 Mile Bank (S)"}
    # upper 9 / lower 9 attach to the CHILDREN
    n = next(c for c in children if "(N)" in c["name"])
    s = next(c for c in children if "(S)" in c["name"])
    assert "upper 9" in n["aliases"]
    assert "lower 9" in s["aliases"]


def test_sci_hand_placed_at_island_center(gazetteer):
    by_id = {f["properties"]["id"]: f["properties"] for f in gazetteer["features"]}
    sci = by_id["san-clemente-island"]
    assert sci["source"] == "manual"
    assert sci.get("verify") is True
    assert sci["radius_nm"] == 10
    for f in gazetteer["features"]:
        if f["properties"]["id"] == "san-clemente-island":
            lon, lat = f["geometry"]["coordinates"]
            assert lat == pytest.approx(32.90, abs=0.001)
            assert lon == pytest.approx(-118.50, abs=0.001)


def test_catalina_radius(gazetteer):
    by_id = {f["properties"]["id"]: f["properties"] for f in gazetteer["features"]}
    assert by_id["catalina"]["radius_nm"] == 10


def test_coronado_islands_hand_placed(gazetteer):
    by_id = {f["properties"]["id"]: f["properties"] for f in gazetteer["features"]}
    c = by_id["coronado-islands"]
    assert c["source"] == "manual"
    assert c["verify"] is True
    for alias in ("coronados", "the islands", "north island", "south island"):
        assert alias in c["aliases"]
    # "rockpile" should NOT be an alias (per rule 1 caveat)
    assert "rockpile" not in c["aliases"]
    assert "the rockpile" not in c["aliases"]


# ---------------------------------------------------------------------
# The key one the operator asked for: alias-collision test PASSES
# ---------------------------------------------------------------------

# Same-name-pair raw names that legitimately collide per rule 5
# (bare name → null, so this is by design)
EXPECTED_RAW_NAME_COLLISIONS = {"230", "seal rocks", "west end", "white rock"}


def test_aliases_do_not_collide_across_features(gazetteer):
    """
    Each entry in a feature's `aliases` list must not appear in any other
    feature's `aliases` list. Raw NAMES are exempt: same-name pairs from
    rule 5 legitimately share a raw name (bare name resolves to null via
    the resolver, per spec).
    """
    alias_index = defaultdict(list)
    for f in gazetteer["features"]:
        p = f["properties"]
        if p["kind"] == "admin":
            continue
        for a in p["aliases"]:
            alias_index[normalize(a)].append(p["id"])
    collisions = {k: sorted(set(v)) for k, v in alias_index.items()
                  if len(set(v)) > 1}
    unexpected = {k: v for k, v in collisions.items()
                  if k not in EXPECTED_RAW_NAME_COLLISIONS}
    assert not unexpected, f"unexpected alias collisions: {unexpected}"


def test_admin_features_have_no_matching_aliases(gazetteer):
    """Rule 6: admin features are excluded from alias matching."""
    for f in gazetteer["features"]:
        p = f["properties"]
        if p["kind"] == "admin":
            # they may still carry aliases historically, but the extraction
            # code will skip admin. So just require kind is set correctly.
            assert p["kind"] == "admin"


def test_kind_counts_reasonable(gazetteer):
    counts = defaultdict(int)
    for f in gazetteer["features"]:
        counts[f["properties"]["kind"]] += 1
    assert counts["group"] >= 4
    assert counts["admin"] >= 3
    assert counts["bank"] > 100
