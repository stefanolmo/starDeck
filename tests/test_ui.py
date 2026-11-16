import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stardeck import astro, theme
from stardeck.catalog import Catalog
from stardeck.config import Config
from stardeck.mainwindow import MainWindow
from stardeck.settings_dialog import SettingsDialog
from stardeck.skyview import Frame, Picked
from stardeck.splash import SplashScreen

JD = astro.jd_from_datetime(datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc))


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.STYLESHEET)
    return a


@pytest.fixture(scope="module")
def catalog():
    return Catalog()


@pytest.fixture
def win(app, catalog, tmp_path):
    w = MainWindow(qs=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat), catalog=catalog, jd=JD)
    w.show()
    w.view.set_view(160.0, 38.0, 100.0)
    app.processEvents()
    yield w
    w.close()


def test_catalog_contents(catalog):
    assert len(catalog.stars) > 5000 and catalog.stars[0].name == "Sirius"
    assert len(catalog.constellations) == 88 and len(catalog.dsos) > 500
    assert catalog.constellations["Ori"].name == "Orione"
    assert [r[1] for r in catalog.find("sirius")] == ["Sirius"]
    assert catalog.find("m31")[0][2].name == "Galassia di Andromeda"


def test_projection_roundtrip_and_center(catalog):
    fr = Frame(JD, 41.9, 12.5, 200.0, 30.0, 90.0, 900, 700)
    # the view centre is the (az, alt) we asked for
    v = fr.unproject(fr.cx, fr.cy)
    alt, az = fr.altaz(v)
    assert alt == pytest.approx(30.0, abs=1e-6) and az == pytest.approx(200.0, abs=1e-6)
    for x, y in ((100, 80), (700, 500), (450, 20)):
        p = fr.project(fr.unproject(x, y))
        assert p[0] == pytest.approx(x, abs=1e-6) and p[1] == pytest.approx(y, abs=1e-6)


def test_east_is_on_the_left_looking_south(catalog):
    fr = Frame(JD, 41.9, 12.5, 180.0, 30.0, 90.0, 900, 700)
    east = fr.project_horizontal(astro.altaz_to_horizon(30.0, 120.0))
    west = fr.project_horizontal(astro.altaz_to_horizon(30.0, 240.0))
    assert east[0] < fr.cx < west[0]
    zenith = fr.project_horizontal(astro.altaz_to_horizon(80.0, 180.0))
    assert zenith[1] < fr.cy                                   # up on the screen


def test_paints_in_all_modes(win, app):
    for az, alt, fov in ((160, 38, 100), (0, 90, 150), (0, -90, 150), (90, 0, 5), (270, 10, 1.5)):
        win.view.set_view(az, alt, fov)
        assert not win.view.grab().isNull()
    for key in win.layer_boxes:
        win.layer_boxes[key].setChecked(not win.layer_boxes[key].isChecked())
    win.view.grab()
    for key in win.layer_boxes:
        win.layer_boxes[key].setChecked(not win.layer_boxes[key].isChecked())


def test_daylight_vs_night_limiting_magnitude(win):
    win.view.set_time(astro.jd_from_datetime(datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)))
    win.view.grab()
    assert win.view.sun_alt > 40 and win.view.limiting_mag() < 0
    win.view.set_time(JD)
    win.view.grab()
    assert win.view.sun_alt < -18 and win.view.limiting_mag() > 6


def test_search_selects_and_centres(win, app):
    win.search.setText("Betelgeuse")
    win._do_search()
    sel = win.view.selection
    assert sel is not None and sel.label == "Betelgeuse"
    QTest.qWait(700)
    alt, az = win.view.altaz_of(sel)
    assert abs(win.view.alt - alt) < 0.5 and abs(((win.view.az - az + 180) % 360) - 180) < 0.5 and win.view.fov <= 25.1
    assert "Betelgeuse" in win.info.text() and "Altezza" in win.info.text()


def test_search_planet_and_unknown(win):
    win.search.setText("giove")
    win._do_search()
    assert win.view.selection.kind == "planet" and win.view.selection.label == "Giove"
    win.search.setText("zzzz")
    win._do_search()
    assert "Nessun risultato" in win.status.text()


