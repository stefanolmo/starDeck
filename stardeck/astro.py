"""Positional astronomy in plain Python (no dependencies).

Accuracy: stars J2000 + precession; Sun and planets from JPL "Keplerian elements for approximate positions" (1800-2050,
a few arcminutes); Moon from a truncated Meeus ch. 47 series (~0.1-0.3 deg) with topocentric parallax. Plenty for a planetarium,
not for occultation timing.

Conventions: angles in degrees unless a name says rad; horizontal vectors are (North, East, Up); azimuth is measured from North
towards East; JD is the Julian Date in UT (the UT/TT difference of ~70 s is ignored).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

D2R = math.pi / 180.0
R2D = 180.0 / math.pi
J2000 = 2451545.0
OBLIQUITY_J2000 = 23.4392911
AU_KM = 149597870.7
EARTH_RADIUS_KM = 6378.14


# ---------------------------------------------------------------- time
def jd_from_datetime(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.astimezone()                       # naive = local time
    return dt.timestamp() / 86400.0 + 2440587.5


def datetime_from_jd(jd: float, tz=timezone.utc) -> datetime:
    return datetime.fromtimestamp((jd - 2440587.5) * 86400.0, tz)


def jd_now() -> float:
    return datetime.now(timezone.utc).timestamp() / 86400.0 + 2440587.5


def gmst(jd: float) -> float:
    """Greenwich mean sidereal time in degrees."""
    t = (jd - J2000) / 36525.0
    return (280.46061837 + 360.98564736629 * (jd - J2000) + 0.000387933 * t * t - t ** 3 / 38710000.0) % 360.0


def lst(jd: float, lon_east: float) -> float:
    return (gmst(jd) + lon_east) % 360.0


# ---------------------------------------------------------------- vectors / matrices
def radec_to_vec(ra: float, dec: float) -> tuple:
    cd = math.cos(dec * D2R)
    return (cd * math.cos(ra * D2R), cd * math.sin(ra * D2R), math.sin(dec * D2R))


def vec_to_radec(v) -> tuple:
    x, y, z = v
    return (math.atan2(y, x) * R2D) % 360.0, math.atan2(z, math.hypot(x, y)) * R2D


def mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def mat_vec(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def transpose(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


def rot_x(a_deg: float):
    c, s = math.cos(a_deg * D2R), math.sin(a_deg * D2R)
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def rot_z(a_deg: float):
    c, s = math.cos(a_deg * D2R), math.sin(a_deg * D2R)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def precession_matrix(jd: float):
    """Rotation J2000 equatorial -> mean equator of date (IAU 1976)."""
    t = (jd - J2000) / 36525.0
    zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) / 3600.0
    z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) / 3600.0
    theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) / 3600.0
    # P = R3(-z) R2(theta) R3(-zeta) with passive rotations = Rz(z) . Ry(theta) . Rz(zeta) in the active convention of rot_z
    ct, st = math.cos(theta * D2R), math.sin(theta * D2R)
    ry = ((ct, 0, -st), (0, 1, 0), (st, 0, ct))
    return mat_mul(rot_z(z), mat_mul(ry, rot_z(zeta)))


def eq_to_horizon_matrix(lst_deg: float, lat: float):
    """Rotation equatorial (of date) -> horizontal (North, East, Up)."""
    sl, cl = math.sin(lat * D2R), math.cos(lat * D2R)
    c, s = math.cos(lst_deg * D2R), math.sin(lst_deg * D2R)
    # x' = x cos L + y sin L ; y' = x sin L - y cos L ; z' = z   (hour-angle frame)
    # N = -sin(lat) x' + cos(lat) z ; E = -y' ; U = cos(lat) x' + sin(lat) z
    return ((-sl * c, -sl * s, cl),
            (-s, c, 0.0),
            (cl * c, cl * s, sl))


def horizon_to_altaz(v) -> tuple:
    n, e, u = v
    return math.atan2(u, math.hypot(n, e)) * R2D, (math.atan2(e, n) * R2D) % 360.0


def altaz_to_horizon(alt: float, az: float) -> tuple:
    ca = math.cos(alt * D2R)
    return (ca * math.cos(az * D2R), ca * math.sin(az * D2R), math.sin(alt * D2R))


# ---------------------------------------------------------------- Sun / planets (Standish, J2000 ecliptic)
# a, a', e, e', I, I', L, L', long.peri, long.peri', long.node, long.node'   (per Julian century)
ELEMENTS = {
    "Mercurio": (0.38709927, 0.00000037, 0.20563593, 0.00001906, 7.00497902, -0.00594749, 252.25032350, 149472.67411175, 77.45779628, 0.16047689, 48.33076593, -0.12534081),
    "Venere": (0.72333566, 0.00000390, 0.00677672, -0.00004107, 3.39467605, -0.00078890, 181.97909950, 58517.81538729, 131.60246718, 0.00268329, 76.67984255, -0.27769418),
    "Terra": (1.00000261, 0.00000562, 0.01671123, -0.00004392, -0.00001531, -0.01294668, 100.46457166, 35999.37244981, 102.93768193, 0.32327364, 0.0, 0.0),
    "Marte": (1.52371034, 0.00001847, 0.09339410, 0.00007882, 1.84969142, -0.00813131, -4.55343205, 19140.30268499, -23.94362959, 0.44441088, 49.55953891, -0.29257343),
    "Giove": (5.20288700, -0.00011607, 0.04838624, -0.00013253, 1.30439695, -0.00183714, 34.39644051, 3034.74612775, 14.72847983, 0.21252668, 100.47390909, 0.20469106),
    "Saturno": (9.53667594, -0.00125060, 0.05386179, -0.00050991, 2.48599187, 0.00193609, 49.95424423, 1222.49362201, 92.59887831, -0.41897216, 113.66242448, -0.28867794),
    "Urano": (19.18916464, -0.00196176, 0.04725744, -0.00004397, 0.77263783, -0.00242939, 313.23810451, 428.48202785, 170.95427630, 0.40805281, 74.01692503, 0.04240589),
    "Nettuno": (30.06992276, 0.00026291, 0.00859048, 0.00005105, 1.77004347, 0.00035372, -55.12002969, 218.45945325, 44.96476227, -0.32241464, 131.78422574, -0.00508664),
}
PLANETS = ["Mercurio", "Venere", "Marte", "Giove", "Saturno", "Urano", "Nettuno"]
H0 = {"Mercurio": -0.42, "Venere": -4.40, "Marte": -1.52, "Giove": -9.40, "Saturno": -8.88, "Urano": -7.19, "Nettuno": -6.87}


def _kepler(m_deg: float, e: float) -> float:
    m = (m_deg + 180.0) % 360.0 - 180.0
    mr = m * D2R
    ea = mr + e * math.sin(mr) * (1.0 + e * math.cos(mr))
    for _ in range(12):
        d = (ea - e * math.sin(ea) - mr) / (1.0 - e * math.cos(ea))
        ea -= d
        if abs(d) < 1e-10:
            break
    return ea


def helio_ecliptic(name: str, jd: float) -> tuple:
    """Heliocentric ecliptic J2000 rectangular coordinates (AU)."""
    a0, da, e0, de, i0, di, l0, dl, w0, dw, o0, do = ELEMENTS[name]
    t = (jd - J2000) / 36525.0
    a, e, inc = a0 + da * t, e0 + de * t, i0 + di * t
    mean_l, peri, node = l0 + dl * t, w0 + dw * t, o0 + do * t
    arg_peri = peri - node
    ea = _kepler(mean_l - peri, e)
    xp = a * (math.cos(ea) - e)
    yp = a * math.sqrt(1.0 - e * e) * math.sin(ea)
    cw, sw = math.cos(arg_peri * D2R), math.sin(arg_peri * D2R)
    co, so = math.cos(node * D2R), math.sin(node * D2R)
    ci, si = math.cos(inc * D2R), math.sin(inc * D2R)
    return ((cw * co - sw * so * ci) * xp + (-sw * co - cw * so * ci) * yp,
            (cw * so + sw * co * ci) * xp + (-sw * so + cw * co * ci) * yp,
            (sw * si) * xp + (cw * si) * yp)


def ecliptic_to_equatorial(v):
    c, sn = math.cos(OBLIQUITY_J2000 * D2R), math.sin(OBLIQUITY_J2000 * D2R)
    return (v[0], v[1] * c - v[2] * sn, v[1] * sn + v[2] * c)


@dataclass
class Body:
    name: str
    ra: float                     # J2000 equatorial, degrees
    dec: float
    mag: float
    dist_au: float = 0.0
    phase: float = 1.0            # illuminated fraction 0..1
    elong: float = 0.0            # elongation from the Sun, degrees
    kind: str = "planet"          # sun | moon | planet
    angsize: float = 0.0          # apparent diameter in degrees (sun/moon)


def sun_geocentric(jd: float) -> tuple:
    """Geocentric ecliptic J2000 vector of the Sun (AU)."""
    ex, ey, ez = helio_ecliptic("Terra", jd)
    return (-ex, -ey, -ez)


def planet_bodies(jd: float) -> list:
    earth = helio_ecliptic("Terra", jd)
    out = []
    for name in PLANETS:
        p = helio_ecliptic(name, jd)
        g = (p[0] - earth[0], p[1] - earth[1], p[2] - earth[2])
        delta = math.sqrt(sum(c * c for c in g))
        r = math.sqrt(sum(c * c for c in p))
        r_e = math.sqrt(sum(c * c for c in earth))
        cos_i = max(-1.0, min(1.0, (r * r + delta * delta - r_e * r_e) / (2 * r * delta)))
        i = math.acos(cos_i) * R2D
        sun_g = (-earth[0], -earth[1], -earth[2])
        sun_d = r_e
        cos_el = max(-1.0, min(1.0, (g[0] * sun_g[0] + g[1] * sun_g[1] + g[2] * sun_g[2]) / (delta * sun_d)))
        mag = H0[name] + 5.0 * math.log10(r * delta)
        if name == "Mercurio":
            mag += 0.0380 * i - 0.000273 * i * i + 2e-6 * i ** 3
        elif name == "Venere":
            mag += 0.0009 * i + 0.000239 * i * i - 6.5e-7 * i ** 3
        elif name == "Marte":
            mag += 0.016 * i
        elif name == "Giove":
            mag += 0.005 * i
        ra, dec = vec_to_radec(ecliptic_to_equatorial(g))
        out.append(Body(name, ra, dec, mag, delta, (1 + cos_i) / 2, math.acos(cos_el) * R2D, "planet"))
    return out


def sun_body(jd: float) -> Body:
    g = sun_geocentric(jd)
    d = math.sqrt(sum(c * c for c in g))
    ra, dec = vec_to_radec(ecliptic_to_equatorial(g))
    return Body("Sole", ra, dec, -26.74, d, 1.0, 0.0, "sun", 2 * math.atan(696000.0 / (d * AU_KM)) * R2D)


# ---------------------------------------------------------------- Moon (Meeus ch. 47, truncated)
_MOON_LR = [  # D, M, M', F, sum_l (1e-6 deg), sum_r (1e-3 km)
    (0, 0, 1, 0, 6288774, -20905355), (2, 0, -1, 0, 1274027, -3699111), (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925), (0, 1, 0, 0, -185116, 48888), (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158), (2, -1, -1, 0, 57066, -152138), (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586), (0, 1, -1, 0, -40923, -129620), (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755), (2, 0, 0, -2, 15327, 10321), (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661), (4, 0, -1, 0, 10675, -34782), (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636), (2, 1, -1, 0, -7888, 24208), (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379), (1, 1, 0, 0, 4987, -16675), (2, -1, 1, 0, 4036, -12831), (2, 0, 2, 0, 3994, -10445),
]
_MOON_B = [  # D, M, M', F, sum_b (1e-6 deg)
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693), (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271), (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266), (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324), (2, 0, 1, 1, 4200),
]


def moon_geocentric(jd: float) -> tuple:
    """(ecliptic longitude of date deg, latitude deg, distance km)."""
    t = (jd - J2000) / 36525.0
    lp = 218.3164477 + 481267.88123421 * t
    d = (297.8501921 + 445267.1114034 * t) * D2R
    m = (357.5291092 + 35999.0502909 * t) * D2R
    mp = (134.9633964 + 477198.8675055 * t) * D2R
    f = (93.2720950 + 483202.0175233 * t) * D2R
    e = 1.0 - 0.002516 * t - 0.0000074 * t * t
    sl = sr = sb = 0.0
    for dd, mm, mpp, ff, cl, cr in _MOON_LR:
        arg = dd * d + mm * m + mpp * mp + ff * f
        ef = e ** abs(mm)
        sl += cl * ef * math.sin(arg)
        sr += cr * ef * math.cos(arg)
    for dd, mm, mpp, ff, cb in _MOON_B:
        sb += cb * (e ** abs(mm)) * math.sin(dd * d + mm * m + mpp * mp + ff * f)
    a1, a2 = (119.75 + 131.849 * t) * D2R, (53.09 + 479264.290 * t) * D2R
    sl += 3958 * math.sin(a1) + 1962 * math.sin(lp * D2R - f) + 318 * math.sin(a2)
    sb += -2235 * math.sin(lp * D2R) + 382 * math.sin((313.45 + 481266.484 * t) * D2R)
    return (lp + sl / 1e6) % 360.0, sb / 1e6, 385000.56 + sr / 1e3


def moon_body(jd: float) -> Body:
    lon, lat, dist = moon_geocentric(jd)
    t = (jd - J2000) / 36525.0
    lon_j2000 = lon - (1.396971 * t + 0.0003086 * t * t)          # general precession in longitude
    cl, sl, cb, sb = math.cos(lon_j2000 * D2R), math.sin(lon_j2000 * D2R), math.cos(lat * D2R), math.sin(lat * D2R)
    ra, dec = vec_to_radec(ecliptic_to_equatorial((cb * cl, cb * sl, sb)))
    sun = sun_body(jd)
    cos_el = math.sin(dec * D2R) * math.sin(sun.dec * D2R) + math.cos(dec * D2R) * math.cos(sun.dec * D2R) * math.cos((ra - sun.ra) * D2R)
    el = math.acos(max(-1.0, min(1.0, cos_el))) * R2D
    # phase angle from elongation (distance ratio taken into account)
    sd = sun.dist_au * AU_KM
    i = math.atan2(sd * math.sin(el * D2R), dist - sd * math.cos(el * D2R))
    k = (1 + math.cos(i)) / 2
    ia = i * R2D
    return Body("Luna", ra, dec, -12.7 + 0.026 * ia + 4e-9 * ia ** 4, dist / AU_KM, k, el, "moon", 2 * math.atan(1737.4 / dist) * R2D)


def moon_waxing(jd: float) -> bool:
    mo, su = moon_body(jd), sun_body(jd)
    return ((mo.ra - su.ra) % 360.0) < 180.0


def moon_parallax_correct(ra: float, dec: float, dist_km: float, lst_deg: float, lat: float) -> tuple:
    """Topocentric RA/Dec (of the same equinox as the input) of the Moon for an observer at `lat` with local sidereal time `lst_deg`."""
    rho = dist_km / EARTH_RADIUS_KM
    x, y, z = radec_to_vec(ra, dec)
    ox, oy, oz = math.cos(lat * D2R) * math.cos(lst_deg * D2R), math.cos(lat * D2R) * math.sin(lst_deg * D2R), math.sin(lat * D2R)
    return vec_to_radec((x * rho - ox, y * rho - oy, z * rho - oz))


# ---------------------------------------------------------------- misc
def mean_obliquity(jd: float) -> float:
    t = (jd - J2000) / 36525.0
    return 23.4392911 - 0.0130042 * t


def moon_phase_name(phase: float, waxing: bool) -> str:
    if phase < 0.03:
        return "Luna nuova"
    if phase > 0.97:
        return "Luna piena"
    if abs(phase - 0.5) < 0.04:
        return "Primo quarto" if waxing else "Ultimo quarto"
    if phase < 0.5:
        return "Luna crescente (falce)" if waxing else "Luna calante (falce)"
    return "Gibbosa crescente" if waxing else "Gibbosa calante"


def twilight_state(sun_alt: float) -> str:
    if sun_alt > -0.833:
        return "giorno"
    if sun_alt > -6:
        return "crepuscolo civile"
    if sun_alt > -12:
        return "crepuscolo nautico"
    if sun_alt > -18:
        return "crepuscolo astronomico"
    return "notte"


def angular_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    c = math.sin(dec1 * D2R) * math.sin(dec2 * D2R) + math.cos(dec1 * D2R) * math.cos(dec2 * D2R) * math.cos((ra1 - ra2) * D2R)
    return math.acos(max(-1.0, min(1.0, c))) * R2D


def fmt_ra(ra: float) -> str:
    h = ra / 15.0
    hh = int(h)
    mm = (h - hh) * 60
    return f"{hh:02d}h {int(mm):02d}m {int((mm - int(mm)) * 60):02d}s"


def fmt_dec(dec: float) -> str:
    s = "+" if dec >= 0 else "−"
    d = abs(dec)
    dd = int(d)
    mm = (d - dd) * 60
    return f"{s}{dd:02d}° {int(mm):02d}′ {int((mm - int(mm)) * 60):02d}″"


def fmt_deg_dms(x: float) -> str:
    dd = int(x)
    mm = (x - dd) * 60
    return f"{dd:d}° {int(mm):02d}′"
