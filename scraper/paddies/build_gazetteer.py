"""
Build data/banks.geojson from data/raw/swyc_spots.gpx.

Applies the operator's triage rules (rules 1-7). Every raw <wpt> becomes
a Feature. Derived group features are added on top. Prints a report so
the operator can verify centroids and collision handling.

Kinds:
  bank     — fishing spots, banks, reefs, kelp beds, canyons, etc.
  landmark — coastal harbors, lighthouses, points (matching-eligible).
  admin    — grid labels and boundary markers (NOT matching-eligible).
  group    — derived container features (Catalina, SCI, 9-mile, etc.).

Source: SWYC Anglers public spot list (Michael Mooradian).
        https://swycanglers.org/resources/local-offshore-fishing-spots/
"""
import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "raw" / "swyc_spots.gpx"
OUT = ROOT / "data" / "banks.geojson"

NS = {"g": "http://www.topografix.com/GPX/1/1"}

ATTRIBUTION = "Spot list courtesy SWYC Anglers"
SOURCE_URL = "https://swycanglers.org/resources/local-offshore-fishing-spots/"
SOURCE_CREDIT = "SWYC Anglers public spot list (Michael Mooradian)"

# Rule 1 group membership keywords (case-insensitive substring on raw name).
CATALINA_KEYWORDS = ["Catalina", "Avalon", "Isthmus", "Two Harbors"]
SCI_KEYWORDS = ["San Clemente", "Pyramid", "China Point", "Castle Rock", "Northwest Harbor"]

# Rule 4 special-case number groups (member-name regex + threshold 5 nm).
SPECIAL_NUMBER_GROUP_MEMBERS = {
    "500": re.compile(r"^\s*(upper|lower)\s+500\s*$", re.I),
    "60":  re.compile(r"^\s*(60|60\s*mile\s*bank(?:\s*\(middle\))?)\s*$", re.I),
}

# Rule 2 manual aliases (keyed by final feature id).
MANUAL_ALIASES = {
    "43-fathom-spot": ["43", "the 43", "43 spot", "43 fathom"],
    "the-corner": ["corner"],  # redundant with auto but explicit for clarity
}

