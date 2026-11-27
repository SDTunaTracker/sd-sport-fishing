"""CDIP THREDDS OPeNDAP access (MOP model points, MOP validation sites, buoys).

Uses the plain-text `.ascii?` OPeNDAP form, so no netCDF library is needed.
CDIP data are free to redistribute; credit CDIP / USACE and cite
O'Reilly et al. (2016).

    series(url, ["waveHs", "waveTp", "waveDp", "waveFlagPrimary"], since=..., until=...)
        -> {"waveTime": [epoch s...], "waveHs": [...], ...}

Requests are cached on disk (data/surf_cache) keyed by URL + query, with a
max age, because MOP files rebuild only every few hours and the archive
never changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "surf_cache"
UA = "TunaTrackerBot/1.0 (+https://thetunatracker.com; surf forecast)"
BASE = "https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip"

CREDIT = ("CDIP / Scripps Institution of Oceanography, funded by USACE and California "
          "State Parks; MOP model: O'Reilly et al. (2016), Coastal Engineering 116")


def mop_url(point: str, kind: str) -> str:
    """kind: ecmwf_fc | forecast (WW3) | nowcast | hindcast."""
    return f"{BASE}/model/MOP_alongshore/{point}_{kind}.nc"


def validation_url(site: str, kind: str) -> str:
    """MOP predicted at a buoy site, e.g. site '100' -> BP100_{kind}.nc."""
    return f"{BASE}/model/MOP_validation/BP{site}_{kind}.nc"


def buoy_urls(station: str) -> list[str]:
    """Archive (historic) and realtime files for a CDIP buoy, oldest first."""
    return [f"{BASE}/archive/{station}p1/{station}p1_historic.nc",
            f"{BASE}/realtime/{station}p1_rt.nc"]


def _get(url: str, max_age_s: float, timeout: float = 120.0) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:20]
    f = CACHE / f"{key}.txt"
    if f.exists() and time.time() - f.stat().st_mtime < max_age_s:
        return f.read_text(encoding="utf-8")
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            f.write_text(r.text, encoding="utf-8")
            return r.text
        except FileNotFoundError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"CDIP fetch failed: {url}: {last}")


def dims(url: str, max_age_s: float = 3 * 3600) -> dict[str, int]:
    """{variable: length of its first dimension} from the .dds."""
    dds = _get(url + ".dds", max_age_s)
    return {m.group(2): int(m.group(3)) for m in
            re.finditer(r"(Int32|Float32|Byte|Float64|Int16)\s+(\w+)\[\w+ = (\d+)\]", dds)}


def attrs(url: str, max_age_s: float = 7 * 86400) -> str:
    return _get(url + ".das", max_age_s)


def parse_ascii(text: str) -> dict[str, list[float]]:
    """OPeNDAP .ascii body -> {var: [values]} for 1-D variables."""
    out: dict[str, list[float]] = {}
    body = text.split("---------------------------------------------", 1)[-1]
    for name, vals in re.findall(r"^(\w+)\[\d+\]\n([^\n]*)", body, re.M):
        try:
            out[name] = [float(x) for x in vals.split(",") if x.strip()]
        except ValueError:
            out[name] = [x.strip().strip('"') for x in vals.split(",")]
    return out


def _idx_range(times: list[float], since: float | None, until: float | None) -> tuple[int, int] | None:
    lo, hi = 0, len(times) - 1
    if since is not None:
        while lo <= hi and times[lo] < since:
            lo += 1
    if until is not None:
        while hi >= lo and times[hi] > until:
            hi -= 1
    return (lo, hi) if lo <= hi else None


def series(url: str, variables: list[str], since: datetime | None = None,
           until: datetime | None = None, time_var: str = "waveTime",
           max_age_s: float = 3 * 3600, chunk: int = 60000) -> dict[str, list[float]]:
    """Time slice of 1-D variables on `time_var`, as plain lists."""
    t_all = parse_ascii(_get(f"{url}.ascii?{time_var}", max_age_s)).get(time_var, [])
    s = since.timestamp() if since else None
    u = until.timestamp() if until else None
    rng = _idx_range(t_all, s, u)
    out: dict[str, list[float]] = {time_var: [], **{v: [] for v in variables}}
    if rng is None:
        return out
    a, b = rng
    for lo in range(a, b + 1, chunk):
        hi = min(b, lo + chunk - 1)
        q = ",".join(f"{v}[{lo}:1:{hi}]" for v in variables)
        part = parse_ascii(_get(f"{url}.ascii?{q}", max_age_s))
        out[time_var].extend(t_all[lo:hi + 1])
        for v in variables:
            out[v].extend(part.get(v, []))
    return out


def to_iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")


def save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
