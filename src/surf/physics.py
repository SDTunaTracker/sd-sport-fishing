"""Linear wave physics for the surf breaking step (pure Python, SI units).

  wavenumber(T, h)            ω² = g k tanh(k h), solved by Newton iteration
  group_speed(T, h)           Cg = n c, n = ½(1 + 2kh / sinh 2kh)
  shoal_hs(H, T, h_to, h_from=None)
                              linear shoaling Ks = sqrt(Cg_from / Cg_to);
                              h_from None = deep water
  break_wave(Hs, T, dir, normal, h1, gamma)
                              shoal + refract (Snell) from the MOP depth h1
                              shoreward until H >= γ·h -> (Hb, hb, alpha_b)
  komar_gaughan(H0, T)        Hb = 0.39 g^(1/5) (T H0²)^(2/5), the closed-form check

Directions are "coming from", degrees true. alpha = wave direction minus the
shore normal (the direction the beach faces). Waves from |alpha| >= 90° don't
reach the beach.
"""
from __future__ import annotations

import math

G = 9.81


def wavenumber(T: float, h: float) -> float:
    w = 2 * math.pi / T
    k0 = w * w / G
    if h <= 0:
        return float("nan")
    # Fenton & McKee start, then Newton.
    k = k0 / math.tanh((k0 * h) ** 0.75) ** (2 / 3)
    for _ in range(30):
        th = math.tanh(k * h)
        f = G * k * th - w * w
        df = G * th + G * k * h * (1 - th * th)
        dk = f / df
        k -= dk
        if abs(dk) < 1e-10 * k:
            break
    return k


def celerity(T: float, h: float | None) -> float:
    if h is None:
        return G * T / (2 * math.pi)
    return (2 * math.pi / T) / wavenumber(T, h)


def group_speed(T: float, h: float | None) -> float:
    if h is None:
        return G * T / (4 * math.pi)
    k = wavenumber(T, h)
    kh = k * h
    n = 0.5 * (1 + (2 * kh / math.sinh(2 * kh) if kh < 350 else 0.0))
    return n * (2 * math.pi / T) / k


def shoal_hs(H: float, T: float, h_to: float, h_from: float | None = None) -> float:
    """H shoaled (no refraction) from depth h_from (None = deep) to h_to."""
    if H is None or T is None or not (T > 0) or not (h_to and h_to > 0) or math.isnan(H) or math.isnan(T):
        return float("nan") if H is None else H
    return H * math.sqrt(group_speed(T, h_from) / group_speed(T, h_to))


def break_wave(Hs: float, T: float, direction: float | None, normal: float | None,
               h1: float, gamma: float, dh: float = 0.05) -> tuple[float, float, float]:
    """Breaking height Hb (m), breaking depth hb (m) and angle at breaking (deg).

    Starts at depth h1 (the MOP point, ~10 m) with Hs, Tp, Dp, then steps
    shoreward applying shoaling (Ks) and refraction (Kr, Snell's law
    sin α / c = const) until H >= γ·h. If the wave already breaks at h1
    (big swell), Hb = Hs at h1.
    """
    if not (Hs and Hs > 0 and T and T > 0):
        return 0.0, 0.0, 0.0
    a1 = 0.0
    if direction is not None and normal is not None and not math.isnan(direction):
        a1 = (direction - normal + 180) % 360 - 180
    if abs(a1) >= 90:
        return 0.0, 0.0, a1
    if Hs >= gamma * h1:
        return Hs, h1, a1
    c1, cg1 = celerity(T, h1), group_speed(T, h1)
    s1 = math.sin(math.radians(a1)) / c1
    cos1 = math.cos(math.radians(a1))
    h = h1
    while h > dh:
        h -= dh
        c, cg = celerity(T, h), group_speed(T, h)
        sa = max(-1.0, min(1.0, s1 * c))
        cosa = math.sqrt(1 - sa * sa)
        H = Hs * math.sqrt(cg1 / cg) * math.sqrt(cos1 / cosa)
        if H >= gamma * h:
            return H, h, math.degrees(math.asin(sa))
    return H, h, math.degrees(math.asin(sa))


def deep_water_height(Hs: float, T: float, h1: float) -> float:
    """Back-shoal Hs at depth h1 to deep water (no refraction)."""
    return Hs * math.sqrt(group_speed(T, h1) / group_speed(T, None))


def komar_gaughan(H0: float, T: float) -> float:
    return 0.39 * G ** 0.2 * (T * H0 * H0) ** 0.4


M_TO_FT = 3.28084


from functools import lru_cache


@lru_cache(maxsize=200000)
def _cc(T: float, h: float) -> tuple[float, float]:
    """(celerity, group speed) cached on (period, depth rounded to cm)."""
    return celerity(T, h), group_speed(T, h)


