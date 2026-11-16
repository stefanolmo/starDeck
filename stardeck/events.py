"""Rise, transit and set times of the Sun, Moon, planets and any fixed object for one local day.

The altitude of the body is sampled every 15 minutes across the day; sign changes of (altitude - h0) are refined by bisection and
altitude maxima by a ternary search. Accuracy is about a minute for the Sun and stars, a few minutes for the Moon (which moves fast).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from . import astro
from .astro import D2R, R2D

H0_SUN = -0.833          # upper limb + standard refraction
H0_MOON = -0.833         # the Moon position used is topocentric, so the same limb/refraction allowance applies
H0_STAR = -0.567         # refraction only (point source)
H0_ASTRO_NIGHT = -18.0
STEP_MIN = 15


@dataclass
class DayEvents:
    rise: Optional[float] = None          # Julian dates (UT)
    transit: Optional[float] = None
    transit_alt: Optional[float] = None   # altitude at culmination, degrees
    set: Optional[float] = None
    state: str = "normal"                 # normal | always_up | never_up (no crossing of the horizon during the day)


def local_day_bounds(jd: float, tz=None) -> tuple:
    """(JD of local midnight starting the day that contains `jd`, JD of the next local midnight). tz None = system local time."""
    d = astro.datetime_from_jd(jd)
    d = d.astimezone(tz) if tz is not None else d.astimezone()
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.combine(start.date() + timedelta(days=1), start.time(), tzinfo=start.tzinfo)
    return astro.jd_from_datetime(start), astro.jd_from_datetime(end)


def _alt_fn(vec_fn: Callable[[float], tuple], lat: float, lon: float, jd_ref: float):
    prec = astro.precession_matrix(jd_ref)               # constant over one day: precession moves ~0.00004 deg per day
    sl, cl = math.sin(lat * D2R), math.cos(lat * D2R)

    def alt(jd: float) -> float:
        v = astro.mat_vec(prec, vec_fn(jd))
        t = astro.lst(jd, lon) * D2R
        s = sl * v[2] + cl * (math.cos(t) * v[0] + math.sin(t) * v[1])
        return math.asin(max(-1.0, min(1.0, s))) * R2D
    return alt


def day_events(vec_fn: Callable[[float], tuple], jd0: float, jd1: float, lat: float, lon: float, h0: float,
               step_min: int = STEP_MIN) -> DayEvents:
    """Events of the body whose J2000 unit vector is vec_fn(jd), within [jd0, jd1) (one local day)."""
    alt = _alt_fn(vec_fn, lat, lon, (jd0 + jd1) / 2)
    step = step_min / 1440.0
    n = int(math.ceil((jd1 - jd0) / step)) + 2
    ts = [jd0 - step + i * step for i in range(n + 1)]       # one extra sample on each side so edge events are bracketed
    hs = [alt(t) for t in ts]
    ev = DayEvents()
    for i in range(len(ts) - 1):
        a, b = hs[i] - h0, hs[i + 1] - h0
        if (a < 0) != (b < 0):
            lo, hi = ts[i], ts[i + 1]
            for _ in range(24):
                mid = (lo + hi) / 2
                if (alt(mid) - h0 < 0) == (a < 0):
                    lo = mid
                else:
                    hi = mid
            t = (lo + hi) / 2
            if jd0 <= t < jd1:
                if b > a and ev.rise is None:
                    ev.rise = t
                elif b < a and ev.set is None:
                    ev.set = t
    for i in range(1, len(ts) - 1):
        if hs[i - 1] < hs[i] >= hs[i + 1]:
            lo, hi = ts[i - 1], ts[i + 1]
            for _ in range(40):
                m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
                if alt(m1) < alt(m2):
                    lo = m1
                else:
                    hi = m2
            t = (lo + hi) / 2
            if jd0 <= t < jd1 and ev.transit is None:
                ev.transit, ev.transit_alt = t, alt(t)
    if ev.rise is None and ev.set is None:
        ev.state = "always_up" if hs[len(hs) // 2] > h0 else "never_up"
    return ev


def fmt_time(jd: Optional[float], tz=None) -> str:
    if jd is None:
        return "—"
    d = astro.datetime_from_jd(jd + 0.5 / 86400.0)           # round to the nearest second before dropping them
    d = d.astimezone(tz) if tz is not None else d.astimezone()
    return f"{d:%H:%M}"


def sun_vec(jd: float) -> tuple:
    b = astro.sun_body(jd)
    return astro.radec_to_vec(b.ra, b.dec)


def body_events(name: str, jd: float, lat: float, lon: float, tz=None) -> DayEvents:
    """Events of 'Sole', 'Luna' or a planet name on the local day that contains `jd`."""
    j0, j1 = local_day_bounds(jd, tz)
    if name == "Sole":
        return day_events(sun_vec, j0, j1, lat, lon, H0_SUN)
    if name == "Luna":
        def moon_vec(t):
            m = astro.moon_topocentric(t, lat, lon)
            return astro.radec_to_vec(m.ra, m.dec)
        return day_events(moon_vec, j0, j1, lat, lon, H0_MOON)

    def planet_vec(t):
        b = astro.planet_body(name, t)
        return astro.radec_to_vec(b.ra, b.dec)
    return day_events(planet_vec, j0, j1, lat, lon, H0_STAR)


def fixed_events(vec: tuple, jd: float, lat: float, lon: float, tz=None) -> DayEvents:
    j0, j1 = local_day_bounds(jd, tz)
    return day_events(lambda _t: vec, j0, j1, lat, lon, H0_STAR)


def night_span(jd: float, lat: float, lon: float, tz=None) -> DayEvents:
    """Crossings of the Sun at -18 degrees: `rise` = end of the astronomical night (morning), `set` = its start (evening)."""
    j0, j1 = local_day_bounds(jd, tz)
    return day_events(sun_vec, j0, j1, lat, lon, H0_ASTRO_NIGHT)
