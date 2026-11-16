"""Main window: sky view, time controls, object info and layer toggles."""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import QDateTime, QElapsedTimer, QSettings, QStringListModel, Qt, QTimer, QTimeZone
from PySide6.QtGui import QAction, QKeySequence, QTextDocument
from PySide6.QtWidgets import (QCheckBox, QCompleter, QDateTimeEdit, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QPushButton, QScrollArea, QSizePolicy, QToolBar, QToolButton, QVBoxLayout, QWidget)

from . import astro, events, theme
from .catalog import Catalog, GREEK
from .config import APP, ORG, Config
from .places import Place, db as places_db, format_custom, parse_custom, preset_places, tzinfo, valid_tz
from .settings_dialog import LocationDialog, SettingsDialog
from .skyview import Picked, SkyView
from .widgets import Card

APP_NAME = "StarDeck"
# time-flow ladder in simulated seconds per real second
RATES = [-86400, -3600, -60, 0, 1, 60, 3600, 86400]
EVENT_BODIES = ["Sole", "Luna"] + astro.PLANETS
LAYERS = [("show_constellation_lines", "Linee delle costellazioni", "C"), ("show_constellation_names", "Nomi delle costellazioni", "V"),
          ("show_star_names", "Nomi delle stelle", "S"), ("show_planets", "Pianeti", "P"), ("show_dso", "Oggetti del profondo cielo", "D"),
          ("show_milky_way", "Via Lattea", "M"), ("show_ecliptic", "Eclittica", "L"), ("show_grid_altaz", "Griglia altazimutale", "A"),
          ("show_grid_eq", "Griglia equatoriale", "E"), ("show_ground", "Orizzonte e punti cardinali", "G"),
          ("show_atmosphere", "Atmosfera (crepuscolo e giorno)", "H")]


def rate_text(r: int) -> str:
    if r == 0:
        return "in pausa"
    if r == 1:
        return "tempo reale"
    sign = "−" if r < 0 else ""
    a = abs(r)
    return f"{sign}{'1 min/s' if a == 60 else '1 h/s' if a == 3600 else '1 giorno/s'}"