def spectral_hs(freqs, dfs, energy) -> float:
    """Hm0 = 4·sqrt(Σ E·df)."""
    m0 = sum(e * d for e, d in zip(energy, dfs) if e and e > 0)
    return 4 * math.sqrt(m0) if m0 > 0 else 0.0


def break_spectrum(freqs, dfs, energy, dirs, normal: float | None, h1: float, gamma: float,
                   dh: float = 0.05) -> tuple[float, float]:
    """Breaking height from a frequency spectrum at depth h1 (experiment E8).

    Each band is shoaled (Ks² = Cg1/Cg) and refracted (Kr² = cos α1/cos α,
    Snell per band) with its OWN frequency and direction; the shoaled bulk
    Hm0(h) = 4·sqrt(Σ E_i(h) df_i) is tested against γ·h. Bands arriving from
    behind the beach (|α| >= 90°) carry no energy. Returns (Hb, hb).
    """
    bands = []
    for f, d, e, th in zip(freqs, dfs, energy, dirs):
        if not (e and e > 0 and f > 0):
            continue
        a1 = 0.0 if (normal is None or th is None or math.isnan(th)) else (th - normal + 180) % 360 - 180
        if abs(a1) >= 90:
            continue
        T = 1.0 / f
        c1, cg1 = _cc(T, round(h1, 2))
        bands.append((T, e * d, cg1, math.sin(math.radians(a1)) / c1, math.cos(math.radians(a1))))
    if not bands:
        return 0.0, 0.0
    hs1 = 4 * math.sqrt(sum(b[1] for b in bands))
    if hs1 >= gamma * h1:
        return hs1, h1
    h = h1
    H = hs1
    while h > dh:
        h = round(h - dh, 2)
        m0 = 0.0
        for T, ed, cg1, s1, cos1 in bands:
            c, cg = _cc(T, h)
            sa = max(-1.0, min(1.0, s1 * c))
            m0 += ed * (cg1 / cg) * (cos1 / math.sqrt(1 - sa * sa))
        H = 4 * math.sqrt(m0)
        if H >= gamma * h:
            return H, h
    return H, h


def _bj_qb(hrms: float, hmax: float) -> float:
    """Fraction of breaking waves Qb from (1 - Qb)/ln(Qb) = -(Hrms/Hmax)^2 (Battjes & Janssen 1978)."""
    b2 = (hrms / hmax) ** 2
    if b2 >= 1:
        return 1.0
    if b2 < 0.1:
        return 0.0
    q = 0.5
    for _ in range(60):                  # fixed point on Qb = exp((Qb - 1)/b²)
        q = math.exp((q - 1) / b2)
    return min(1.0, max(0.0, q))


def bj_profile(Hs: float, T: float, h1: float, slope: float, direction: float | None = None,
               normal: float | None = None, gamma: float = 0.73, alpha: float = 1.0,
               dx: float = 2.0) -> tuple[float, float]:
    """Random-wave shoaling + breaking (Battjes & Janssen 1978 energy balance)
    from depth h1 shoreward on a plane slope. Returns (max Hs along the
    profile, depth where it occurs): the height of the breaking-wave field
    (experiment E12), instead of monochromatic shoaling to γ·h.

    d(E·Cg·cosα)/dx = -D,  D = (α/4)·ρg·fp·Qb·Hmax²,  Hmax = γ·h,  Hrms = Hs/√2.
    """
    if not (Hs and Hs > 0 and T and T > 0):
        return 0.0, 0.0
    a1 = 0.0
    if direction is not None and normal is not None and not math.isnan(direction):
        a1 = (direction - normal + 180) % 360 - 180
    if abs(a1) >= 90:
        return 0.0, 0.0
    c1 = celerity(T, h1)
    s1 = math.sin(math.radians(a1)) / c1
    rho_g = 1025 * G
    fp = 1.0 / T
    hrms = Hs / math.sqrt(2)
    flux = rho_g * hrms ** 2 / 8 * group_speed(T, h1) * math.cos(math.radians(a1))
    h, best, best_h = h1, Hs, h1
    while h > 0.3:
        hmax = gamma * h
        qb = _bj_qb(hrms, hmax)
        diss = alpha / 4 * rho_g * fp * qb * hmax ** 2
        flux = max(0.0, flux - diss * dx)
        h = max(0.3, h - slope * dx)
        c, cg = celerity(T, h), group_speed(T, h)
        sa = max(-1.0, min(1.0, s1 * c))
        e = flux / (cg * math.sqrt(1 - sa * sa))
        hrms = math.sqrt(8 * e / rho_g)
        hs = hrms * math.sqrt(2)
        if hs > best:
            best, best_h = hs, h
        if flux <= 0:
            break
    return best, best_h
