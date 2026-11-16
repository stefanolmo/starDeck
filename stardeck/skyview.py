"""The sky itself: stereographic all-sky view with stars, constellations, deep-sky objects, Sun, Moon, planets, horizon."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from . import astro, theme
from .astro import D2R, R2D
from .catalog import Catalog
from .config import Config

FOV_MIN, FOV_MAX = 1.0, 150.0

PLANET_COLORS = {"Mercurio": "#cfc6b8", "Venere": "#fff6dc", "Marte": "#ff8a5c", "Giove": "#f3dcb6", "Saturno": "#f0dc9a",
                 "Urano": "#9be8ee", "Nettuno": "#7fa6ff"}
# (sun altitude, zenith colour, horizon colour)
SKY_KEYS = [(-20, (3, 6, 13), (8, 14, 30)), (-12, (6, 12, 30), (22, 34, 66)), (-6, (16, 30, 66), (96, 86, 110)),
            (-1, (36, 66, 120), (236, 140, 96)), (3, (56, 105, 170), (190, 196, 210)), (12, (60, 128, 205), (150, 196, 236))]
BV_KEYS = [(-0.3, (146, 172, 255)), (0.0, (175, 196, 255)), (0.3, (206, 218, 255)), (0.58, (255, 246, 238)), (0.8, (255, 232, 205)),
           (1.2, (255, 203, 150)), (1.7, (255, 165, 100)), (2.2, (255, 130, 80))]
CARDINALS = [(0, "N", True), (45, "NE", False), (90, "E", True), (135, "SE", False), (180, "S", True), (225, "SO", False),
             (270, "O", True), (315, "NO", False)]


def _lerp_keys(keys, x):
    if x <= keys[0][0]:
        return keys[0][1:]
    for (x0, *a), (x1, *b) in zip(keys, keys[1:]):
        if x <= x1:
            t = (x - x0) / (x1 - x0)
            return tuple(tuple(ai + (bi - ai) * t for ai, bi in zip(ca, cb)) for ca, cb in zip(a, b))
    return keys[-1][1:]


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def star_color(bv: float) -> QColor:
    bv = max(BV_KEYS[0][0], min(BV_KEYS[-1][0], bv))
    for (x0, c0), (x1, c1) in zip(BV_KEYS, BV_KEYS[1:]):
        if bv <= x1:
            return QColor(*[int(v) for v in _mix(c0, c1, (bv - x0) / (x1 - x0))])
    return QColor(*BV_KEYS[-1][1])


_STAR_COLORS = [star_color(-0.3 + i * 0.1) for i in range(26)]


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


@dataclass
class Picked:
    kind: str                # star | planet | sun | moon | dso | const
    obj: object
    vec: tuple               # J2000 unit vector at the time of picking

    @property
    def label(self) -> str:
        o = self.obj
        if self.kind in ("star", "dso"):
            return o.label()
        return o.name


class Frame:
    """Projection state for one paint: time, place and view direction -> matrices and screen mapping."""

    def __init__(self, jd, lat, lon, az, alt, fov, w, h):
        self.jd, self.lat, self.lon, self.az, self.alt, self.fov = jd, lat, lon, az, alt, fov
        self.lst = astro.lst(jd, lon)
        self.prec = astro.precession_matrix(jd)
        self.eq2hor = astro.eq_to_horizon_matrix(self.lst, lat)               # equator of date -> horizontal
        self.j2hor = astro.mat_mul(self.eq2hor, self.prec)                    # J2000 -> horizontal
        c = astro.altaz_to_horizon(alt, az)
        r = (-math.sin(az * D2R), math.cos(az * D2R), 0.0)
        u = (-math.sin(alt * D2R) * math.cos(az * D2R), -math.sin(alt * D2R) * math.sin(az * D2R), math.cos(alt * D2R))
        self.basis = (c, r, u)
        self.M = astro.mat_mul(self.basis, self.j2hor)                        # J2000 -> view
        self.MD = astro.mat_mul(self.basis, self.eq2hor)                      # equator of date -> view
        self.w, self.h = w, h
        self.cx, self.cy = w / 2.0, h / 2.0
        self.s = (min(w, h) / 2.0) / (2.0 * math.tan(fov * D2R / 4.0))        # pixels per stereographic unit
        rho_max = math.hypot(self.cx, self.cy) / self.s
        self.cos_lim = math.cos(2.0 * math.atan(rho_max / 2.0))               # anything further than the corners is off screen

    def project(self, v, m=None):
        """Unit vector (in the frame `m` maps from; default J2000) -> (x, y, d0); None if not drawable."""
        m = m or self.M
        d0 = m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2]
        if d0 < -0.9:
            return None
        k = 2.0 / (1.0 + d0) * self.s
        return (self.cx + k * (m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2]),
                self.cy - k * (m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]), d0)

    def project_horizontal(self, v):
        return self.project(v, self.basis)

    def unproject(self, x, y):
        """Screen point -> J2000 unit vector."""
        px, py = (x - self.cx) / self.s, (self.cy - y) / self.s
        r2 = px * px + py * py
        d = ((4.0 - r2) / (4.0 + r2), 4.0 * px / (4.0 + r2), 4.0 * py / (4.0 + r2))
        # view -> J2000 : transpose of M
        t = astro.transpose(self.M)
        return astro.mat_vec(t, d)

    def below_horizon(self, v_j2000, margin: float = 0.0) -> bool:
        m = self.j2hor[2]
        return m[0] * v_j2000[0] + m[1] * v_j2000[1] + m[2] * v_j2000[2] < -margin

    def altaz(self, v_j2000):
        return astro.horizon_to_altaz(astro.mat_vec(self.j2hor, v_j2000))


class SkyView(QWidget):
    selected = Signal(object)         # Picked | None
    hovered = Signal(object)          # Picked | None
    viewChanged = Signal()

    def __init__(self, catalog: Catalog, cfg: Config, parent=None):
        super().__init__(parent)
        self.cat, self.cfg = catalog, cfg
        self.jd = astro.jd_now()
        self.az, self.alt, self.fov = 180.0, 35.0, 100.0
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.frame: Optional[Frame] = None
        self.bodies: dict[str, astro.Body] = {}
        self.body_vecs: dict[str, tuple] = {}
        self.sun_alt = -30.0
        self.moon_waxing = True
        self.selection: Optional[Picked] = None
        self.hover: Optional[Picked] = None
        self.track = False
        self._hits: list = []
        self._press = None
        self._moved = False
        self._anim = None
        self._anim_clock = QElapsedTimer()
        self._anim_timer = QTimer(self, interval=16)
        self._anim_timer.timeout.connect(self._anim_step)
        self._font = QFont("sans", 9)
        self._font_small = QFont("sans", 8)
        self._font_const = QFont("sans", 9)
        self._font_const.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        self._font_const.setWeight(QFont.DemiBold)

    # ------------------------------------------------------------------ state
    def set_time(self, jd: float) -> None:
        self.jd = jd
        self.update()

    def set_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self.update()

    def set_view(self, az: float, alt: float, fov: Optional[float] = None) -> None:
        self.az = az % 360.0
        self.alt = _clamp(alt, -90.0, 90.0)
        if fov is not None:
            self.fov = _clamp(fov, FOV_MIN, FOV_MAX)
        self.update()
        self.viewChanged.emit()

    def current_vec(self, p: Picked) -> tuple:
        if p.kind in ("planet", "sun", "moon"):
            return self.body_vecs.get(p.obj.name, p.vec)
        return p.vec

    def altaz_of(self, p: Picked) -> tuple:
        fr = self.frame or self._make_frame()
        return fr.altaz(self.current_vec(p))

    def goto(self, p: Picked, fov: Optional[float] = None, track: bool = False) -> None:
        alt, az = self.altaz_of(p)
        self.track = track
        self.animate_to(az, alt, fov)

    def animate_to(self, az: float, alt: float, fov: Optional[float] = None, ms: int = 450) -> None:
        daz = (az - self.az + 180.0) % 360.0 - 180.0
        self._anim = (self.az, self.alt, self.fov, daz, alt - self.alt, (fov - self.fov) if fov else 0.0, ms)
        self._anim_clock.start()
        self._anim_timer.start()

    def _anim_step(self) -> None:
        if self._anim is None:
            self._anim_timer.stop()
            return
        az0, alt0, fov0, daz, dalt, dfov, ms = self._anim
        t = min(1.0, self._anim_clock.elapsed() / ms)
        e = t * t * (3 - 2 * t)
        self.az, self.alt, self.fov = (az0 + daz * e) % 360.0, alt0 + dalt * e, fov0 + dfov * e
        if t >= 1.0:
            self._anim = None
            self._anim_timer.stop()
        self.update()
        self.viewChanged.emit()

    # ------------------------------------------------------------------ computation
    def _make_frame(self) -> Frame:
        return Frame(self.jd, self.cfg.lat, self.cfg.lon, self.az, self.alt, self.fov, max(self.width(), 1), max(self.height(), 1))

    def _update_bodies(self) -> None:
        jd = self.jd
        bodies = {b.name: b for b in astro.planet_bodies(jd)}
        bodies["Sole"] = astro.sun_body(jd)
        moon = astro.moon_topocentric(jd, self.cfg.lat, self.cfg.lon)
        lst = astro.lst(jd, self.cfg.lon)
        prec = astro.precession_matrix(jd)
        bodies["Luna"] = moon
        self.bodies = bodies
        self.body_vecs = {n: astro.radec_to_vec(b.ra, b.dec) for n, b in bodies.items()}
        self.moon_waxing = ((moon.ra - bodies["Sole"].ra) % 360.0) < 180.0
        sun_alt, _ = astro.horizon_to_altaz(astro.mat_vec(astro.mat_mul(astro.eq_to_horizon_matrix(lst, self.cfg.lat), prec),
                                                          self.body_vecs["Sole"]))
        self.sun_alt = sun_alt

    def limiting_mag(self) -> float:
        lim = 6.2 if self.fov < 110 else 5.4
        if self.cfg.show_atmosphere:
            lim -= 8.0 * _clamp((self.sun_alt + 18.0) / 18.0, 0.0, 1.0)
        return lim

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _ev) -> None:
        self._update_bodies()
        if self.track and self.selection is not None:
            alt, az = astro.horizon_to_altaz(astro.mat_vec(astro.mat_mul(astro.eq_to_horizon_matrix(astro.lst(self.jd, self.cfg.lon), self.cfg.lat),
                                                                         astro.precession_matrix(self.jd)), self.current_vec(self.selection)))
            if self._anim is None:
                self.az, self.alt = az, alt
        fr = self.frame = self._make_frame()
        self._hits = []
        self._occupied: list[QRectF] = []
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        night = _clamp((-self.sun_alt - 6.0) / 12.0, 0.0, 1.0) if self.cfg.show_atmosphere else 1.0
        self._paint_sky(p, fr)
        if self.cfg.show_milky_way and night > 0.05 and self.fov > 16:
            self._paint_milky_way(p, fr, night)
        if self.cfg.show_grid_eq:
            self._paint_eq_grid(p, fr)
        if self.cfg.show_ecliptic:
            self._paint_ecliptic(p, fr)
        if self.cfg.show_grid_altaz:
            self._paint_altaz_grid(p, fr)
        if self.cfg.show_constellation_lines:
            self._paint_constellation_lines(p, fr)
        if self.cfg.show_dso:
            self._paint_dso(p, fr)
        self._paint_stars(p, fr)
        self._paint_bodies(p, fr)
        if self.cfg.show_ground:
            self._paint_ground(p, fr)
        self._paint_labels(p, fr)
        self._paint_selection(p, fr)
        self._paint_hud(p, fr)
        p.end()

    # ---- background
    def _sky_colors(self):
        if not self.cfg.show_atmosphere:
            return (3, 6, 13), (8, 14, 30)
        return _lerp_keys(SKY_KEYS, self.sun_alt)

    def _paint_sky(self, p: QPainter, fr: Frame) -> None:
        top, hor = self._sky_colors()
        hp = fr.project_horizontal(astro.altaz_to_horizon(0.0, self.az)) if self.alt > -85 else None
        if hp is not None and self.alt < 89:
            y0 = _clamp(hp[1], -fr.h, 2 * fr.h)
        else:
            y0 = fr.h * 1.2
        g = QLinearGradient(0, y0, 0, y0 - max(fr.h * 0.9, 1))
        g.setColorAt(0, QColor(*[int(c) for c in hor]))
        g.setColorAt(1, QColor(*[int(c) for c in top]))
        p.fillRect(self.rect(), QBrush(g))

    def _paint_ground(self, p: QPainter, fr: Frame) -> None:
        top, hor = self._sky_colors()
        gc = QColor(*[int(c * 0.34 + k) for c, k in zip(hor, (10, 15, 12))])
        gc.setAlpha(245)
        a = self.alt
        sa = math.sin(a * D2R)
        path = QPainterPath()
        rect = QRectF(-5, -5, fr.w + 10, fr.h + 10)
        if abs(sa) < 2e-3:
            path.addRect(QRectF(-5, fr.cy, fr.w + 10, fr.h))
            line = (QPointF(-5, fr.cy), QPointF(fr.w + 5, fr.cy))
            circle = None
        else:
            cy = fr.cy - fr.s * 2.0 * math.cos(a * D2R) / sa
            rad = fr.s * 2.0 / abs(sa)
            circle = (QPointF(fr.cx, cy), rad)
            if sa > 0:
                path.addRect(rect)
                hole = QPainterPath()
                hole.addEllipse(QPointF(fr.cx, cy), rad, rad)
                path = path.subtracted(hole)
            else:
                path.addEllipse(QPointF(fr.cx, cy), rad, rad)
        p.setPen(Qt.NoPen)
        p.setBrush(gc)
        p.drawPath(path)
        edge = QColor(*[int(min(255, c * 0.8 + 40)) for c in hor])
        edge.setAlpha(45)
        p.setPen(QPen(edge, 7.0))
        p.setBrush(Qt.NoBrush)
        if circle is None:
            p.drawLine(*line)
        elif circle[1] < 1e6:
            p.drawEllipse(circle[0], circle[1], circle[1])
        edge.setAlpha(170)
        p.setPen(QPen(edge, 1.6))
        p.setBrush(Qt.NoBrush)
        if circle is None:
            p.drawLine(*line)
        elif circle[1] < 1e6:
            p.drawEllipse(circle[0], circle[1], circle[1])

    # ---- lines
    def _draw_polyline(self, p: QPainter, fr: Frame, vecs, m=None, close=False) -> None:
        run = []
        pts = [fr.project(v, m) for v in vecs]
        if close:
            pts.append(pts[0])
        for q in pts:
            if q is None or q[2] < fr.cos_lim - 0.15:
                if len(run) > 1:
                    p.drawPolyline(QPolygonF(run))
                run = []
            else:
                run.append(QPointF(q[0], q[1]))
        if len(run) > 1:
            p.drawPolyline(QPolygonF(run))

    def _paint_altaz_grid(self, p: QPainter, fr: Frame) -> None:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(70, 140, 255, 70), 1))
        for alt in range(-60, 90, 15):
            self._draw_polyline(p, fr, [astro.altaz_to_horizon(alt, a) for a in range(0, 361, 3)], fr.basis)
        for az in range(0, 360, 30):
            self._draw_polyline(p, fr, [astro.altaz_to_horizon(a, az) for a in range(-90, 91, 3)], fr.basis)
        p.setPen(QPen(QColor(70, 140, 255, 110), 1, Qt.DashLine))
        self._draw_polyline(p, fr, [astro.altaz_to_horizon(0, a) for a in range(0, 361, 2)], fr.basis)

    def _paint_eq_grid(self, p: QPainter, fr: Frame) -> None:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(200, 110, 255, 70), 1))
        for dec in range(-75, 90, 15):
            self._draw_polyline(p, fr, [astro.radec_to_vec(ra, dec) for ra in range(0, 361, 3)], fr.MD)
        for ra in range(0, 360, 30):
            self._draw_polyline(p, fr, [astro.radec_to_vec(ra, d) for d in range(-90, 91, 3)], fr.MD)
        p.setPen(QPen(QColor(200, 110, 255, 120), 1, Qt.DashLine))
        self._draw_polyline(p, fr, [astro.radec_to_vec(ra, 0) for ra in range(0, 361, 2)], fr.MD)

    def _paint_ecliptic(self, p: QPainter, fr: Frame) -> None:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(251, 191, 36, 95), 1.2, Qt.DashDotLine))
        vecs = [astro.ecliptic_to_equatorial((math.cos(l * D2R), math.sin(l * D2R), 0.0)) for l in range(0, 361, 2)]
        self._draw_polyline(p, fr, vecs)

    def _paint_constellation_lines(self, p: QPainter, fr: Frame) -> None:
        p.setBrush(Qt.NoBrush)
        day = 1.0 - _clamp((-self.sun_alt - 6.0) / 12.0, 0.0, 1.0) if self.cfg.show_atmosphere else 0.0
        p.setPen(QPen(QColor(90, 150, 220, int(110 - 70 * day)), 1.1))
        M, cx, cy, s, cl = fr.M, fr.cx, fr.cy, fr.s, fr.cos_lim - 0.15
        m0, m1, m2 = M
        path = QPainterPath()
        for con in self.cat.constellations.values():
            for line in con.lines:
                started = False
                for v in line:
                    d0 = m0[0] * v[0] + m0[1] * v[1] + m0[2] * v[2]
                    if d0 < cl:
                        started = False
                        continue
                    k = 2.0 / (1.0 + d0) * s
                    x = cx + k * (m1[0] * v[0] + m1[1] * v[1] + m1[2] * v[2])
                    y = cy - k * (m2[0] * v[0] + m2[1] * v[1] + m2[2] * v[2])
                    if started:
                        path.lineTo(x, y)
                    else:
                        path.moveTo(x, y)
                        started = True
        p.drawPath(path)

    def _paint_milky_way(self, p: QPainter, fr: Frame, night: float) -> None:
        """Brightness outlines drawn at 1/6 resolution and scaled up smoothly: soft edges instead of contour steps."""
        f = 6
        w, h = max(1, fr.w // f), max(1, fr.h // f)
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(Qt.NoPen)
        q.setBrush(QColor(150, 178, 235, int(13 * night * _clamp((self.fov - 15.0) / 45.0, 0.0, 1.0))))
        far = 6.0 * max(w, h)
        M, s, cx, cy = fr.M, fr.s / f, fr.cx / f, fr.cy / f
        for level in self.cat.milky_way:
            for ring in level:
                poly = []
                for v in ring:
                    d0 = M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2]
                    if d0 < -0.98:
                        continue
                    d1 = M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2]
                    d2 = M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2]
                    if d0 < -0.2:                              # behind the observer: push radially far away
                        n = math.hypot(d1, d2) or 1.0
                        poly.append(QPointF(cx + far * d1 / n, cy - far * d2 / n))
                    else:
                        k = 2.0 / (1.0 + d0) * s
                        poly.append(QPointF(cx + k * d1, cy - k * d2))
                if len(poly) > 2:
                    q.drawPolygon(QPolygonF(poly))
        q.end()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(self.rect(), img)

    # ---- deep sky
    def _paint_dso(self, p: QPainter, fr: Frame) -> None:
        if self.sun_alt > -6 and self.cfg.show_atmosphere:
            return
        lim = 2.5 + 6.5 * (1.0 - self.fov / FOV_MAX)
        p.setBrush(Qt.NoBrush)
        for d in self.cat.dsos:
            messier = d.desig.startswith("M ")
            if d.mag is None and not (messier and self.fov < 40):
                continue
            if d.mag is not None and (d.mag > lim or (not messier and (self.fov > 25 or d.mag > 7.5))):
                continue
            q = fr.project(d.vec)
            if q is None or q[2] < fr.cos_lim or not (-20 < q[0] < fr.w + 20 and -20 < q[1] < fr.h + 20):
                continue
            if self.cfg.show_ground and fr.below_horizon(d.vec):
                continue
            x, y, d0 = q
            r = _clamp(fr.s * (d.size / 120.0) * D2R * 2.0 / (1.0 + d0), 4.0, 70.0)
            col = QColor(140, 200, 255, 190) if d.type in ("s", "s0", "g", "gg", "sd", "i", "e") else \
                QColor(255, 190, 130, 190) if d.type in ("bn", "en", "rn", "sfr", "snr", "pn") else QColor(180, 230, 170, 190)
            p.setPen(QPen(col, 1.1))
            if d.type in ("s", "s0", "g", "gg", "sd", "i", "e"):
                p.save(); p.translate(x, y); p.rotate(-30)
                p.drawEllipse(QPointF(0, 0), r, r * 0.5)
                p.restore()
            elif d.type in ("gc",):
                p.drawEllipse(QPointF(x, y), r, r)
                p.drawLine(QPointF(x - r, y), QPointF(x + r, y)); p.drawLine(QPointF(x, y - r), QPointF(x, y + r))
            elif d.type == "oc":
                pen = QPen(col, 1.1, Qt.DotLine)
                p.setPen(pen)
                p.drawEllipse(QPointF(x, y), r, r)
            elif d.type == "pn":
                p.drawEllipse(QPointF(x, y), r * 0.6, r * 0.6)
                p.drawLine(QPointF(x - r, y), QPointF(x - r * 0.6, y)); p.drawLine(QPointF(x + r * 0.6, y), QPointF(x + r, y))
            else:
                p.drawRect(QRectF(x - r * 0.8, y - r * 0.8, r * 1.6, r * 1.6))
            self._hits.append((x, y, max(r, 7.0), 3, Picked("dso", d, d.vec)))
            if messier or self.fov < 25:
                self._label(p, d.label(), x + r + 3, y - 2, QColor(col.red(), col.green(), col.blue(), 200), self._font_small, prio=3)

    # ---- stars
    def _paint_stars(self, p: QPainter, fr: Frame) -> None:
        lim = self.limiting_mag()
        zoom = _clamp((60.0 / self.fov) ** 0.45, 0.8, 2.4) * self.cfg.star_scale
        M, cx, cy, s, cos_lim = fr.M, fr.cx, fr.cy, fr.s, fr.cos_lim
        (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = M
        w, h = fr.w + 10, fr.h + 10
        p.setPen(Qt.NoPen)
        halo_list = []
        for st in self.cat.stars:
            mag = st.mag
            if mag > lim:
                break
            vx, vy, vz = st.vec
            d0 = a0 * vx + a1 * vy + a2 * vz
            if d0 < cos_lim:
                continue
            k = 2.0 / (1.0 + d0) * s
            x = cx + k * (b0 * vx + b1 * vy + b2 * vz)
            y = cy - k * (c0 * vx + c1 * vy + c2 * vz)
            if x < -10 or y < -10 or x > w or y > h:
                continue
            r = (0.75 + 0.42 * (lim + 0.3 - mag)) * zoom * 0.62
            col = _STAR_COLORS[int(_clamp((st.bv + 0.3) * 10, 0, 25))]
            if r < 1.0:
                col = QColor(col)
                col.setAlphaF(_clamp(r / 0.9 + 0.15, 0.2, 1.0))
                r = 0.55 + r * 0.3
            p.setBrush(col)
            p.drawEllipse(QPointF(x, y), r, r)
            if mag < 2.3:
                halo_list.append((x, y, r, col))
            if (mag < 5.2 or self.fov < 40) and not (self.cfg.show_ground and fr.below_horizon(st.vec)):
                self._hits.append((x, y, max(r, 6.0), 2 if (st.name or mag < 3) else 4, Picked("star", st, st.vec)))
        for x, y, r, col in halo_list:
            g = QRadialGradient(QPointF(x, y), r * 4.2)
            c = QColor(col); c.setAlpha(95)
            g.setColorAt(0, c)
            c = QColor(col); c.setAlpha(0)
            g.setColorAt(1, c)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(x, y), r * 4.2, r * 4.2)

    # ---- Sun, Moon, planets
    def _body_xy(self, fr: Frame, name: str):
        return fr.project(self.body_vecs[name])

    def _paint_bodies(self, p: QPainter, fr: Frame) -> None:
        if self.cfg.show_planets:
            for name in astro.PLANETS:
                b = self.bodies[name]
                q = self._body_xy(fr, name)
                if q is None or q[2] < fr.cos_lim or not (-30 < q[0] < fr.w + 30 and -30 < q[1] < fr.h + 30):
                    continue
                if self.cfg.show_atmosphere and b.mag > self.limiting_mag() + 1.0:
                    continue                                   # washed out by daylight
                if self.cfg.show_ground and fr.below_horizon(self.body_vecs[name], 0.01):
                    continue
                x, y = q[0], q[1]
                r = _clamp(2.6 + (1.5 - b.mag) * 0.55, 2.4, 6.5) * _clamp((60.0 / self.fov) ** 0.3, 0.9, 1.6)
                col = QColor(PLANET_COLORS[name])
                g = QRadialGradient(QPointF(x, y), r * 3.6)
                gc = QColor(col); gc.setAlpha(80)
                g.setColorAt(0, gc)
                gc = QColor(col); gc.setAlpha(0)
                g.setColorAt(1, gc)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(g))
                p.drawEllipse(QPointF(x, y), r * 3.6, r * 3.6)
                p.setBrush(col)
                p.drawEllipse(QPointF(x, y), r, r)
                if name == "Saturno":
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 200), 1.2))
                    p.save(); p.translate(x, y); p.rotate(-18)
                    p.drawEllipse(QPointF(0, 0), r * 2.1, r * 0.7)
                    p.restore()
                self._hits.append((x, y, max(r + 3, 9.0), 0, Picked("planet", b, self.body_vecs[name])))
                self._label(p, name, x + r + 5, y + 4, QColor(col.red(), col.green(), col.blue(), 230), self._font, prio=0)
        # Sun
        q = self._body_xy(fr, "Sole")
        sun = self.bodies["Sole"]
        if q is not None and q[2] > fr.cos_lim and -200 < q[0] < fr.w + 200 and -200 < q[1] < fr.h + 200:
            x, y, d0 = q
            r = max(8.0, fr.s * 2.0 / (1 + d0) * sun.angsize * D2R / 2.0)
            g = QRadialGradient(QPointF(x, y), r * 7)
            g.setColorAt(0, QColor(255, 236, 170, 200)); g.setColorAt(0.25, QColor(255, 200, 100, 80)); g.setColorAt(1, QColor(255, 180, 80, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(x, y), r * 7, r * 7)
            p.setBrush(QColor(255, 244, 200))
            p.drawEllipse(QPointF(x, y), r, r)
            self._hits.append((x, y, r + 6, 0, Picked("sun", sun, self.body_vecs["Sole"])))
            self._label(p, "Sole", x + r + 6, y + 4, QColor(255, 230, 160), self._font, prio=0)
        # Moon
        q = self._body_xy(fr, "Luna")
        moon = self.bodies["Luna"]
        if q is not None and q[2] > fr.cos_lim and -100 < q[0] < fr.w + 100 and -100 < q[1] < fr.h + 100:
            x, y, d0 = q
            r = max(9.0, fr.s * 2.0 / (1 + d0) * moon.angsize * D2R / 2.0)
            self._draw_moon(p, fr, x, y, r, moon)
            self._hits.append((x, y, r + 4, 0, Picked("moon", moon, self.body_vecs["Luna"])))
            self._label(p, "Luna", x + r + 6, y + 4, QColor(225, 228, 235), self._font, prio=0)

    def _draw_moon(self, p: QPainter, fr: Frame, x: float, y: float, r: float, moon: astro.Body) -> None:
        sq = self._body_xy(fr, "Sole")
        ang = math.degrees(math.atan2(sq[1] - y, sq[0] - x)) if sq is not None else 0.0
        # glow
        g = QRadialGradient(QPointF(x, y), r * 3.2)
        g.setColorAt(0, QColor(220, 225, 240, int(70 * moon.phase))); g.setColorAt(1, QColor(220, 225, 240, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(x, y), r * 3.2, r * 3.2)
        p.save()
        p.translate(x, y)
        p.rotate(ang)
        p.setBrush(QColor(34, 40, 50))
        p.drawEllipse(QPointF(0, 0), r, r)
        k = moon.phase
        rx = abs(2 * k - 1) * r
        path = QPainterPath()
        path.moveTo(0, -r)
        path.arcTo(QRectF(-r, -r, 2 * r, 2 * r), 90, -180)
        path.arcTo(QRectF(-rx, -r, 2 * rx, 2 * r), 270, -180 if k > 0.5 else 180)
        path.closeSubpath()
        lit = QRadialGradient(QPointF(r * 0.2, -r * 0.1), r * 1.2)
        lit.setColorAt(0, QColor(246, 244, 232)); lit.setColorAt(1, QColor(208, 206, 196))
        p.setBrush(QBrush(lit))
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), 0.8))
        p.drawEllipse(QPointF(0, 0), r, r)
        p.restore()

    # ---- text
    def _label(self, p: QPainter, text: str, x: float, y: float, color: QColor, font: QFont, prio: int = 5, center: bool = False) -> bool:
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(text)
        rect = QRectF(x - (w / 2 if center else 0), y - fm.ascent(), w, fm.height())
        pad = rect.adjusted(-3, -2, 3, 2)
        if rect.right() < 0 or rect.left() > self.width() or rect.bottom() < 0 or rect.top() > self.height():
            return False
        for o in self._occupied:
            if o.intersects(pad):
                return False
        self._occupied.append(pad)
        p.setFont(font)
        p.setPen(QColor(0, 0, 0, 140))
        p.drawText(QPointF(rect.left() + 1, y + 1), text)
        p.setPen(color)
        p.drawText(QPointF(rect.left(), y), text)
        return True

    def _paint_labels(self, p: QPainter, fr: Frame) -> None:
        # star names
        if self.cfg.show_star_names:
            lim = 1.0 + 5.0 * (1.0 - min(self.fov, 110.0) / 110.0) ** 0.9
            if self.cfg.show_atmosphere:
                lim = min(lim, self.limiting_mag() - 0.3)
            for st in self.cat.named:
                if st.mag > lim + (0.0 if st.name else -0.8) or (not st.name and self.fov > 45):
                    continue
                q = fr.project(st.vec)
                if q is None or q[2] < fr.cos_lim or (self.cfg.show_ground and fr.below_horizon(st.vec)):
                    continue
                r = (0.75 + 0.42 * (6.5 - st.mag)) * 0.62
                self._label(p, st.label(), q[0] + r + 4, q[1] + 3, QColor(190, 208, 230, 215), self._font_small, prio=2)
        # constellation names
        if self.cfg.show_constellation_names and self.fov > 14:
            nightf = _clamp((-self.sun_alt - 4.0) / 12.0, 0.0, 1.0) if self.cfg.show_atmosphere else 1.0
            col = QColor(110, 170, 240, int(190 * nightf))
            for con in (self.cat.constellations.values() if nightf > 0.05 else ()):
                q = fr.project(con.vec)
                if q is None or q[2] < fr.cos_lim or (self.cfg.show_ground and fr.below_horizon(con.vec, 0.03)):
                    continue
                self._label(p, con.name.upper(), q[0], q[1], col, self._font_const, prio=4, center=True)
        # cardinal points
        if self.cfg.show_cardinals and self.cfg.show_ground:
            for az, txt, major in CARDINALS:
                q = fr.project_horizontal(astro.altaz_to_horizon(1.5, az))
                if q is None or not (-20 < q[0] < fr.w + 20 and -20 < q[1] < fr.h + 20):
                    continue
                f = QFont("sans", 12 if major else 9, QFont.Bold if major else QFont.Normal)
                col = QColor(theme.ACCENT) if az == 0 else QColor(240, 215, 160) if major else QColor(180, 190, 205)
                p.setFont(f)
                fm = QFontMetricsF(f)
                p.setPen(QColor(0, 0, 0, 160))
                p.drawText(QPointF(q[0] - fm.horizontalAdvance(txt) / 2 + 1, q[1] + 1), txt)
                p.setPen(col)
                p.drawText(QPointF(q[0] - fm.horizontalAdvance(txt) / 2, q[1]), txt)

    def _paint_selection(self, p: QPainter, fr: Frame) -> None:
        for obj, col, rad in ((self.hover, QColor(255, 255, 255, 120), 11), (self.selection, QColor(theme.ACCENT), 15)):
            if obj is None:
                continue
            q = fr.project(self.current_vec(obj))
            if q is None:
                continue
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, 1.6))
            x, y = q[0], q[1]
            p.drawEllipse(QPointF(x, y), rad, rad)
            if obj is self.selection:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    p.drawLine(QPointF(x + dx * (rad + 2), y + dy * (rad + 2)), QPointF(x + dx * (rad + 8), y + dy * (rad + 8)))

    def _paint_hud(self, p: QPainter, fr: Frame) -> None:
        p.setFont(self._font_small)
        txt = f"Az {self.az:5.1f}°  Alt {self.alt:+5.1f}°  ·  campo {self.fov:.0f}°"
        p.setPen(QColor(255, 255, 255, 130))
        p.drawText(QPointF(12, fr.h - 12), txt)
        if self.track and self.selection is not None:
            p.setPen(QColor(theme.ACCENT))
            p.drawText(QPointF(12, fr.h - 28), f"● segue {self.selection.label}")

    # ------------------------------------------------------------------ picking
    def pick_at(self, x: float, y: float, tol: float = 12.0) -> Optional[Picked]:
        best, best_d = None, 1e9
        for hx, hy, hr, prio, obj in self._hits:
            d = math.hypot(hx - x, hy - y)
            if d <= max(tol, hr):
                score = d + prio * 4.0
                if score < best_d:
                    best, best_d = obj, score
        return best

    def select(self, obj: Optional[Picked]) -> None:
        self.selection = obj
        if obj is None:
            self.track = False
        self.selected.emit(obj)
        self.update()

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._press = (ev.position(), self.az, self.alt)
            self._moved = False
            self._anim = None
            self.setFocus()

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        if self._press is not None and (ev.buttons() & Qt.LeftButton):
            p0, az0, alt0 = self._press
            dx, dy = pos.x() - p0.x(), pos.y() - p0.y()
            if not self._moved and abs(dx) + abs(dy) < 4:
                return
            self._moved = True
            self.setCursor(Qt.ClosedHandCursor)
            self.track = False
            fr = self.frame
            deg_per_px = R2D / fr.s if fr else 0.1
            f = 1.0 / max(0.15, math.cos(alt0 * D2R))
            self.az = (az0 - dx * deg_per_px * min(f, 6.0)) % 360.0
            self.alt = _clamp(alt0 + dy * deg_per_px, -90.0, 90.0)
            self.update()
            self.viewChanged.emit()
            return
        h = self.pick_at(pos.x(), pos.y(), 9.0)
        if (h is None) != (self.hover is None) or (h is not None and self.hover is not None and h.obj is not self.hover.obj):
            self.hover = h
            self.hovered.emit(h)
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self._press is not None:
            if not self._moved:
                self.select(self.pick_at(ev.position().x(), ev.position().y()))
            self._press = None
            self.setCursor(Qt.CrossCursor)

    def mouseDoubleClickEvent(self, ev) -> None:
        h = self.pick_at(ev.position().x(), ev.position().y())
        if h is not None:
            self.select(h)
            self.goto(h, fov=min(self.fov, 40.0), track=True)
        elif self.frame is not None:
            alt, az = self.frame.altaz(self.frame.unproject(ev.position().x(), ev.position().y()))
            self.animate_to(az, alt)

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        self.zoom(0.85 ** steps)

    def zoom(self, factor: float) -> None:
        self.fov = _clamp(self.fov * factor, FOV_MIN, FOV_MAX)
        self.update()
        self.viewChanged.emit()

    def keyPressEvent(self, ev) -> None:
        step = max(1.0, self.fov / 12.0)
        k = ev.key()
        if k == Qt.Key_Left:
            self.track = False; self.set_view(self.az - step, self.alt)
        elif k == Qt.Key_Right:
            self.track = False; self.set_view(self.az + step, self.alt)
        elif k == Qt.Key_Up:
            self.track = False; self.set_view(self.az, self.alt + step)
        elif k == Qt.Key_Down:
            self.track = False; self.set_view(self.az, self.alt - step)
        elif k in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_PageUp):
            self.zoom(0.8)
        elif k in (Qt.Key_Minus, Qt.Key_PageDown):
            self.zoom(1.25)
        else:
            super().keyPressEvent(ev)
