"""Regenerates the README screenshots (offscreen, deterministic time and place):  QT_QPA_PLATFORM=offscreen python3 docs/make_screenshots.py"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from stardeck import __version__, astro, theme
from stardeck.mainwindow import MainWindow
from stardeck.skyview import Picked
from stardeck.splash import SplashScreen

HERE = os.path.dirname(__file__)


def main():
    app = QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    qs = QSettings("/tmp/stardeck_shots.ini", QSettings.IniFormat)
    qs.clear()
    jd = astro.jd_from_datetime(datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc))
    w = MainWindow(qs=qs, jd=jd)
    w.cfg.place, w.cfg.lat, w.cfg.lon = "Roma", 41.9, 12.5
    w._update_place_label()
    w.resize(1280, 800)
    w.show()
    w.view.set_view(160.0, 38.0, 100.0)
    app.processEvents()
    w.grab().save(os.path.join(HERE, "main.png"))
    star = [s for s in w.cat.stars if s.name == "Betelgeuse"][0]
    w.view.fov = 28.0
    w._pick(Picked("star", star, star.vec), 28.0)
    w.view._anim = None
    alt, az = w.view.altaz_of(w.view.selection)
    w.view.set_view(az, alt, 28.0)
    w.cfg.show_grid_eq = True
    w.layer_boxes["show_grid_eq"].setChecked(True)
    app.processEvents()
    w.grab().save(os.path.join(HERE, "orion.png"))
    s = SplashScreen(__version__)
    s.set_time(2100)
    s.grab().save(os.path.join(HERE, "splash.png"))


if __name__ == "__main__":
    main()
