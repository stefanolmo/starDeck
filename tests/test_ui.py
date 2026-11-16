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
    win.cfg.lat, win.cfg.lon = -33.87, 151.21
    win.view.set_config(win.cfg)
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


def test_place_combo_switches_location(win):
    c = win.place_combo
    i = c.findText("Tokyo")
    assert i >= 0
    c.setCurrentIndex(i)
    c.activated.emit(i)
    assert win.cfg.place == "Tokyo" and win.cfg.lat == pytest.approx(35.68)
    assert win.place_combo.currentText() == "Tokyo" and "35.68°N" in win.place_label.text()
    assert Config().load(win.qs).place == "Tokyo"
    win.view.grab()


def test_custom_place_saved_and_listed(win, monkeypatch):
    from stardeck import mainwindow
    from stardeck.settings_dialog import LocationDialog
    monkeypatch.setattr(LocationDialog, "exec", lambda self: 1)
    monkeypatch.setattr(LocationDialog, "result_place", lambda self: ("Il mio giardino", 39.5, 16.1))
    c = win.place_combo
    c.setCurrentIndex(c.count() - 1)                       # "Altro luogo…"
    c.activated.emit(c.count() - 1)
    assert win.cfg.place == "Il mio giardino" and win.cfg.lat == pytest.approx(39.5)
    assert c.itemText(0) == "★ Il mio giardino" and c.currentIndex() == 0
    assert mainwindow.parse_custom(win.cfg.custom_places) == [("Il mio giardino", 39.5, 16.1)]


def test_parse_custom_ignores_garbage():
    from stardeck.places import parse_custom
    assert parse_custom("a|1|2;bad;x|abc|2;y|95|0;|1|1;ok|-33.9|151.2") == [("a", 1.0, 2.0), ("ok", -33.9, 151.2)]
