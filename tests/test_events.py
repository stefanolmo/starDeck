"""Rise / transit / set checked against astropy (builtin ephemeris) for Rome, 2026-11-16, and the polar edge cases."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stardeck import astro, events

ROME = ZoneInfo("Europe/Rome")
LAT, LON = 41.9, 12.5


def hm(jd, tz=ROME):
    return events.fmt_time(jd, tz)


def mins(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def noon(y, m, d, tz=ROME):
    return astro.jd_from_datetime(datetime(y, m, d, 12, 0, tzinfo=tz))


# (body, rise, transit, set) from astropy at 1-minute resolution
REFERENCE = [("Sole", "07:00", "11:55", "16:48"), ("Luna", "12:38", "17:44", "22:48"), ("Venere", "04:25", "09:52", "15:17"),
             ("Marte", "23:25", "06:24", "13:20"), ("Giove", "23:26", "06:22", "13:14")]


@pytest.mark.parametrize("name,rise,transit,set_", REFERENCE)
def test_bodies_match_reference(name, rise, transit, set_):
    ev = events.body_events(name, noon(2026, 11, 16), LAT, LON, ROME)
    for got, want in ((ev.rise, rise), (ev.transit, transit), (ev.set, set_)):
        assert got is not None and abs(mins(hm(got)) - mins(want)) <= 2, (name, hm(got), want)


def test_day_window_is_the_local_day():
    j0, j1 = events.local_day_bounds(noon(2026, 3, 29), ROME)        # DST starts on 2026-03-29: a 23-hour day
    assert j1 - j0 == pytest.approx(23 / 24)
    assert hm(j0) == "00:00"


def test_star_events_fall_within_the_day():
    v = astro.radec_to_vec(101.287, -16.716)                           # Sirius
    ev = events.fixed_events(v, noon(2026, 11, 16), LAT, LON, ROME)
    j0, j1 = events.local_day_bounds(noon(2026, 11, 16), ROME)
    assert ev.state == "normal" and all(j0 <= t < j1 for t in (ev.rise, ev.transit, ev.set))      # Sirius: transit ~03h, set ~10h, rise ~22h
    assert ev.set > ev.transit and ev.rise > ev.set
    assert ev.transit_alt == pytest.approx(90 - LAT - 16.716, abs=0.2)


def test_circumpolar_and_never_rises():
    polaris = astro.radec_to_vec(37.95, 89.26)
    assert events.fixed_events(polaris, noon(2026, 11, 16), LAT, LON, ROME).state == "always_up"
    crux = astro.radec_to_vec(186.65, -63.1)                           # Acrux, never rises from Rome
    assert events.fixed_events(crux, noon(2026, 11, 16), LAT, LON, ROME).state == "never_up"


def test_polar_midnight_sun_and_polar_night():
    tromso = ZoneInfo("Europe/Oslo")
    summer = events.body_events("Sole", noon(2026, 6, 21, tromso), 69.65, 18.96, tromso)
    winter = events.body_events("Sole", noon(2026, 12, 21, tromso), 69.65, 18.96, tromso)
    assert summer.state == "always_up" and winter.state == "never_up"


def test_astronomical_night_span():
    n = events.night_span(noon(2026, 11, 16), LAT, LON, ROME)
    assert n.set is not None and n.rise is not None and mins(hm(n.set)) > mins(hm(n.rise))     # evening start, morning end
    assert events.night_span(noon(2026, 6, 21), 55.0, 12.5, ROME).state == "always_up"       # no astronomical night at 55N in June
