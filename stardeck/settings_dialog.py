"""Settings dialog: observing location and display options."""
from __future__ import annotations

import zoneinfo

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSlider, QVBoxLayout)

from .config import Config
from .places import PLACES, db, valid_tz


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(440)
        self.cfg = cfg
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.place = QComboBox()
        for name, lat, lon in PLACES:
            self.place.addItem(name, (lat, lon))
        self.place.addItem("Personalizzato", None)
        self.place.currentIndexChanged.connect(self._place_changed)
        form.addRow("Luogo", self.place)
        self.name = QLineEdit(cfg.place)
        form.addRow("Nome", self.name)
        self.lat = QDoubleSpinBox(); self.lat.setRange(-90, 90); self.lat.setDecimals(4); self.lat.setSuffix(" °N")
        self.lon = QDoubleSpinBox(); self.lon.setRange(-180, 180); self.lon.setDecimals(4); self.lon.setSuffix(" °E")
        self.lat.setValue(cfg.lat); self.lon.setValue(cfg.lon)
        form.addRow("Latitudine", self.lat)
        form.addRow("Longitudine", self.lon)
        self.scale = QSlider(Qt.Horizontal); self.scale.setRange(50, 200); self.scale.setValue(int(cfg.star_scale * 100))
        form.addRow("Dimensione stelle", self.scale)
        self.splash = QCheckBox("Mostra la schermata iniziale")
        self.splash.setChecked(cfg.show_splash)
        form.addRow("", self.splash)
        lay.addLayout(form)
        hint = QLabel("Il fuso orario è quello del sistema. L'ora mostrata e modificabile è sempre l'ora locale del computer.")
        hint.setObjectName("muted"); hint.setWordWrap(True)
        lay.addWidget(hint)
        self.err = QLabel("")
        self.err.setStyleSheet("color: #f87171;")
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Annulla"); cancel.clicked.connect(self.reject)
        ok = QPushButton("OK"); ok.setObjectName("primary"); ok.clicked.connect(self._accept)
        row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)
        idx = self.place.findText(cfg.place)
        self.place.blockSignals(True)
        self.place.setCurrentIndex(idx if idx >= 0 and abs(self.place.itemData(idx)[0] - cfg.lat) < 0.01 else self.place.count() - 1)
        self.place.blockSignals(False)

    def _place_changed(self, _i: int) -> None:
        d = self.place.currentData()
        if d is not None:
            self.lat.setValue(d[0]); self.lon.setValue(d[1]); self.name.setText(self.place.currentText())

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.err.setText("Dai un nome al luogo.")
            return
        lat, lon = self.lat.value(), self.lon.value()
        if (name, lat, lon) != (self.cfg.place, self.cfg.lat, self.cfg.lon) or not self.cfg.tz:
            self.cfg.tz = db().guess_tz(lat, lon, name)
        self.cfg.place, self.cfg.lat, self.cfg.lon = name, lat, lon
        self.cfg.star_scale = self.scale.value() / 100.0
        self.cfg.show_splash = self.splash.isChecked()
        self.accept()


class LocationDialog(QDialog):
    """Pick any place on Earth: name + coordinates (decimal degrees), optionally saved in the place list."""

    def __init__(self, name: str = "", lat: float = 0.0, lon: float = 0.0, tz: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Altro luogo")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("es. Il mio giardino")
        self.lat = QDoubleSpinBox(); self.lat.setRange(-90, 90); self.lat.setDecimals(4); self.lat.setSuffix(" °N (− = sud)")
        self.lon = QDoubleSpinBox(); self.lon.setRange(-180, 180); self.lon.setDecimals(4); self.lon.setSuffix(" °E (− = ovest)")
        self.lat.setValue(lat); self.lon.setValue(lon)
        form.addRow("Nome", self.name)
        form.addRow("Latitudine", self.lat)
        form.addRow("Longitudine", self.lon)
        self.tz = QLineEdit(tz)
        self.tz.setPlaceholderText("Europe/Rome — vuoto = automatico dalle coordinate")
        comp = QCompleter(sorted(zoneinfo.available_timezones()), self.tz)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.tz.setCompleter(comp)
        form.addRow("Fuso orario", self.tz)
        lay.addLayout(form)
        self.save = QCheckBox("Salva nell'elenco dei luoghi")
        self.save.setChecked(True)
        lay.addWidget(self.save)
        hint = QLabel("Coordinate in gradi decimali (le trovi in qualsiasi mappa: clic destro sul punto).")
        hint.setObjectName("muted"); hint.setWordWrap(True)
        lay.addWidget(hint)
        self.err = QLabel("")
        self.err.setStyleSheet("color: #f87171;")
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Annulla"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Vai"); ok.setObjectName("primary"); ok.clicked.connect(self._accept)
        row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)

    def _accept(self) -> None:
        if not self.name.text().strip():
            self.err.setText("Dai un nome al luogo.")
            return
        if self.tz.text().strip() and not valid_tz(self.tz.text().strip()):
            self.err.setText("Fuso orario sconosciuto (formato Continente/Città, es. Europe/Rome).")
            return
        self.accept()

    def result_place(self) -> tuple:
        lat, lon, name = self.lat.value(), self.lon.value(), self.name.text().strip()
        return name, lat, lon, self.tz.text().strip() or db().guess_tz(lat, lon, name)
