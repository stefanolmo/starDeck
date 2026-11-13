"""Application settings (persisted with QSettings) as a plain dataclass."""
from __future__ import annotations

from dataclasses import dataclass, fields

ORG = "stardeck"
APP = "stardeck"


@dataclass
class Config:
    # observer
    place: str = "Roma"
    lat: float = 41.90              # degrees north
    lon: float = 12.50              # degrees east
    # layers
    show_constellation_lines: bool = True
    show_constellation_names: bool = True
    show_star_names: bool = True
    show_planets: bool = True
    show_dso: bool = True
    show_milky_way: bool = True
    show_grid_altaz: bool = False
    show_grid_eq: bool = False
    show_ecliptic: bool = True
    show_ground: bool = True
    show_atmosphere: bool = True    # sky colour by twilight, faint stars wash out by day
    show_cardinals: bool = True
    # display
    star_scale: float = 1.0
    show_splash: bool = True

    def load(self, qs) -> "Config":
        for f in fields(self):
            if not qs.contains(f.name):
                continue
            v = qs.value(f.name)
            cur = getattr(self, f.name)
            try:
                if isinstance(cur, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
                elif isinstance(cur, int):
                    v = int(float(v))
                elif isinstance(cur, float):
                    v = float(v)
                else:
                    v = str(v)
            except (TypeError, ValueError):
                continue
            setattr(self, f.name, v)
        return self

    def save(self, qs) -> None:
        for f in fields(self):
            qs.setValue(f.name, getattr(self, f.name))
        qs.sync()
