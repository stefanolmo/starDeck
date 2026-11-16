import argparse
import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, astro, theme
from .mainwindow import APP_NAME, MainWindow
from .places import tzinfo, valid_tz
from .splash import SplashScreen


def parse_when(text: str, tz=None) -> float:
    """'2026-12-24 22:30' (wall-clock time at the observing place, `tz`) or ISO with offset/Z -> Julian date."""
    from datetime import datetime
    d = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if d.tzinfo is None and tz is not None:
        d = d.replace(tzinfo=tz)
    return astro.jd_from_datetime(d)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stardeck", description="Virtual planetarium: stars, constellations, planets, Sun and Moon for any time and place")
    ap.add_argument("--time", metavar="YYYY-MM-DD[ HH:MM]", help="start frozen at this time instead of 'now': wall-clock time at the observing place (ISO 8601; 'Z' or an offset for absolute time)")
    ap.add_argument("--lat", type=float, help="latitude in degrees north (overrides the saved location for this run)")
    ap.add_argument("--lon", type=float, help="longitude in degrees east")
    ap.add_argument("--tz", metavar="ZONE", help="IANA time zone of the place (default: guessed from the coordinates), e.g. Europe/Rome")
    ap.add_argument("--view", metavar="AZ,ALT[,FOV]", help="initial view direction in degrees (azimuth from north towards east)")
    ap.add_argument("--screenshot", metavar="PNG", help="(development) save a screenshot and exit")
    ap.add_argument("--no-splash", action="store_true", help="do not show the splash screen")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("stardeck")
    icon_path = os.path.join(os.path.dirname(__file__), "stardeck.svg")      # shipped inside the package
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    app.setStyleSheet(theme.STYLESHEET)
    f = QFont(app.font())
    f.setPointSize(10)
    app.setFont(f)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    w = MainWindow()
    if args.lat is not None or args.lon is not None or args.tz:
        lat = args.lat if args.lat is not None else w.cfg.lat
        lon = args.lon if args.lon is not None else w.cfg.lon
        name = "Personalizzato" if (args.lat is not None or args.lon is not None) else w.cfg.place
        tz = args.tz if args.tz and valid_tz(args.tz) else None
        if args.tz and tz is None:
            ap.error(f"unknown time zone: {args.tz}")
        w.set_place(name, lat, lon, tz or "", persist=False)
    if args.time:
        w.rate = 0
        w._update_rate_ui()
        w.view.set_time(parse_when(args.time, tzinfo(w.cfg.tz)))
        w._update_time_widgets(force=True)
    if args.view:
        parts = [float(x) for x in args.view.split(",")]
        w.view.set_view(parts[0], parts[1], parts[2] if len(parts) > 2 else None)
    use_splash = (w.cfg.show_splash and not (args.no_splash or args.screenshot or os.environ.get("STARDECK_NO_SPLASH")))
    splash = None
    if use_splash:
        splash = SplashScreen(__version__)
        splash.start()
        app.processEvents()
    if splash is None:
        w.show()
    else:
        splash.finished.connect(w.show)
        splash.finished.connect(w.raise_)
    if args.screenshot:
        QTimer.singleShot(int(os.environ.get("STARDECK_SHOT_DELAY", "800")),
                          lambda: (w.grab().save(args.screenshot), w.close(), app.quit()))
        w.show()
    rc = app.exec()
    return rc


if __name__ == "__main__":
    sys.exit(main())
