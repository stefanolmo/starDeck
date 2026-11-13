"""Reusable widgets: card."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class Card(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 12, 14, 14)
        self._lay.setSpacing(10)
        self.title_label = None
        if title:
            self.title_label = QLabel(title.upper())
            self.title_label.setObjectName("cardTitle")
            self._lay.addWidget(self.title_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self._lay.addLayout(self.body)