LANDMARK_KEYWORDS = re.compile(
    r"\b(harbor|harbour|lighthouse|light|pier|jetty|breakwater|wharf|anchorage|beach|bay|"
    r"point conception|orange county line|slough)\b",
    re.I,
)
# Words that override a landmark hit and keep the feature classified as a fishing spot.
BANK_OVERRIDE = re.compile(
    r"\b(reef|bank|kelp|rockfish|spot|hardbottom|canyon|knuckle|ridge|hump|finger|trench|fathom)\b",
    re.I,
)


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^\w\s\-]", " ", s)
    s = re.sub(r"[\s_]+", "-", s.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def normalize(text: str) -> str:
    """Lower, strip leading 'the', collapse hyphens/whitespace, drop punctuation."""
    s = unicodedata.normalize("NFKD", text or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[-_]", " ", s)         # hyphens/underscores first
    s = re.sub(r"[^\w\s]", " ", s)      # drop other punctuation
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^the\s+", "", s)       # THEN strip leading "the"
    return s


def haversine_nm(lat1, lon1, lat2, lon2):
    R_NM = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def centroid(coords):
    if not coords:
        return None
    return (sum(c[0] for c in coords) / len(coords),
            sum(c[1] for c in coords) / len(coords))


def classify(name: str) -> str:
    n = name.lower()
    stripped = name.strip()
    if stripped.startswith("[") or n.startswith("area "):
        return "admin"
    if LANDMARK_KEYWORDS.search(n) and not BANK_OVERRIDE.search(n):
        return "landmark"
    return "bank"


def numbers_in(name: str) -> list[str]:
    return re.findall(r"\b(\d{2,4})\b", name)


def auto_aliases_generic(name: str) -> list[str]:
    s = name.lower()
    s = re.sub(r"\b(bank|spot|the)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s and s != name.lower().strip():
        return [s]
    return []


# ------------------------------------------------------------------------

def _known_landmark_suffix(lat, lon):
    """Assign a same-name-pair feature to a rough geographic bucket."""
    KNOWN = [
        ("catalina", 33.38, -118.40),
        ("sci", 32.90, -118.50),
        ("coronados", 32.40, -117.25),
        ("sd", 32.72, -117.17),
        ("la", 33.85, -118.30),
        ("channel-islands", 34.02, -119.75),
    ]
    return min(KNOWN, key=lambda k: haversine_nm(lat, lon, k[1], k[2]))[0]


def _rename(feat, new_id, by_id):
    old = feat["_id"]
    if old in by_id and by_id[old] is feat:
        del by_id[old]
    feat["_id"] = new_id
    by_id[new_id] = feat


def build():
    if not SRC.exists():
        print(f"ERROR: {SRC} not found", file=sys.stderr)
        sys.exit(2)

    tree = ET.parse(SRC)
    root = tree.getroot()
    wpts = root.findall(".//g:wpt", NS)

    # Step 1 — parse raw features
    feats = []
    used = defaultdict(int)
    for idx, w in enumerate(wpts):
        raw = (w.findtext("g:name", default="", namespaces=NS) or "").strip()
        lat, lon = float(w.get("lat")), float(w.get("lon"))
        if not raw:
            raw = f"Unnamed waypoint {idx}"
        base = slugify(raw) or f"wpt-{idx}"
        used[base] += 1
        uid = base if used[base] == 1 else f"{base}-{used[base]}"
        feats.append({
            "_raw_name": raw,
            "_id": uid,
            "_lat": lat, "_lon": lon,
            "_kind": classify(raw),
            "_aliases": set(),
            "_parent": None,
            "_source": "swyc",
            "_verify": False,
        })
    by_id = {f["_id"]: f for f in feats}

    # Step 2 — Cortes / Bishop Rock (rule 3)
    bishop = next((f for f in feats if f["_raw_name"] == "Cortez Bank (Bishop Rock)"), None)
    cortes = next((f for f in feats if f["_raw_name"] == "Cortes Bank"), None)
    if bishop and cortes:
        _rename(bishop, "bishop-rock", by_id)
        bishop["_parent"] = cortes["_id"]
        bishop["_aliases"].update(["bishop rock", "the bishop"])
        cortes["_aliases"].update(["cortes", "cortez", "cortez bank", "the cortes"])
    elif bishop:
        _rename(bishop, "bishop-rock", by_id)
        bishop["_aliases"].update(["bishop rock", "the bishop"])

    # Step 3 — Rule 4 special: derived groups for 500, 60
    number_group_ids = set()
    number_group_report = []
    for num, member_re in SPECIAL_NUMBER_GROUP_MEMBERS.items():
        members = [f for f in feats if f["_kind"] != "group" and member_re.match(f["_raw_name"])]
        if not members:
            continue
        coords = [(m["_lat"], m["_lon"]) for m in members]
        max_pair = 0.0
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                d = haversine_nm(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
                if d > max_pair:
                    max_pair = d
        cen = centroid(coords)
        ok = (len(members) >= 2 and max_pair <= 5.0)
        if ok:
            # If the group id collides with an existing raw feature, suffix the raw feature.
            if num in by_id and by_id[num]["_kind"] != "group":
                _rename(by_id[num], f"{num}-wpt", by_id)
            g = {
                "_raw_name": num,
                "_id": num,
                "_lat": cen[0], "_lon": cen[1],
                "_kind": "group",
                "_aliases": {num, f"the {num}"},
                "_parent": None,
                "_source": "derived",
                "_verify": False,
            }
            by_id[num] = g
            feats.append(g)
            for m in members:
                m["_parent"] = num
            number_group_ids.add(num)
        number_group_report.append((num, ok, max_pair, cen, [m["_id"] for m in members]))

    # Step 4 — Rule 5: exact same-name pairs
    pair_report = []
    suffixed_no_group_names = set()
    by_exact = defaultdict(list)
    for f in feats:
        if f["_kind"] == "group":
            continue
        by_exact[f["_raw_name"]].append(f)
    for name, members in by_exact.items():
        if len(members) < 2:
            continue
        coords = [(m["_lat"], m["_lon"]) for m in members]
        max_pair = max(
            haversine_nm(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
            for i in range(len(members)) for j in range(i + 1, len(members))
        )
        base = slugify(name)
        if max_pair <= 5.0:
            member_ids_before = [m["_id"] for m in members]
            if base in by_id and by_id[base] in members:
                _rename(by_id[base], f"{base}-a", by_id)
            cen = centroid(coords)
            g = {
                "_raw_name": name,
                "_id": base,
                "_lat": cen[0], "_lon": cen[1],
                "_kind": "group",
                "_aliases": {normalize(name)},
                "_parent": None,
                "_source": "derived",
                "_verify": False,
            }
            by_id[base] = g
            feats.append(g)
            for m in members:
                if m["_parent"] is None:
                    m["_parent"] = base
            pair_report.append((name, "grouped", max_pair, base,
                                member_ids_before, [m["_id"] for m in members]))
        else:
            # suffix by geography; bare name → null (no group)
            suffixed_no_group_names.add(name)
            member_ids_before = [m["_id"] for m in members]
            raw_suffixes = [_known_landmark_suffix(m["_lat"], m["_lon"]) for m in members]
            # if two members share the same bucket, use n/s split by latitude
            if len(members) == 2 and raw_suffixes[0] == raw_suffixes[1]:
                if members[0]["_lat"] >= members[1]["_lat"]:
                    raw_suffixes = [f"{raw_suffixes[0]}-n", f"{raw_suffixes[1]}-s"]
                else:
                    raw_suffixes = [f"{raw_suffixes[0]}-s", f"{raw_suffixes[1]}-n"]
            new_ids = []
            for m, suf in zip(members, raw_suffixes):
                new_id = f"{base}-{suf}"
                k = 1
                candidate = new_id
                while candidate in by_id and by_id[candidate] is not m:
                    k += 1
                    candidate = f"{new_id}-{k}"
                _rename(m, candidate, by_id)
                new_ids.append(candidate)
            pair_report.append((name, "suffixed", max_pair, None, member_ids_before, new_ids))

    # Step 5 — Rule 4 main: bare-number primary detection for non-special numbers
    number_primary = {}
    number_conflicts = []
    all_nums = set()
    for f in feats:
        if f["_kind"] == "group":
            continue
        for n in numbers_in(f["_raw_name"]):
            all_nums.add(n)
    for num in sorted(all_nums, key=int):
        if num in number_group_ids:
            continue
        candidates = []
        for f in feats:
            if f["_kind"] == "group":
                continue
            rn = f["_raw_name"].strip()
            # Rule 5 override: features whose raw name was rule-5-suffixed can't be primary
            if rn in suffixed_no_group_names:
                continue
            if rn == num:
                candidates.append(("exact", f))
            elif re.match(rf"^\s*{re.escape(num)}[\s(]", rn):
                candidates.append(("lead", f))
        if not candidates:
            continue
        exacts = [f for kind, f in candidates if kind == "exact"]
        leads = [f for kind, f in candidates if kind == "lead"]
        if len(exacts) == 1:
            primary = exacts[0]
        elif exacts:
            primary = exacts[0]
            number_conflicts.append((num, "multiple exact", [f["_id"] for _, f in candidates]))
        elif len(leads) == 1:
            primary = leads[0]
        else:
            # multiple leads → pick shortest (most number-like)
            leads.sort(key=lambda f: len(f["_raw_name"]))
            primary = leads[0]
            number_conflicts.append((num, "multiple leading-number", [f["_id"] for _, f in candidates]))
        number_primary[num] = primary["_id"]
        primary["_aliases"].update([num, f"the {num}"])
        # parenthetical mentions become children (parent=primary), unless already parented
        for f in feats:
            if f is primary or f["_kind"] == "group":
                continue
            rn = f["_raw_name"]
            if num in numbers_in(rn) and not re.match(rf"^\s*{re.escape(num)}[\s(]", rn) and rn.strip() != num:
                if f["_parent"] is None:
                    f["_parent"] = primary["_id"]

    # Step 6 — Rule 1: derived Catalina / SCI groups
    def matches_kw(f, keywords):
        n = f["_raw_name"].lower()
        return any(kw.lower() in n for kw in keywords)

    cat_matches = [f for f in feats if f["_kind"] in ("bank", "landmark") and matches_kw(f, CATALINA_KEYWORDS)]
    sci_matches = [f for f in feats if f["_kind"] in ("bank", "landmark") and matches_kw(f, SCI_KEYWORDS)]

    cat_ids = {f["_id"] for f in cat_matches}
    sci_ids = {f["_id"] for f in sci_matches}
    overlap_ids = cat_ids & sci_ids

    # Preliminary centroids from unambiguous members
    cat_only = [by_id[i] for i in (cat_ids - overlap_ids)]
    sci_only = [by_id[i] for i in (sci_ids - overlap_ids)]
    cat_cen_prelim = centroid([(f["_lat"], f["_lon"]) for f in cat_only])
    sci_cen_prelim = centroid([(f["_lat"], f["_lon"]) for f in sci_only])
    # Resolve overlap by proximity
    for fid in overlap_ids:
        f = by_id[fid]
        d_cat = haversine_nm(f["_lat"], f["_lon"], *cat_cen_prelim) if cat_cen_prelim else float("inf")
        d_sci = haversine_nm(f["_lat"], f["_lon"], *sci_cen_prelim) if sci_cen_prelim else float("inf")
        if d_cat <= d_sci:
            sci_ids.discard(fid)
        else:
            cat_ids.discard(fid)

    def add_group(gid, name, members, aliases, radius, source="derived", verify=False):
        coords = [(by_id[i]["_lat"], by_id[i]["_lon"]) for i in members if i in by_id]
        if not coords:
            return None
        cen = centroid(coords)
        if gid in by_id and by_id[gid]["_kind"] != "group":
            _rename(by_id[gid], f"{gid}-wpt", by_id)
        g = {
            "_raw_name": name,
            "_id": gid,
            "_lat": cen[0], "_lon": cen[1],
            "_kind": "group",
            "_aliases": set(aliases),
            "_parent": None,
            "_source": source,
            "_verify": verify,
            "_radius_override": radius,
        }
        by_id[gid] = g
        feats.append(g)
        for mid in members:
            if mid in by_id and by_id[mid]["_parent"] is None:
                by_id[mid]["_parent"] = gid
        return g

    # Catalina: derived centroid, but radius bumped to 10 nm (SCI/Catalina
    # are ~21 nm long each — a smaller circle misses the west end).
    catalina_group = add_group(
        "catalina", "Catalina", sorted(cat_ids),
        ["cat", "catalina", "catalina island"], 10,
    )
    # SCI: hand-placed anchor at island center (not the derived centroid,
    # which was pulled east by China Point / Castle Rock members).
    sci_group = add_group(
        "san-clemente-island", "San Clemente Island", sorted(sci_ids),
        ["si", "clemente", "san clemente island", "san clemente"], 10,
    )
    if sci_group is not None:
        sci_group["_lat"] = 32.90
        sci_group["_lon"] = -118.50
        sci_group["_source"] = "manual"
        sci_group["_verify"] = True

    # Step 7 — 9-mile-bank derived group
    n9 = next((f for f in feats if f["_raw_name"] == "9 Mile Bank (N)"), None)
    s9 = next((f for f in feats if f["_raw_name"] == "9 Mile Bank (S)"), None)
    nine_group = None
    if n9 and s9:
        mid = centroid([(n9["_lat"], n9["_lon"]), (s9["_lat"], s9["_lon"])])
        nine_group = {
            "_raw_name": "9 Mile Bank",
            "_id": "9-mile-bank",
            "_lat": mid[0], "_lon": mid[1],
            "_kind": "group",
            "_aliases": {"9 mile", "9-mile", "nine mile", "9 mile bank", "middle rock"},
            "_parent": None,
            "_source": "derived",
            "_verify": False,
            "_radius_override": 2,
        }
        by_id["9-mile-bank"] = nine_group
        feats.append(nine_group)
        n9["_parent"] = "9-mile-bank"
        s9["_parent"] = "9-mile-bank"
        # per rule 1: upper 9 → N, lower 9 → S
        n9["_aliases"].update(["upper 9", "upper nine"])
        s9["_aliases"].update(["lower 9", "lower nine"])

    # Step 8 — Coronado Islands (hand-placed)
    coronados = {
        "_raw_name": "Coronado Islands",
        "_id": "coronado-islands",
        "_lat": 32.40, "_lon": -117.25,
        "_kind": "group",
        "_aliases": {"coronados", "the islands", "north island", "south island",
                     "middle island", "coronado islands"},
        "_parent": None,
        "_source": "manual",
        "_verify": True,
        "_radius_override": 4,
    }
    by_id["coronado-islands"] = coronados
    feats.append(coronados)

    # Step 9 — Auto-alias generation (for non-numbered names)
    for f in feats:
        if f["_kind"] in ("group", "admin"):
            continue
        nums = numbers_in(f["_raw_name"])
        if not nums:
            for a in auto_aliases_generic(f["_raw_name"]):
                f["_aliases"].add(a)

    # Step 10 — apply manual aliases table (rule 2 etc.)
    for fid, aliases in MANUAL_ALIASES.items():
        if fid in by_id:
            by_id[fid]["_aliases"].update(aliases)

    # Step 10b — Rule 7: drop generic auto-aliases that collide with a
    # feature literally named that. The literal-name feature keeps the alias;
    # others lose it. (E.g., "Worm Bank"'s stripped alias "worm" is dropped
    # because "The Worm" literally is that.)
    literal_index = defaultdict(list)
    for f in feats:
        if f["_kind"] == "admin":
            continue
        key = normalize(f["_raw_name"])
        if key:
            literal_index[key].append(f["_id"])
    for f in feats:
        if f["_kind"] == "admin":
            continue
        my_literal = normalize(f["_raw_name"])
        to_drop = set()
        for a in list(f["_aliases"]):
            key = normalize(a)
            if not key:
                continue
            others = [i for i in literal_index.get(key, []) if i != f["_id"]]
            if others and key != my_literal:
                to_drop.add(a)
        f["_aliases"] -= to_drop

    # Step 11 — assemble output
    features_out = []
    for f in feats:
        props = {
            "id": f["_id"],
            "name": f["_raw_name"],
            "source_name": f["_raw_name"],
            "aliases": sorted(f["_aliases"]),
            "kind": f["_kind"],
            "radius_nm": _radius(f),
            "source": f["_source"],
            "parent": f["_parent"],
        }
        if f.get("_verify"):
            props["verify"] = True
        features_out.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [f["_lon"], f["_lat"]]},
            "properties": props,
        })

    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "attribution": ATTRIBUTION,
            "source_credit": SOURCE_CREDIT,
            "source_url": SOURCE_URL,
            "generated_from": "data/raw/swyc_spots.gpx",
            "feature_count": len(features_out),
        },
        "features": features_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fc, indent=2), encoding="utf-8")

    # Report ---------------------------------------------------------------
    print(f"wrote {OUT} ({len(features_out)} features)")

    counts = defaultdict(int)
    for feat in features_out:
        counts[feat["properties"]["kind"]] += 1
    print("\n=== counts by kind ===")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")

    print("\n=== derived group centroids (eyeball these) ===")
    for gid in ["catalina", "san-clemente-island", "9-mile-bank", "coronado-islands"]:
        g = by_id.get(gid)
        if g:
            member_count = sum(1 for x in feats if x["_parent"] == gid)
            note = " verify=True" if g.get("_verify") else ""
            print(f"  {gid}: lat={g['_lat']:.5f}  lon={g['_lon']:.5f}  "
                  f"members={member_count}  source={g['_source']}{note}")

    print("\n=== rule 4 special-case number groups (500, 60) ===")
    for num, ok, max_pair, cen, mids in number_group_report:
        status = "GROUPED" if ok else f"NOT GROUPED (max pair {max_pair:.2f} nm > 5)"
        print(f"  {num}: {status}  centroid=({cen[0]:.5f},{cen[1]:.5f})  members={mids}")

    print("\n=== rule 4 primary conflicts (multiple candidates) ===")
    if number_conflicts:
        for num, why, ids in number_conflicts:
            print(f"  {num}: {why} -> {ids}  (primary={number_primary.get(num)})")
    else:
        print("  (none)")

    print("\n=== rule 5 same-name pair outcomes ===")
    for name, mode, dist, gid, before, after in pair_report:
        print(f"  {name!r}: {mode} (max_pair {dist:.2f} nm)  ids: {before} -> {after}"
              + (f"  group={gid}" if gid else ""))

    # alias collisions (matching-eligible only: no admin)
    alias_index = defaultdict(list)
    for f in feats:
        if f["_kind"] == "admin":
            continue
        for candidate in [f["_raw_name"]] + list(f["_aliases"]):
            key = normalize(candidate)
            if key:
                alias_index[key].append(f["_id"])
    collisions = {k: sorted(set(v)) for k, v in alias_index.items() if len(set(v)) > 1}
    print("\n=== alias/name collisions (matching-eligible, excludes admin) ===")
    if collisions:
        for k, ids in sorted(collisions.items())[:80]:
            print(f"  {k!r} -> {ids}")
        if len(collisions) > 80:
            print(f"  ... and {len(collisions)-80} more")
    else:
        print("  (none)")


def _radius(f):
    if "_radius_override" in f:
        return f["_radius_override"]
    n = f["_raw_name"].lower()
    if f.get("_parent") == "catalina" or "catalina" in n:
        return 6
    if f.get("_parent") == "san-clemente-island" or "clemente" in n:
        return 6
    if "coronado" in n or "tanner" in n or re.search(r"\bcort(e|é)?[sz]\b", n):
        return 4
    return 2


if __name__ == "__main__":
    build()
