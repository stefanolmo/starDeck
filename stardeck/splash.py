"""Animated splash screen: a rotating dome of stars, Orion drawn line by line, a shooting star, title, credits and version."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from . import theme

W, H = 780, 440
CREDITS = "Stefano Ciurleo & Claude Code - 2026"
# Orion, as (x, y) on the dome in units of its radius, centred on the dome; stars and the lines joining them
ORION = {"Betelgeuse": (-0.30, -0.52), "Bellatrix": (0.32, -0.46), "Meissa": (0.02, -0.70), "Alnitak": (-0.10, 0.02), "Alnilam": (0.04, -0.02),
         "Mintaka": (0.18, -0.06), "Saiph": (-0.26, 0.52), "Rigel": (0.34, 0.46), "Sword": (0.04, 0.22)}
ORION_LINES = [("Meissa", "Betelgeuse"), ("Meissa", "Bellatrix"), ("Betelgeuse", "Alnitak"), ("Bellatrix", "Mintaka"), ("Alnitak", "Alnilam"),
               ("Alnilam", "Mintaka"), ("Alnitak", "Saiph"), ("Mintaka", "Rigel"), ("Alnilam", "Sword")]
ORION_COL = {"Betelgeuse": "#ff9d6b", "Rigel": "#9ec5ff", "Bellatrix": "#b6d2ff"}


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class SplashScreen(QWidget):
    finished = Signal()

    def __init__(self, version: str, duration_ms: int = 3000, parent=None):
        super().__init__(parent)
        self.version = version
        self.duration = duration_ms
        self.t = 0.0
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self._clock = QElapsedTimer()
        self._tick = QTimer(self, interval=16)
        self._tick.timeout.connect(self._advance)
        self.cx, self.cy, self.R = W * 0.72, H * 0.50, 150.0
        rnd = random.Random(7)
        self.stars = []
        for _ in range(260):
            a, r = rnd.uniform(0, 2 * math.pi), math.sqrt(rnd.uniform(0, 1))
            self.stars.append((a, r, rnd.uniform(0.5, 2.0), rnd.uniform(0.3, 1.0), rnd.uniform(0, 6.28)))

    def start(self) -> None:
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.center().x() - W // 2, g.center().y() - H // 2)
        self.show()
        self.raise_()
        self._clock.start()
        self._tick.start()

    def _advance(self) -> None:
        self.t = float(self._clock.elapsed())
        if self.t >= self.duration:
            self._tick.stop()
            self.close()
            self.finished.emit()
            return
        self.update()

    def set_time(self, ms: float) -> None:
        """Freeze the animation at `ms` (used for screenshots and tests)."""
        self.t = ms
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = self.t / max(self.duration, 1)
        fade_in = _ease(self.t / 350.0)
        fade_out = 1.0 - _ease((self.t - (self.duration - 300)) / 300.0)
        p.setOpacity(max(0.0, min(fade_in, fade_out)))
        self._paint_card(p)
        self._paint_dome(p)
        self._paint_text(p)
        self._paint_progress(p, k)
        p.end()

    def _paint_card(self, p: QPainter) -> None:
        rect = QRectF(8, 8, W - 16, H - 16)
        path = QPainterPath()
        path.addRoundedRect(rect, 22, 22)
        glow = QRadialGradient(QPointF(self.cx, self.cy), W * 0.5)
        glow.setColorAt(0, QColor(45, 212, 191, 40))
        glow.setColorAt(1, QColor(45, 212, 191, 0))
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor("#141b24"))
        g.setColorAt(1, QColor("#0a0e13"))
        p.fillPath(path, g)
        p.fillPath(path, QBrush(glow))
        p.setPen(QPen(QColor(theme.BORDER), 1.5))
        p.drawPath(path)
        p.setClipPath(path)

    def _paint_dome(self, p: QPainter) -> None:
        c = QPointF(self.cx, self.cy)
        R = self.R
        dome = QPainterPath()
        dome.addEllipse(c, R, R)
        sky = QRadialGradient(c, R)
        sky.setColorAt(0, QColor("#0a1428"))
        sky.setColorAt(0.8, QColor("#0e1c36"))
        sky.setColorAt(1, QColor("#1a3050"))
        p.fillPath(dome, QBrush(sky))
        p.save()
        p.setClipPath(dome)
        spin = self.t / 1000.0 * 0.12                           # slow rotation of the whole sky
        p.setPen(Qt.NoPen)
        for a, r, size, bright, ph in self.stars:
            aa = a + spin
            tw = 0.75 + 0.25 * math.sin(self.t / 260.0 + ph)
            col = QColor(220, 232, 255, int(255 * bright * tw))
            p.setBrush(col)
            p.drawEllipse(QPointF(c.x() + R * r * math.cos(aa), c.y() + R * r * math.sin(aa)), size * 0.7, size * 0.7)
        # Orion, drawn progressively and (rotated with the sky)
        prog = _ease((self.t - 500.0) / 1700.0)
        cs, sn = math.cos(spin), math.sin(spin)

        def pt(name):
            x, y = ORION[name]
            return QPointF(c.x() + R * 0.78 * (x * cs - y * sn), c.y() + R * 0.78 * (x * sn + y * cs))
        n = len(ORION_LINES)
        p.setBrush(Qt.NoBrush)
        for i, (a, b) in enumerate(ORION_LINES):
            f = _clamp01(prog * n - i)
            if f <= 0:
                continue
            pa, pb = pt(a), pt(b)
            p.setPen(QPen(QColor(45, 212, 191, 190), 1.6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pa, QPointF(pa.x() + (pb.x() - pa.x()) * f, pa.y() + (pb.y() - pa.y()) * f))
        for name in ORION:
            q = pt(name)
            col = QColor(ORION_COL.get(name, "#f1f5f9"))
            big = name in ORION_COL
            g = QRadialGradient(q, 16 if big else 9)
            hc = QColor(col); hc.setAlpha(150)
            g.setColorAt(0, hc)
            hc.setAlpha(0)
            g.setColorAt(1, hc)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(q, 16 if big else 9, 16 if big else 9)
            p.setBrush(col)
            p.drawEllipse(q, 3.6 if big else 2.4, 3.6 if big else 2.4)
        # shooting star
        st = (self.t - 1500.0) / 700.0
        if 0 <= st <= 1:
            x0, y0 = c.x() + R * 0.9, c.y() - R * 0.55
            x1, y1 = c.x() - R * 0.2, c.y() + R * 0.35
            hx, hy = x0 + (x1 - x0) * st, y0 + (y1 - y0) * st
            tail = QLinearGradient(hx, hy, hx - (x1 - x0) * 0.22, hy - (y1 - y0) * 0.22)
            tail.setColorAt(0, QColor(255, 255, 255, 230))
            tail.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(QPen(QBrush(tail), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(hx, hy), QPointF(hx - (x1 - x0) * 0.22, hy - (y1 - y0) * 0.22))
        p.restore()
        # horizon ring
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(45, 212, 191, 150), 2.0))
        p.drawEllipse(c, R, R)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawEllipse(c, R + 9, R + 9)
        p.setFont(QFont("sans", 9, QFont.Bold))
        p.setPen(QColor(theme.ACCENT))
        for txt, dx, dy in (("N", 0, -R - 16), ("S", 0, R + 24), ("E", -R - 18, 4), ("O", R + 12, 4)):
            p.drawText(QPointF(c.x() + dx - 4, c.y() + dy), txt)

    def _paint_text(self, p: QPainter) -> None:
        x = 58
        f = QFont("sans", 46, QFont.Black)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.setPen(QColor("#f1f5f9"))
        p.drawText(QPointF(x, H * 0.47), "Star")
        w = p.fontMetrics().horizontalAdvance("Star ")
        p.setPen(QColor(theme.ACCENT))
        p.drawText(QPointF(x + w - 4, H * 0.47), "Deck")
        p.setPen(Qt.NoPen)
        g = QLinearGradient(x, 0, x + 230, 0)
        g.setColorAt(0, QColor(theme.ACCENT))
        g.setColorAt(1, QColor(45, 212, 191, 0))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(x, H * 0.47 + 16, 230, 3), 1.5, 1.5)
        p.setFont(QFont("sans", 11))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QPointF(x + 2, H * 0.47 + 50), CREDITS)
        p.setFont(QFont("sans", 10, QFont.DemiBold))
        p.setPen(QColor(theme.ACCENT))
        p.drawText(QPointF(x + 2, H * 0.47 + 76), f"Version {self.version}")
        p.setFont(QFont("sans", 8))
        p.setPen(QColor(255, 255, 255, 70))
        p.drawText(QPointF(x + 2, H - 38), "Planetario virtuale  ·  stelle  ·  pianeti  ·  costellazioni")

    def _paint_progress(self, p: QPainter, k: float) -> None:
        x0, x1, y = 58.0, W - 58.0, H - 24.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(x0, y, x1 - x0, 3), 1.5, 1.5)
        g = QLinearGradient(x0, 0, x1, 0)
        g.setColorAt(0, QColor(theme.ACCENT))
        g.setColorAt(1, QColor("#38bdf8"))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(x0, y, (x1 - x0) * min(k, 1.0), 3), 1.5, 1.5)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x
