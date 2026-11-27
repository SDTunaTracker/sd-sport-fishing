"""
Coordinate parsing + offset resolution for fishing-report positions.

All parsing done in code — the model's lat/lon (if any) is only *verified*
by us, per the v2 spec:
  * regex-parse "raw" for DD / DDM / DMS forms
  * sanity box: SoCal offshore bounds
  * land test: reject if east of the mainland coastline
  * offsets: bearing + distance from a named bank, flat-earth approximation
"""
from __future__ import annotations

import math
import re

# ------------------------------------------------------------------ sanity

# Offshore SoCal bounding box (from spec). Wide enough to include Cortes /
# Tanner (west) and the SD Bight (east); does NOT extend into Baja.
SANITY_LAT_MIN, SANITY_LAT_MAX = 30.0, 34.6
SANITY_LON_MIN, SANITY_LON_MAX = -121.0, -116.5


def in_sanity_box(lat: float, lon: float) -> bool:
    return (SANITY_LAT_MIN <= lat <= SANITY_LAT_MAX and
            SANITY_LON_MIN <= lon <= SANITY_LON_MAX)


def on_land(lat: float, lon: float) -> bool:
    """
    Very coarse mainland test per spec: reject anything east of
    lon=-117.05 AND north of lat=32.5. Catches most of the SD mainland
    (Point Loma, Coronado, downtown, La Jolla, Del Mar…) without needing
    a real coastline polygon. Misses SD Bay, and lets Coronados / open
    ocean through — which is what we want.
    """
    return lon > -117.05 and lat > 32.5


# Wider box for long-range trip reports (Revillagigedos to Pt Conception).
WIDE_LAT_MIN, WIDE_LAT_MAX = 15.0, 35.0
WIDE_LON_MIN, WIDE_LON_MAX = -125.0, -105.0


def in_wide_box(lat: float, lon: float) -> bool:
    return WIDE_LAT_MIN <= lat <= WIDE_LAT_MAX and WIDE_LON_MIN <= lon <= WIDE_LON_MAX


def valid_offshore(lat: float, lon: float) -> bool:
    return in_sanity_box(lat, lon) and not on_land(lat, lon)


# ------------------------------------------------------------------ map pins
# Where a posted position is believable for the chart: offshore SoCal and
# northern Baja (Point Conception down to about Cedros / Guerrero Negro, 28 N).
PIN_LAT_MIN, PIN_LAT_MAX = 28.0, 34.6
PIN_LON_MIN = -122.0

# Mainland Pacific coast as (lat, lon), south to north. Latitude rises along
# the list, so "on land" is simply lon east of the coast at that latitude.
# Coarse on purpose (a few miles): it drops points on land or in the Gulf of
# California, not points just inside a harbour.
_COAST = [
    (28.00, -114.10), (28.60, -114.20), (29.00, -114.80), (29.60, -115.40),
    (30.00, -115.80), (30.40, -116.00), (30.90, -116.30), (31.40, -116.60),
    (31.86, -116.66), (32.20, -116.90), (32.53, -117.12), (32.70, -117.25),
    (32.85, -117.27), (33.10, -117.32), (33.40, -117.60), (33.60, -117.88),
    (33.72, -118.10), (33.75, -118.40), (33.90, -118.42), (34.03, -118.80),
    (34.08, -119.06), (34.27, -119.30), (34.40, -119.70), (34.45, -120.47),
    (34.60, -120.65),
]


def coast_lon(lat: float) -> float:
    pts = _COAST
    if lat <= pts[0][0]:
        return pts[0][1]
    for (a_lat, a_lon), (b_lat, b_lon) in zip(pts, pts[1:]):
        if lat <= b_lat:
            t = (lat - a_lat) / (b_lat - a_lat)
            return a_lon + t * (b_lon - a_lon)
    return pts[-1][1]


def in_pin_area(lat: float, lon: float) -> bool:
    """Offshore SoCal / northern Baja: inside the box and west of the mainland coast."""
    if not (PIN_LAT_MIN <= lat <= PIN_LAT_MAX and PIN_LON_MIN <= lon):
        return False
    return lon < coast_lon(lat)