def test_click_picks_object(win, app):
    star = [s for s in win.cat.stars if s.name == "Capella"][0]          # high in the sky on this evening
    p = Picked("star", star, star.vec)
    win.view.set_view(*reversed(win.view.altaz_of(p)), 20.0)
    win.view.grab()
    QTest.mouseClick(win.view, Qt.LeftButton, Qt.NoModifier, QPointF(win.view.width() / 2, win.view.height() / 2).toPoint())
    assert win.view.selection is not None and win.view.selection.label == "Capella"


def test_drag_pans_view(win, app):
    az0, alt0 = win.view.az, win.view.alt
    c = QPointF(win.view.width() / 2, win.view.height() / 2).toPoint()
    QTest.mousePress(win.view, Qt.LeftButton, Qt.NoModifier, c)
    QTest.mouseMove(win.view, c + QPointF(120, 0).toPoint())
    QTest.mouseRelease(win.view, Qt.LeftButton, Qt.NoModifier, c + QPointF(120, 0).toPoint())
    assert win.view.az != az0 and win.view.alt == pytest.approx(alt0)


def test_time_controls(win):
    win.shift_time(1)
    assert win.view.jd == pytest.approx(JD + 1)
    win.rate = 0
    win.faster()
    assert win.rate == 1
    win.faster()
    assert win.rate == 60
    win.toggle_play()
    assert win.rate == 0
    win.go_now()
    assert win.rate == 1 and abs(win.view.jd - astro.jd_now()) < 5 / 86400


def test_layer_toggle_persists(win, tmp_path):
    win.layer_boxes["show_grid_altaz"].setChecked(True)
    assert Config().load(win.qs).show_grid_altaz is True


def test_settings_roundtrip(app):
    d = SettingsDialog(Config())
    d.place.setCurrentIndex(d.place.findText("Tokyo"))
    d._accept()
    assert d.cfg.place == "Tokyo" and d.cfg.lat == pytest.approx(35.68) and d.cfg.lon == pytest.approx(139.69)
    d2 = SettingsDialog(Config())
    d2.name.setText("  ")
    d2._accept()
    assert d2.err.text()


def test_southern_hemisphere_and_poles(win):
    win.set_place("Sydney", -33.87, 151.21, "Australia/Sydney")
    win.search.setText("Canopus")
    win._do_search()
    QTest.qWait(600)
    win.view.grab()
    win.cfg.lat = 90.0
    win.view.set_view(0, 50, 90)
    assert not win.view.grab().isNull()


def test_splash_paints(app):
    s = SplashScreen("0.1.0")
    for ms in (0, 1500, 2900):
        s.set_time(ms)
        assert not s.grab().isNull()


def _type_place(win, text):
    win.place_edit.setText(text)
    win._place_typed(text)


def test_place_search_autocomplete_and_timezone(win):
    _type_place(win, "tokyo")
    labels = win.place_model.stringList()
    assert labels and labels[0].startswith("Tokyo")
    win._place_picked(labels[0])
    assert win.cfg.place == "Tokyo" and win.cfg.tz == "Asia/Tokyo" and win.cfg.lat == pytest.approx(35.68)
    assert win.place_edit.text() == "Tokyo" and "35.68°N" in win.place_label.text()
    assert Config().load(win.qs).tz == "Asia/Tokyo"
    # 2026-11-13 21:00 UTC = 14/11 06:00 in Tokyo (UTC+9)
    assert win.dt_edit.dateTime().toString("dd/MM/yyyy HH:mm") == "14/11/2026 06:00"
    assert "Asia/Tokyo" in win.utc_label.text() and "UTC+9" in win.utc_label.text()
    win.view.grab()


def test_search_finds_small_town_from_gazetteer(win):
    _type_place(win, "vibo val")
    assert win.place_model.stringList()[0].startswith("Vibo Valentia")
    win._place_picked(win.place_model.stringList()[0])
    assert win.cfg.tz == "Europe/Rome"


