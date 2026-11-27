"""San Diego surf breaks: MOP point, shore normal, bottom, preferences.

From surf-forecast-methods.md §4. MOP ids and normals were read from CDIP
metadata; the code re-reads metaShoreNormal / metaWaterDepth at run time and
uses those. Preferences (tide window, best wind, swell window) are published
priors [D], to be learned per break.

type:  beach | reef | shores   (sets the rating's height trapezoid)
gamma: breaker index γ (Hb = γ·hb); beach ~0.78, reef/point ~0.95
cal:   per-break face-height calibration c_b (start 1.0; Blacks > 1 and
       Scripps/Shores < 1 expected from canyon refraction; fit when we have
       surf observations)
tide:  (low_ft, high_ft) MLLW window where the break works best
buoy:  nearest CDIP validation buoy, for bias correction and display
"""
from __future__ import annotations

BREAKS: list[dict] = [
    {"id": "oceanside-pier", "name": "Oceanside Pier", "lat": 33.1933, "lon": -117.3877,
     "mop": "D0912", "type": "beach", "gamma": 0.78, "cal": 1.0, "tide": (0.0, 6.0),
     "swell": (180, 295), "buoy": "264", "potential": 4.0},
    {"id": "oceanside-harbor", "name": "Oceanside Harbor", "lat": 33.2000, "lon": -117.398,
     "mop": "D0916", "type": "beach", "gamma": 0.80, "cal": 1.0, "tide": (2.5, 6.0),
     "swell": (180, 295), "buoy": "264", "potential": 4.0},
    {"id": "swamis", "name": "Swamis", "lat": 33.0345, "lon": -117.2923,
     "mop": "D0710", "type": "reef", "gamma": 0.95, "cal": 1.0, "tide": (-0.5, 3.5),
     "swell": (240, 300), "buoy": "262", "potential": 4.5},
    {"id": "cardiff-reef", "name": "Cardiff Reef", "lat": 33.0152, "lon": -117.2834,
     "mop": "D0686", "type": "reef", "gamma": 0.95, "cal": 1.0, "tide": (0.0, 6.0),
     "swell": (240, 300), "buoy": "262", "potential": 4.0},
    {"id": "blacks", "name": "Blacks", "lat": 32.8796, "lon": -117.2538,
     "mop": "D0530", "type": "beach", "gamma": 0.80, "cal": 1.0, "tide": (-0.5, 3.5),
     "swell": (205, 295), "buoy": "201", "potential": 5.0},
    {"id": "scripps-pier", "name": "Scripps Pier", "lat": 32.8657, "lon": -117.2564,
     "mop": "D0511", "type": "beach", "gamma": 0.78, "cal": 1.0, "tide": (0.0, 4.0),
     "swell": (200, 300), "buoy": "201", "potential": 3.5},
    {"id": "la-jolla-shores", "name": "La Jolla Shores", "lat": 32.8586, "lon": -117.2584,
     "mop": "D0501", "type": "shores", "gamma": 0.75, "cal": 1.0, "tide": (0.0, 6.0),
     "swell": (250, 300), "buoy": "201", "potential": 3.5},
    {"id": "windansea", "name": "Windansea", "lat": 32.8294, "lon": -117.2827,
     "mop": "D0455", "type": "reef", "gamma": 0.95, "cal": 1.0, "tide": (0.0, 6.0),
     "swell": (190, 280), "buoy": "201", "potential": 4.5},
    {"id": "pacific-beach", "name": "Pacific Beach (Crystal Pier)", "lat": 32.7958, "lon": -117.2592,
     "mop": "D0408", "type": "beach", "gamma": 0.78, "cal": 1.0, "tide": (1.5, 4.5),
     "swell": (190, 290), "buoy": "220", "potential": 3.5},
    {"id": "ocean-beach", "name": "Ocean Beach Pier", "lat": 32.7478, "lon": -117.2539,
     "mop": "D0347", "type": "beach", "gamma": 0.80, "cal": 1.0, "tide": (1.5, 4.5),
     "swell": (220, 300), "buoy": "220", "potential": 4.0},
    {"id": "sunset-cliffs", "name": "Sunset Cliffs", "lat": 32.7193, "lon": -117.2578,
     "mop": "D0316", "type": "reef", "gamma": 0.95, "cal": 1.0, "tide": (-0.5, 2.5),
     "swell": (190, 290), "buoy": "220", "potential": 4.5},
    {"id": "imperial-beach", "name": "Imperial Beach Pier", "lat": 32.5784, "lon": -117.1343,
     "mop": "D0050", "type": "beach", "gamma": 0.78, "cal": 1.0, "tide": (2.5, 6.0),
     "swell": (180, 270), "buoy": "191", "potential": 3.5},
]

BY_ID = {b["id"]: b for b in BREAKS}