# ------------------------------------------------------------------ normalise
# Forum posters write positions many ways. These rewrites turn the common
# variants into the forms the three patterns below already read:
#   "N32 50.639 W117 31.854"  hemisphere letters in front of the numbers
#   "32 40.5 / 117 30.2"      slash, semicolon or bar between lat and lon
#   "32-40.5 117-30.2"        dash between degrees and minutes

_NUM_PART = r"\d{1,3}(?:\.\d+)?°?(?:[\s\-]*\d{1,2}(?:\.\d+)?['′]?){0,2}[\"″]?"
_PREFIX_HEMI = re.compile(
    r"(?<![A-Za-z])([NS])\s*(" + _NUM_PART + r")\s*[,/;|]?\s*([EW])\s*(" + _NUM_PART + r")",
    re.I,
)
# "32-40.5" -> "32 40.5", but never touch a negative number like ", -117.5".
_DEG_DASH = re.compile(r"(?<![\d.])(\d{2,3})-(\d{1,2}(?:\.\d+)?)(?!\d)")
_PAIR_SEP = re.compile(r"(?<=[\d'′\"″°NSns])\s*[/;|]\s*(?=[\d\-NSEWnsew])")


def normalise(raw: str) -> str:
    s = raw.replace("º", "°").replace("˚", "°")
    s = _PREFIX_HEMI.sub(
        lambda m: f"{m.group(2).strip()} {m.group(1).upper()} {m.group(4).strip()} {m.group(3).upper()}", s)
    s = _DEG_DASH.sub(r"\1 \2", s)
    s = _PAIR_SEP.sub(" ", s)
    return s


# ------------------------------------------------------------------ parsers

# Hemisphere suffix (N/S/E/W), optionally spaced from the number.
# We keep this outside the lat/lon subpatterns so tests can see the group order.
_HEMI = r"(?:\s*([NSEW]))?"

# Key trick to avoid mis-parsing:
# - Degrees pattern uses `(?![\d.])` after the digits: an integer degrees value
#   can NOT be followed by another digit or a decimal point, or we'd be
#   stealing part of a DD-form number like "32.4083".
# - Every "number end" that could otherwise slip into a DD reading gets the
#   same trailing lookahead.

# DMS: 32°24'30" N  117°18'06" W  — symbols are OPTIONAL so space-separated
# form "32 24 30 N 117 18 06 W" also parses. Requires 3 integer groups per side.
_DMS = re.compile(
    r"""
    (?:^|[^\d.\-])                              # non-numeric boundary
    (\d{1,3})(?![\d.])\s*(?:[°d]|deg)?\s*       # degrees
    (\d{1,2})(?![\d.])\s*(?:['m′]|min|')?\s*    # minutes (the `(?![\d.])` on the digits blocks glomming)
    (\d{1,2}(?:\.\d+)?)\s*(?:["s″]|sec|"|'')?
    """ + _HEMI + r"""
    \s*[,\s]+\s*
    (\d{1,3})(?![\d.])\s*(?:[°d]|deg)?\s*
    (\d{1,2})(?![\d.])\s*(?:['m′]|min|')?\s*
    (\d{1,2}(?:\.\d+)?)\s*(?:["s″]|sec|"|'')?
    """ + _HEMI,
    re.I | re.X,
)

# DDM: 32 24.50 N 117 18.10 W  or  32°24.5' 117°18.1'
# Degrees must be followed by non-digit-non-dot; minutes MUST have a decimal.
_DDM = re.compile(
    r"""
    (?:^|[^\d.\-])
    (\d{1,3})(?![\d.])\s*(?:[°d]|deg)?\s*
    (\d{1,2}\.\d+)\s*(?:['m′]|min|')?\s*
    """ + _HEMI + r"""
    \s*[,\s]+\s*
    (\d{1,3})(?![\d.])\s*(?:[°d]|deg)?\s*
    (\d{1,2}\.\d+)\s*(?:['m′]|min|')?\s*
    """ + _HEMI,
    re.I | re.X,
)

# DD: 32.4083, -117.3017  or  32.4083°N 117.3017°W  or  32.4083 117.3017
# The lat/lon numbers here always contain a decimal point.
_DD = re.compile(
    r"""
    (?:^|[^\d.\-])                        # boundary
    (-?\d{1,3}\.\d+)\s*(?:[°d])?          # lat (has decimal)
    (?:\s*([NSEW]))?                      # optional lat hemi
    [\s,]+                                 # separator (>=1 space or comma)
    (-?\d{1,3}\.\d+)\s*(?:[°d])?          # lon (has decimal)
    (?:\s*([NSEW]))?                      # optional lon hemi
    """,
    re.I | re.X,
)