class MainWindow(QMainWindow):
    def __init__(self, qs: Optional[QSettings] = None, catalog: Optional[Catalog] = None, jd: Optional[float] = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.qs = qs or QSettings(ORG, APP)
        self.cfg = Config().load(self.qs)
        self.ephemeral = False
        if not tzinfo(self.cfg.tz):
            self.cfg.tz = places_db().guess_tz(self.cfg.lat, self.cfg.lon, self.cfg.place)
        self.cat = catalog or Catalog()
        self.rate = 1 if jd is None else 0
        self._rate_before_pause = 1
        self._clock = QElapsedTimer()
        self._last_shown = None
        self._build_ui()
        self.view.set_time(jd if jd is not None else astro.jd_now())
        self._update_time_widgets(force=True)
        self._update_rate_ui()
        self._clock.start()
        self.timer = QTimer(self, interval=40)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.view.set_view(180.0, 40.0, 100.0)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        tb = QToolBar("Principale")
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)
        title = QLabel(f"<span style='font-size:17px;font-weight:800;color:#f1f5f9'>Star</span>"
                       f"<span style='font-size:17px;font-weight:800;color:{theme.ACCENT}'>Deck</span>")
        title.setContentsMargins(4, 0, 14, 0)
        tb.addWidget(title)
        self.place_edit = QLineEdit()
        self.place_edit.setMinimumWidth(250)
        self.place_edit.setPlaceholderText("Luogo: scrivi una città…")
        self.place_edit.setToolTip("Luogo di osservazione: scrivi il nome di una città (34.000 in archivio), Invio per scegliere")
        self.place_edit.addAction(theme.icon("pin", theme.MUTED), QLineEdit.LeadingPosition)
        self.place_edit.textEdited.connect(self._place_typed)
        self.place_edit.returnPressed.connect(self._place_enter)
        self.place_model = QStringListModel(self)
        self.place_completer = QCompleter(self.place_model, self)
        self.place_completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)   # the list is already filtered by PlaceDB
        self.place_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.place_completer.setMaxVisibleItems(12)
        self.place_completer.activated[str].connect(self._place_picked)
        self.place_edit.setCompleter(self.place_completer)
        self._place_results: dict[str, Place] = {}
        tb.addWidget(self.place_edit)
        self.place_btn = QToolButton()
        self.place_btn.setText("▾")
        self.place_btn.setToolTip("Luoghi salvati e predefiniti")
        self.place_btn.setPopupMode(QToolButton.InstantPopup)
        self.place_menu = QMenu(self)
        self.place_btn.setMenu(self.place_menu)
        tb.addWidget(self.place_btn)
        self.place_label = QLabel()
        self.place_label.setObjectName("kv")
        self.place_label.setContentsMargins(10, 0, 0, 0)
        tb.addWidget(self.place_label)
        sp = QWidget(); sp.setFixedWidth(16); sp.setObjectName("spacer")
        tb.addWidget(sp)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca: Sirius, M31, Orione…")
        self.search.setFixedWidth(260)
        self.search.setClearButtonEnabled(True)
        self.search.addAction(theme.icon("search", theme.MUTED), QLineEdit.LeadingPosition)
        self.search.returnPressed.connect(self._do_search)
        tb.addWidget(self.search)
        self._completer_model_names()
        spacer = QWidget(); spacer.setObjectName("spacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.act_settings = QAction(theme.icon("gear"), "Impostazioni", self)
        self.act_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.act_settings.triggered.connect(self.open_settings)
        tb.addAction(self.act_settings)

        self.addToolBarBreak()
        tt = QToolBar("Tempo")
        tt.setMovable(False)
        tt.setFloatable(False)
        self.addToolBar(tt)
        self.btn_back = self._tbtn(theme.icon("back"), "Rallenta / indietro nel tempo  (J)", self.slower, "J")
        self.btn_play = self._tbtn(theme.icon("pause"), "Pausa / tempo reale  (Spazio)", self.toggle_play, "Space")
        self.btn_fwd = self._tbtn(theme.icon("fwd"), "Accelera il tempo  (L)", self.faster, "K")
        for b in (self.btn_back, self.btn_play, self.btn_fwd):
            tt.addWidget(b)
        self.rate_label = QLabel()
        self.rate_label.setObjectName("kv")
        self.rate_label.setMinimumWidth(110)
        self.rate_label.setContentsMargins(8, 0, 8, 0)
        tt.addWidget(self.rate_label)
        self.dt_edit = QDateTimeEdit()
        self.dt_edit.setDisplayFormat("dd/MM/yyyy  HH:mm:ss")
        self.dt_edit.setCalendarPopup(True)
        self.dt_edit.setTimeZone(QTimeZone.UTC)
        self.dt_edit.setMinimumWidth(190)
        self.dt_edit.dateTimeChanged.connect(self._dt_edited)
        tt.addWidget(self.dt_edit)
        self.btn_now = self._tbtn(theme.icon("now"), "Torna all'ora attuale  (N)", self.go_now, "N")
        tt.addWidget(self.btn_now)
        for label, days in (("−1 g", -1), ("+1 g", 1), ("−1 h", -1 / 24), ("+1 h", 1 / 24)):
            b = QPushButton(label)
            b.setToolTip("Sposta la data/ora")
            b.clicked.connect(lambda _c=False, d=days: self.shift_time(d))
            tt.addWidget(b)
        spacer2 = QWidget(); spacer2.setObjectName("spacer")
        spacer2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tt.addWidget(spacer2)
        self.utc_label = QLabel()
        self.utc_label.setObjectName("kv")
        tt.addWidget(self.utc_label)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(10)
        self.view = SkyView(self.cat, self.cfg)
        self.view.selected.connect(self._selected)
        self.view.hovered.connect(self._hovered)
        root.addWidget(self.view, 1)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)
        self.info_card = Card("Oggetto")
        self.info = QLabel("Clicca un astro per i dettagli.\nDoppio clic: centra e segui.")
        self.info.setObjectName("kv")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._fit_label(self.info)
        self.info_card.body.addWidget(self.info)
        row = QHBoxLayout()
        self.btn_center = QPushButton("Centra")
        self.btn_center.clicked.connect(lambda: self._center(False))
        self.btn_follow = QPushButton("Segui")
        self.btn_follow.setCheckable(True)
        self.btn_follow.clicked.connect(self._follow)
        row.addWidget(self.btn_center); row.addWidget(self.btn_follow)
        self.info_card.body.addLayout(row)
        self.btn_center.setEnabled(False); self.btn_follow.setEnabled(False)
        sl.addWidget(self.info_card)
        self.sky_card = Card("Cielo adesso")
        self.sky_sun = QLabel()
        self.sky_moon = QLabel()
        for lab in (self.sky_sun, self.sky_moon):
            lab.setObjectName("kv")
            lab.setTextFormat(Qt.PlainText)
            self.sky_card.body.addWidget(lab)
        sl.addWidget(self.sky_card)
        self.ev_card = Card("Sorge e tramonta")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        self.ev_grid = grid
        for c, h in enumerate(("", "Sorge", "Culmine", "Tramonta")):
            lab = QLabel(h)
            lab.setObjectName("muted")
            grid.addWidget(lab, 0, c)
        self.ev_cells: dict[str, list] = {}
        for r, name in enumerate(EVENT_BODIES, start=1):
            row = [QLabel(name)] + [QLabel("—") for _ in range(3)]
            for c, lab in enumerate(row):
                lab.setObjectName("kv")
                lab.setTextFormat(Qt.PlainText)
                grid.addWidget(lab, r, c)
            self.ev_cells[name] = row
        self.ev_card.body.addLayout(grid)
        self.night_label = QLabel()
        self.night_label.setObjectName("muted")
        self.night_label.setTextFormat(Qt.PlainText)
        self.ev_card.body.addWidget(self.night_label)
        sl.addWidget(self.ev_card)
        layers = Card("Visualizza")
        self.layer_boxes = {}
        for key, text, sc in LAYERS:
            cb = QCheckBox(f"{text}   ({sc})")
            cb.setChecked(getattr(self.cfg, key))
            cb.toggled.connect(lambda v, k=key: self._layer(k, v))
            layers.body.addWidget(cb)
            self.layer_boxes[key] = cb
            act = QAction(self)
            act.setShortcut(QKeySequence(sc))
            act.triggered.connect(cb.toggle)
            self.addAction(act)
        sl.addWidget(layers)
        sl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(330)
        root.addWidget(scroll)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.statusBar().addWidget(self.status, 1)
        self._update_place_label()

    def _tbtn(self, ic, tip, slot, key=None):
        b = QToolButton()
        b.setIcon(ic)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        if key:
            b.setShortcut(QKeySequence(key))
        return b

    def _completer_model_names(self) -> None:
        names = [s.name for s in self.cat.named if s.name] + [c.name for c in self.cat.constellations.values()] + \
                [d.label() for d in self.cat.dsos if d.desig.startswith("M ")] + ["Sole", "Luna"] + astro.PLANETS
        comp = QCompleter(sorted(set(names)), self.search)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.activated.connect(lambda _t: self._do_search())
        self.search.setCompleter(comp)

    # ------------------------------------------------------------------ place
    def _saved_places(self) -> list:
        return parse_custom(self.cfg.custom_places)

    def _update_place_label(self) -> None:
        """Shows the current place and rebuilds the menu of saved / preset places."""
        self.place_edit.setText(self.cfg.place)
        self.place_edit.setCursorPosition(0)
        self.place_edit.clearFocus()
        ns = "N" if self.cfg.lat >= 0 else "S"
        ew = "E" if self.cfg.lon >= 0 else "O"
        self.place_label.setText(f"{abs(self.cfg.lat):.2f}°{ns}  {abs(self.cfg.lon):.2f}°{ew}")
        m = self.place_menu
        m.clear()
        saved = self._saved_places()
        for p in saved:
            m.addAction("★ " + p.name, lambda _c=False, p=p: self._apply_place(p))
        if saved:
            m.addSeparator()
        for p in preset_places():
            m.addAction(p.name, lambda _c=False, p=p: self._apply_place(p))
        m.addSeparator()
        m.addAction("Altro luogo (coordinate)…", self._other_place)

    def _place_typed(self, text: str) -> None:
        res = places_db().search(text, self._saved_places() + preset_places())
        labels, seen = [], {}
        for p in res:
            seen[p.label] = seen.get(p.label, 0) + 1
        self._place_results = {}
        for p in res:
            lab = p.label if seen[p.label] == 1 else f"{p.label} ({abs(p.lat):.1f}°{'N' if p.lat >= 0 else 'S'} {abs(p.lon):.1f}°{'E' if p.lon >= 0 else 'O'})"
            if p.mine:
                lab = "★ " + lab
            labels.append(lab)
            self._place_results[lab] = p
        self.place_model.setStringList(labels)
        if labels:
            self.place_completer.complete()

    def _place_picked(self, label: str) -> None:
        p = self._place_results.get(label)
        if p is not None:
            self._apply_place(p)

    def _place_enter(self) -> None:
        popup = self.place_completer.popup()
        if popup is not None and popup.isVisible() and popup.currentIndex().isValid():
            return                                       # the completer handles it
        res = places_db().search(self.place_edit.text(), self._saved_places() + preset_places(), 1)
        if res:
            self._apply_place(res[0])
        else:
            self.status.setText(f"Nessun luogo trovato per «{self.place_edit.text()}» — usa ▾ → «Altro luogo»")

    def _apply_place(self, p: Place) -> None:
        tz = p.tz if p.tz and valid_tz(p.tz) else places_db().guess_tz(p.lat, p.lon, p.name)
        self.set_place(p.name, p.lat, p.lon, tz)

    def _other_place(self) -> None:
        dlg = LocationDialog(self.cfg.place, self.cfg.lat, self.cfg.lon, self.cfg.tz, self)
        if dlg.exec():
            name, lat, lon, tz = dlg.result_place()
            if dlg.save.isChecked():
                mine = [p for p in self._saved_places() if p.name != name]
                self.cfg.custom_places = format_custom([Place(name, lat, lon, tz, mine=True)] + mine)
            self.set_place(name, lat, lon, tz)
        else:
            self._update_place_label()

    def set_place(self, name: str, lat: float, lon: float, tz: str = "", persist: bool = True) -> None:
        """Changes the observing place. The instant stays the same; the clock is shown in the new place's time zone."""
        self.cfg.place, self.cfg.lat, self.cfg.lon = name, lat, lon
        self.cfg.tz = tz if tz and valid_tz(tz) else places_db().guess_tz(lat, lon, name)
        self.ephemeral = not persist                   # command-line place: do not overwrite the saved settings on exit
        if persist:
            self.cfg.save(self.qs)
        self.view.set_config(self.cfg)
        self._update_place_label()
        self._update_time_widgets(force=True)
        self._update_events(force=True)
        self.status.setText(f"Luogo: {name}  ·  fuso {self.cfg.tz}")

    # ------------------------------------------------------------------ time
    def _tick(self) -> None:
        dt_ms = self._clock.restart()
        if self.rate != 0:
            self.view.jd += self.rate * dt_ms / 1000.0 / 86400.0
            self.view.update()
            self._update_time_widgets()
        else:
            self._update_time_widgets()
        self._update_sky_card()

    def _tz(self):
        return tzinfo(self.cfg.tz)                    # None = system local time

    def _local_dt(self) -> datetime:
        tz = self._tz()
        d = astro.datetime_from_jd(self.view.jd)
        return d.astimezone(tz) if tz is not None else d.astimezone()

    def _update_time_widgets(self, force: bool = False) -> None:
        d = self._local_dt()
        key = round(d.timestamp())
        if key == self._last_shown and not force:
            return
        self._last_shown = key
        self.dt_edit.blockSignals(True)
        # the edit shows the place's wall-clock time; it is stored as if it were UTC so that no system DST rule can alter it
        wall = calendar.timegm(d.replace(tzinfo=None).timetuple())
        self.dt_edit.setDateTime(QDateTime.fromSecsSinceEpoch(wall, QTimeZone.UTC))
        self.dt_edit.blockSignals(False)
        u = astro.datetime_from_jd(self.view.jd)
        off = d.utcoffset().total_seconds() / 3600.0 if d.utcoffset() is not None else 0.0
        self.utc_label.setText(f"{self.cfg.tz or 'ora di sistema'} {d:%Z} (UTC{off:+g})  ·  UTC {u:%H:%M:%S}  ·  JD {self.view.jd:.4f}")

    def _dt_edited(self, qdt: QDateTime) -> None:
        wall = datetime.fromtimestamp(qdt.toSecsSinceEpoch(), timezone.utc).replace(tzinfo=None)
        tz = self._tz()
        self.view.set_time(astro.jd_from_datetime(wall.replace(tzinfo=tz) if tz is not None else wall))   # naive = system local time
        self._last_shown = None
        if self.rate == 1:
            self.rate = 0
            self._update_rate_ui()

    def go_now(self) -> None:
        self.view.set_time(astro.jd_now())
        self.rate = 1
        self._update_rate_ui()
        self._update_time_widgets(force=True)

    def shift_time(self, days: float) -> None:
        self.view.set_time(self.view.jd + days)
        if self.rate == 1:
            self.rate = 0
            self._update_rate_ui()
        self._update_time_widgets(force=True)

    def toggle_play(self) -> None:
        if self.rate == 0:
            self.rate = self._rate_before_pause or 1
        else:
            self._rate_before_pause = self.rate
            self.rate = 0
        self._update_rate_ui()

    def slower(self) -> None:
        i = RATES.index(self.rate) if self.rate in RATES else RATES.index(1)
        self.rate = RATES[max(0, i - 1)]
        self._update_rate_ui()

    def faster(self) -> None:
        i = RATES.index(self.rate) if self.rate in RATES else RATES.index(1)
        self.rate = RATES[min(len(RATES) - 1, i + 1)]
        self._update_rate_ui()

    def _update_rate_ui(self) -> None:
        self.rate_label.setText(rate_text(self.rate))
        self.btn_play.setIcon(theme.icon("play" if self.rate == 0 else "pause"))
        self._clock.restart()

    # ------------------------------------------------------------------ objects
    def _selected(self, obj: Optional[Picked]) -> None:
        self.btn_center.setEnabled(obj is not None)
        self.btn_follow.setEnabled(obj is not None)
        self.btn_follow.setChecked(self.view.track)
        self.info.setText(self._describe(obj) if obj else "Clicca un astro per i dettagli.\nDoppio clic: centra e segui.")
        self._fit_label(self.info)

    @staticmethod
    def _fit_label(lab: QLabel) -> None:
        """Rich-text QLabels with word wrap under-report their height inside cards: size them from a QTextDocument."""
        lab.ensurePolished()
        doc = QTextDocument()
        doc.setDefaultFont(lab.font())
        doc.setHtml(lab.text().replace("\n", "<br>"))
        doc.setTextWidth(max(lab.width(), 250))
        lab.setFixedHeight(int(doc.size().height()) + 14)

    def _hovered(self, obj: Optional[Picked]) -> None:
        if obj is None:
            self.status.setText("")
            return
        alt, az = self.view.altaz_of(obj)
        mag = self._mag_text(obj)
        self.status.setText(f"{obj.label}{'  ·  ' + mag if mag else ''}  ·  Alt {alt:+.1f}°  Az {az:.1f}°")

    def _center(self, track: bool) -> None:
        if self.view.selection is not None:
            self.view.goto(self.view.selection, fov=min(self.view.fov, 45.0), track=track)
            self.btn_follow.setChecked(track)

    def _follow(self, on: bool) -> None:
        if self.view.selection is None:
            return
        if on:
            self.view.goto(self.view.selection, fov=min(self.view.fov, 45.0), track=True)
        else:
            self.view.track = False
            self.view.update()

    @staticmethod
    def _mag_text(o: Picked) -> str:
        m = o.obj.mag
        return "" if m is None else f"mag {m:+.1f}" if o.kind != "dso" else f"mag {m:.1f}"

    def _describe(self, o: Picked) -> str:
        alt, az = self.view.altaz_of(o)
        v = self.view.current_vec(o)
        ra, dec = astro.vec_to_radec(v)
        rows = []
        ob = o.obj
        title = o.label
        sub = ""
        if o.kind == "star":
            sub = f"Stella · {ob.con}" if ob.con else "Stella"
            if ob.name and ob.bayer:
                sub += f" · {GREEK.get(ob.bayer, ob.bayer)} {ob.con}"
            rows += [("Magnitudine", f"{ob.mag:+.2f}"), ("Indice B−V", f"{ob.bv:+.2f}")]
        elif o.kind == "dso":
            sub = ob.type_name()
            title = f"{ob.label()}" + (f" — {ob.name}" if ob.name else "")
            rows += [("Magnitudine", "—" if ob.mag is None else f"{ob.mag:.1f}"), ("Dimensione", f"{ob.size:.0f}′" if ob.size else "—")]
        elif o.kind == "planet":
            sub = "Pianeta"
            rows += [("Magnitudine", f"{ob.mag:+.1f}"), ("Distanza", f"{ob.dist_au:.3f} UA"), ("Fase", f"{ob.phase * 100:.0f}%"),
                     ("Elongazione", f"{ob.elong:.0f}°")]
        elif o.kind == "sun":
            sub = "Stella · la nostra"
            rows += [("Distanza", f"{ob.dist_au:.4f} UA"), ("Diametro", f"{ob.angsize * 60:.1f}′")]
        elif o.kind == "moon":
            sub = astro.moon_phase_name(ob.phase, self.view.moon_waxing)
            rows += [("Illuminazione", f"{ob.phase * 100:.0f}%"), ("Distanza", f"{ob.dist_au * astro.AU_KM:,.0f} km".replace(",", ".")),
                     ("Elongazione", f"{ob.elong:.0f}°")]
        rows += [("Asc. retta", astro.fmt_ra(ra)), ("Declinazione", astro.fmt_dec(dec)),
                 ("Altezza", f"{alt:+.1f}°" + ("" if alt > 0 else "  (sotto l'orizzonte)")), ("Azimut", f"{az:.1f}°  {self._compass(az)}")]
        ev = self._selection_events(o)
        tz = self._tz()
        if ev.state == "always_up":
            rows.append(("Visibilità", "sempre sopra l'orizzonte"))
        elif ev.state == "never_up":
            rows.append(("Visibilità", "non sorge oggi"))
        else:
            rows += [("Sorge", events.fmt_time(ev.rise, tz)), ("Culmine", events.fmt_time(ev.transit, tz) +
                     (f"  ({ev.transit_alt:.0f}°)" if ev.transit_alt is not None and ev.transit_alt > events.H0_STAR else "")),
                     ("Tramonta", events.fmt_time(ev.set, tz))]
        tbl = "".join(f"<tr><td style='color:{theme.MUTED};padding-right:10px'>{k}</td><td>{v}</td></tr>" for k, v in rows)
        return (f"<div style='font-size:16px;font-weight:800;color:#f1f5f9'>{title}</div>"
                f"<div style='color:{theme.ACCENT};margin-bottom:6px'>{sub}</div><table>{tbl}</table>")

    @staticmethod
    def _compass(az: float) -> str:
        return ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"][int((az + 11.25) // 22.5) % 16]

    def _update_sky_card(self) -> None:
        v = self.view
        if not v.bodies:
            v._update_bodies()
        moon = v.bodies["Luna"]
        self.sky_sun.setText(f"Sole: {v.sun_alt:+.1f}° · {astro.twilight_state(v.sun_alt)}")
        self.sky_moon.setText(f"Luna: {astro.moon_phase_name(moon.phase, v.moon_waxing)} {moon.phase * 100:.0f}%")
        self._update_events()

    # ------------------------------------------------------------------ rise / transit / set
    def _event_args(self) -> tuple:
        return self.cfg.lat, self.cfg.lon, self._tz()

    def _update_events(self, force: bool = False) -> None:
        """Recomputes the rise/transit/set table when the local day, the place or the time zone changes (not every tick)."""
        key = (self._local_dt().date(), self.cfg.lat, self.cfg.lon, self.cfg.tz)
        if key == getattr(self, "_ev_key", None) and not force:
            return
        self._ev_key = key
        lat, lon, tz = self._event_args()
        jd = self.view.jd
        self.ev_card.title_label.setText(f"SORGE E TRAMONTA · {key[0]:%d/%m}")
        for name in EVENT_BODIES:
            ev = events.body_events(name, jd, lat, lon, tz)
            cells = self.ev_cells[name]
            self.ev_grid.removeWidget(cells[1])
            self.ev_grid.removeWidget(cells[2])
            self.ev_grid.removeWidget(cells[3])
            row = EVENT_BODIES.index(name) + 1
            if ev.state != "normal":
                cells[1].setText("sempre sopra l'orizzonte" if ev.state == "always_up" else "non sorge")
                self.ev_grid.addWidget(cells[1], row, 1, 1, 3)
                cells[2].hide(); cells[3].hide(); cells[1].show()
            else:
                self.ev_grid.addWidget(cells[1], row, 1); self.ev_grid.addWidget(cells[2], row, 2); self.ev_grid.addWidget(cells[3], row, 3)
                up = ev.transit_alt is not None and ev.transit_alt > events.H0_STAR
                cells[1].setText(events.fmt_time(ev.rise, tz))
                cells[2].setText(events.fmt_time(ev.transit, tz) if up else "—")
                cells[3].setText(events.fmt_time(ev.set, tz))
                for c in cells[1:]:
                    c.show()
                cells[2].setToolTip(f"altezza massima {ev.transit_alt:.0f}°" if up else "")
        n = events.night_span(jd, lat, lon, tz)
        if n.state == "always_up":
            self.night_label.setText("Nessuna notte astronomica")
        elif n.state == "never_up":
            self.night_label.setText("Notte astronomica tutto il giorno")
        else:
            self.night_label.setText(f"Notte astronomica: dalle {events.fmt_time(n.set, tz)} alle {events.fmt_time(n.rise, tz)}")
        if self.view.selection is not None:
            self.info.setText(self._describe(self.view.selection))
            self._fit_label(self.info)

    def _selection_events(self, o: Picked):
        lat, lon, tz = self._event_args()
        if o.kind in ("sun", "moon", "planet"):
            return events.body_events(o.obj.name, self.view.jd, lat, lon, tz)
        return events.fixed_events(o.vec, self.view.jd, lat, lon, tz)

    def _do_search(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        t = text.lower()
        for n in ["Sole"] + ["Luna"] + astro.PLANETS:
            if n.lower() == t or (len(t) >= 3 and n.lower().startswith(t)):
                b = self.view.bodies[n]
                kind = "sun" if n == "Sole" else "moon" if n == "Luna" else "planet"
                self._pick(Picked(kind, b, self.view.body_vecs[n]), 30.0)
                return
        res = self.cat.find(text, 1)
        if not res:
            self.status.setText(f"Nessun risultato per «{text}»")
            return
        kind, _label, obj = res[0]
        if kind == "const":
            self.view.select(None)
            alt, az = self.view.frame.altaz(obj.vec)
            self.view.track = False
            self.view.animate_to(az, alt, 55.0)
        else:
            self._pick(Picked(kind, obj, obj.vec), 25.0 if kind == "star" else 15.0)

    def _pick(self, p: Picked, fov: float) -> None:
        self.view.select(p)
        self.view.goto(p, fov=fov, track=False)
        self.btn_follow.setChecked(False)

    # ------------------------------------------------------------------ settings
    def _layer(self, key: str, on: bool) -> None:
        setattr(self.cfg, key, on)
        self.view.set_config(self.cfg)
        self.cfg.save(self.qs)

    def open_settings(self) -> None:
        d = SettingsDialog(self.cfg, self)
        if d.exec():
            self.cfg.save(self.qs)
            self.view.set_config(self.cfg)
            self._update_place_label()
            self._update_time_widgets(force=True)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._fit_label(self.info)
        self._update_sky_card()

    def closeEvent(self, ev) -> None:
        if not self.ephemeral:
            self.cfg.save(self.qs)
        super().closeEvent(ev)
