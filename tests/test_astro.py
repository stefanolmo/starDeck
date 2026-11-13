"""Positional astronomy checked against well-known values (astropy / USNO / Meeus worked examples)."""
import math
from datetime import datetime, timezone

import pytest

from stardeck import astro


def jd(y, mo, d, h=0, mi=0):
    return astro.jd_from_datetime(datetime(y, mo, d, h, mi, tzinfo=timezone.utc))


def test_julian_date_and_roundtrip():
    assert jd(2000, 1, 1, 12) == pytest.approx(2451545.0)
    assert astro.datetime_from_jd(2451545.0) == datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def test_sidereal_time_meeus_example():
    # Meeus ex. 12.a: 1987-04-10 0h UT -> GMST 13h10m46.3668s
    assert astro.gmst(jd(1987, 4, 10)) / 15.0 == pytest.approx(13 + 10 / 60 + 46.3668 / 3600, abs=1e-4)


def test_sun_at_j2000():
    s = astro.sun_body(2451545.0)
    assert s.ra == pytest.approx(281.29, abs=0.05) and s.dec == pytest.approx(-23.03, abs=0.05)
    assert s.dist_au == pytest.approx(0.98333, abs=1e-4)


def test_sun_solstice_declination():
    assert astro.sun_body(jd(2026, 6, 21, 12)).dec == pytest.approx(23.43, abs=0.05)


def test_moon_meeus_example():
    # Meeus ex. 47.a: 1992-04-12 0h TD -> lambda 133.167 deg, beta -3.229 deg, distance 368409.7 km
    lon, lat, dist = astro.moon_geocentric(2448724.5)
    assert lon == pytest.approx(133.167, abs=0.05)
    assert lat == pytest.approx(-3.229, abs=0.05)
    assert dist == pytest.approx(368409.7, abs=60)


def test_moon_phase_new_and_full():
    new = astro.moon_body(jd(2026, 11, 9, 14, 0))           # new moon 2026-11-09
    full = astro.moon_body(jd(2026, 11, 24, 14, 0))         # full moon 2026-11-24
    assert new.phase < 0.02 and full.phase > 0.98


def test_planets_against_reference():
    t = jd(2026, 11, 13, 21)
    bodies = {b.name: b for b in astro.planet_bodies(t)}
    assert set(bodies) == set(astro.PLANETS)
    assert bodies["Venere"].mag < -3.5 and bodies["Giove"].mag < -1.5
    for b in bodies.values():
        assert 0 <= b.ra < 360 and -30 < b.dec < 30            # all planets near the ecliptic


def test_venus_jupiter_conjunction_june_2026():
    t = jd(2026, 6, 9, 12)
    v = next(b for b in astro.planet_bodies(t) if b.name == "Venere")
    j = next(b for b in astro.planet_bodies(t) if b.name == "Giove")
    assert astro.angular_distance(v.ra, v.dec, j.ra, j.dec) < 2.0


def test_horizontal_coordinates_sirius():
    t = jd(2026, 11, 13, 21)
    h = astro.mat_mul(astro.eq_to_horizon_matrix(astro.lst(t, 12.5), 41.9), astro.precession_matrix(t))
    alt, az = astro.horizon_to_altaz(astro.mat_vec(h, astro.radec_to_vec(101.287, -16.716)))
    assert alt == pytest.approx(-4.71, abs=0.05) and az == pytest.approx(108.32, abs=0.05)     # astropy reference


def test_polaris_altitude_equals_latitude():
    t = jd(2026, 3, 1, 3)
    h = astro.mat_mul(astro.eq_to_horizon_matrix(astro.lst(t, 0.0), 45.0), astro.precession_matrix(t))
    alt, az = astro.horizon_to_altaz(astro.mat_vec(h, astro.radec_to_vec(37.95, 89.26)))
    assert alt == pytest.approx(45.0, abs=1.0) and (az < 3 or az > 357)


def test_twilight_and_phase_names():
    assert astro.twilight_state(-30) == "notte" and astro.twilight_state(10) == "giorno"
    assert astro.moon_phase_name(0.5, True) == "Primo quarto" and astro.moon_phase_name(0.99, True) == "Luna piena"


def test_formatting():
    assert astro.fmt_ra(88.79) == "05h 55m 09s" and astro.fmt_dec(-5.5).startswith("−05°")