def _hemi_sign(hemi: str | None, default_negative: bool = False) -> int:
    """
    N/E => +1, S/W => -1, missing => -1 if default_negative else +1.
    Callers pass default_negative=True for the longitude slot (SoCal → West).
    """
    if hemi:
        return -1 if hemi.upper() in ("S", "W") else 1
    return -1 if default_negative else 1


def parse_coords(raw: str) -> dict | None:
    """
    Try DMS → DDM → DD in that order (most specific first). Returns
    {"lat": float, "lon": float, "format": "dms"|"ddm"|"dd"} or None.
    Missing hemisphere: assume North for lat, West for lon (SoCal default).
    """
    if not raw:
        return None
    s = " " + normalise(raw.strip()) + " "

    m = _DMS.search(s)
    if m:
        d1, mn1, sec1, hemi1, d2, mn2, sec2, hemi2 = m.groups()
        lat = int(d1) + int(mn1)/60 + float(sec1)/3600
        lon = int(d2) + int(mn2)/60 + float(sec2)/3600
        lat *= _hemi_sign(hemi1, default_negative=False)
        lon *= _hemi_sign(hemi2, default_negative=True)
        return {"lat": round(lat, 6), "lon": round(lon, 6), "format": "dms"}

    m = _DDM.search(s)
    if m:
        d1, mn1, hemi1, d2, mn2, hemi2 = m.groups()
        lat = int(d1) + float(mn1)/60
        lon = int(d2) + float(mn2)/60
        lat *= _hemi_sign(hemi1, default_negative=False)
        lon *= _hemi_sign(hemi2, default_negative=True)
        return {"lat": round(lat, 6), "lon": round(lon, 6), "format": "ddm"}

    m = _DD.search(s)
    if m:
        d1, hemi1, d2, hemi2 = m.groups()
        lat_val, lon_val = float(d1), float(d2)
        if hemi1:  # explicit hemi overrides any sign in the number
            lat = abs(lat_val) * _hemi_sign(hemi1, default_negative=False)
        else:
            lat = lat_val if lat_val < 0 else lat_val  # keep sign as-is
        if hemi2:
            lon = abs(lon_val) * _hemi_sign(hemi2, default_negative=True)
        else:
            # missing hemi: negative sign wins, else assume West
            lon = lon_val if lon_val < 0 else -lon_val
        return {"lat": round(lat, 6), "lon": round(lon, 6), "format": "dd"}

    return None


# Start of something that could be a latitude in the pin area (28-34 degrees,
# hemisphere letter optional). Used to scan whole posts.
_LAT_START = re.compile(r"(?<![\w.])(?:[NS]\s*)?(?:2[89]|3[0-4])(?=[°\s.\-])", re.I)
_DD_DECIMALS = re.compile(r"\d\.\d{3,}")


def find_coords(text: str) -> list[dict]:
    """Every distinct believable position written in a post, in order.

    Stricter than parse_coords: decimal degrees need 3+ decimals (so "32.5 lb,
    117.4 miles" stays prose), and each pair must be inside the pin area."""
    out: list[dict] = []
    if not text:
        return out
    for m in _LAT_START.finditer(text):
        window = text[m.start(): m.start() + 64].split("\n\n")[0]
        p = parse_coords(window)
        if not p:
            continue
        if p["format"] == "dd" and not _DD_DECIMALS.search(window):
            continue
        if not in_pin_area(p["lat"], p["lon"]):
            continue
        if any(abs(p["lat"] - q["lat"]) < 0.002 and abs(p["lon"] - q["lon"]) < 0.002 for q in out):
            continue
        out.append(p)
    return out


def coords_agree(a: tuple[float, float] | None,
                 b: tuple[float, float] | None,
                 tolerance_deg: float = 0.01) -> bool:
    """True iff both coords are present and each dimension is within tolerance."""
    if a is None or b is None:
        return False
    return abs(a[0] - b[0]) <= tolerance_deg and abs(a[1] - b[1]) <= tolerance_deg


