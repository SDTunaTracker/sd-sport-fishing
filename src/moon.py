"""Moon phase calculation (synodic-month approximation).

Port of the moonInfo() helper in the design's data.js. Good enough for trip-report
correlations; not astronomical-grade.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

PHASES = [
    "New", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]

# Reference new moon: 2000-01-06 18:14 UTC
_REF = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
_SYNODIC = 29.53058867


@dataclass
class MoonInfo:
    phase: str
    illum: int           # 0-100
    days_from_new: float
    days_from_full: float


def moon_info(d: datetime) -> MoonInfo:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    days = (d - _REF).total_seconds() / 86400.0
    p = days % _SYNODIC
    illum = (1 - math.cos((p / _SYNODIC) * 2 * math.pi)) / 2
    idx = int((p / _SYNODIC) * 8 + 0.5) % 8
    return MoonInfo(
        phase=PHASES[idx],
        illum=round(illum * 100),
        days_from_new=round(p * 10) / 10,
        days_from_full=round(abs(p - _SYNODIC / 2) * 10) / 10,
    )