def test_editing_clock_uses_place_timezone(win):
    win.set_place("Sydney", -33.87, 151.21, "Australia/Sydney")
    assert win.cfg.tz == "Australia/Sydney"
    win.rate = 0
    import calendar
    from datetime import timedelta
    from PySide6.QtCore import QDateTime, QTimeZone
    wall = calendar.timegm((2026, 12, 24, 22, 30, 0))
    win.dt_edit.setDateTime(QDateTime.fromSecsSinceEpoch(wall, QTimeZone.UTC))   # the edit holds the place's wall time as if it were UTC
    # Sydney is UTC+11 in December (DST): 22:30 local = 11:30 UTC
    u = astro.datetime_from_jd(win.view.jd) + timedelta(seconds=0.5)
    assert (u.month, u.day, u.hour, u.minute) == (12, 24, 11, 30)


def test_custom_place_saved_with_timezone(win, monkeypatch):
    from stardeck.settings_dialog import LocationDialog
    monkeypatch.setattr(LocationDialog, "exec", lambda self: 1)
    monkeypatch.setattr(LocationDialog, "result_place", lambda self: ("Il mio giardino", 39.5, 16.1, "Europe/Rome"))
    win._other_place()
    assert win.cfg.place == "Il mio giardino" and win.cfg.tz == "Europe/Rome"
    saved = win._saved_places()
    assert saved[0].name == "Il mio giardino" and saved[0].tz == "Europe/Rome" and saved[0].mine
    _type_place(win, "giardino")
    assert win.place_model.stringList()[0].startswith("★ Il mio giardino")


def test_guess_timezone_and_gazetteer():
    from stardeck.places import db, tzinfo, valid_tz
    d = db()
    assert d.guess_tz(41.9, 12.5) == "Europe/Rome" and d.guess_tz(-33.9, 151.2) == "Australia/Sydney"
    assert d.guess_tz(0.0, -150.0) == "Etc/GMT+10"                 # open ocean: from the longitude
    assert d.guess_tz(19.82, -155.47, "Mauna Kea (Hawaii)") == "Pacific/Honolulu"
    assert tzinfo("") is None and tzinfo("Nope/Nope") is None and valid_tz("Europe/Rome")
    assert [p.name for p in d.search("napoli", __import__("stardeck.places", fromlist=["x"]).preset_places())][0] == "Napoli"
    assert d.search("x") == []


def test_parse_custom_ignores_garbage():
    from stardeck.places import parse_custom
    got = parse_custom("a|1|2;bad;x|abc|2;y|95|0;|1|1;ok|-33.9|151.2|Australia/Sydney")
    assert [(p.name, p.lat, p.lon, p.tz) for p in got] == [("a", 1.0, 2.0, ""), ("ok", -33.9, 151.2, "Australia/Sydney")]


def test_events_card_and_clipping(win):
    win._update_events(force=True)
    win.show(); win.repaint()
    sun = win.ev_cells["Sole"]
    assert all(":" in c.text() for c in sun[1:])
    assert "Notte astronomica" in win.night_label.text()
    assert "SORGE E TRAMONTA" in win.ev_card.title_label.text()
    # every label of the cards is fully visible: its height fits its text (nothing clipped)
    for lab in (win.sky_sun, win.sky_moon, *[c for row in win.ev_cells.values() for c in row]):
        assert lab.height() >= lab.fontMetrics().height()


def test_events_follow_place_and_selection(win):
    win.set_place("Tromsø", 69.65, 18.96, "Europe/Oslo")
    win.view.set_time(astro.jd_from_datetime(datetime(2026, 12, 21, 12, 0, tzinfo=timezone.utc)))
    win._update_events(force=True)
    assert win.ev_cells["Sole"][1].text() == "non sorge" and win.ev_cells["Sole"][2].isHidden()
    win.set_place("Roma", 41.9, 12.5, "Europe/Rome")
    win.search.setText("Sirius")
    win._do_search()
    assert "Culmine" in win.info.text() and "Sorge" in win.info.text() and "Tramonta" in win.info.text()