# ------------------------------------------------------------------ bearing / distance

# 16-point compass (short strings, longest-first so 'nne' beats 'n' in matching)
_COMPASS = {
    "nne": 22.5, "ene": 67.5, "ese": 112.5, "sse": 157.5,
    "ssw": 202.5, "wsw": 247.5, "wnw": 292.5, "nnw": 337.5,
    "ne":  45.0, "se": 135.0, "sw": 225.0, "nw": 315.0,
    "n":    0.0, "e":  90.0, "s": 180.0, "w": 270.0,
}

# Directional phrases → bearing FROM the reference bank TO the position.
# Interpretation for SoCal:
#   "outside" the bank ≈ seaward (southwest-ish); spec says ~240°
#   "inside" the bank ≈ shoreward (northeast-ish); spec says ~060°
_PHRASE_BEARING = {
    "outside":  240.0,
    "inside":    60.0,
    "seaward":  240.0,
    "shoreward": 60.0,
    "offshore": 240.0,
    "west of":  270.0,
    "east of":   90.0,
    "north of":  0.0,
    "south of": 180.0,
    "northwest of": 315.0,
    "northeast of":  45.0,
    "southwest of": 225.0,
    "southeast of": 135.0,
    "sw of": 225.0, "se of": 135.0, "nw of": 315.0, "ne of": 45.0,
}


def bearing_from_words(text: str) -> float | None:
    """
    Parse bearing FROM the ref bank TO the target position.
    Returns degrees (0-360) or None.

    Matches phrases longest-first with word boundaries, so "northeast of X"
    is picked over the shorter "east of" that would otherwise slice into it.
    Compass tokens are only matched as whole words.
    """
    if not text:
        return None
    t = text.lower()
    # Phrases: longest first + word boundaries so "east of" doesn't hijack
    # "northeast of" and "se of" doesn't hijack "sse of".
    for phrase in sorted(_PHRASE_BEARING.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", t):
            return _PHRASE_BEARING[phrase]
    # Bare compass tokens (also longest first)
    for tok in sorted(_COMPASS.keys(), key=len, reverse=True):
        if re.search(rf"\b{tok}\b", t):
            return _COMPASS[tok]
    return None


_DISTANCE_WORDS = {
    "couple": 2.0, "pair": 2.0,
    "few":    3.0,
    "handful": 4.0,
    "several": 5.0,
}


def distance_from_words(text: str) -> float | None:
    """
    Return distance in nautical miles, or None.

    Offshore-angler convention: bare "miles" MEANS nautical miles. We only
    convert from statute when the text explicitly says "statute miles" or
    "sm" (or the letters "smi").
    """
    if not text:
        return None
    t = text.lower()
    # Numeric with an explicit unit
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*"
        r"(nm|nautical\s+miles?|statute\s+miles?|smi\b|sm\b|miles?|mi)\b",
        t,
    )
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if re.match(r"^(statute|sm|smi)", unit):
            return val * 0.868976       # statute → nm
        return val                       # nm or bare "miles" → nm
    # Word approximations: bare "miles" = nm; "statute miles" = convert.
    for word, val in _DISTANCE_WORDS.items():
        pat_statute = rf"\b{word}\b\s+(?:of\s+)?statute\s+miles?"
        if re.search(pat_statute, t):
            return val * 0.868976
        pat_bare = rf"\b{word}\b\s+(?:of\s+)?(?:miles?|mi|nm)\b"
        if re.search(pat_bare, t):
            return val
    return None


def apply_offset(ref_lat: float, ref_lon: float,
                 bearing_deg: float, distance_nm: float) -> tuple[float, float]:
    """
    Flat-earth offset. At bank-scale distances (< 30 nm) the error is
    well under 0.1 nm — plenty for a paddy-report pin.
    """
    theta = math.radians(bearing_deg)
    dnorth = distance_nm * math.cos(theta)
    deast  = distance_nm * math.sin(theta)
    dlat = dnorth / 60.0                                  # 1° lat ≈ 60 nm
    dlon = deast / (60.0 * math.cos(math.radians(ref_lat)))
    return (round(ref_lat + dlat, 4), round(ref_lon + dlon, 4))


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    R_NM = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return 2 * R_NM * math.asin(math.sqrt(a))
