"""Preset observing locations (name, latitude °N, longitude °E)."""
import gzip
import json
import math
import os
import unicodedata
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PLACES = [
    ("Roma", 41.90, 12.50), ("Milano", 45.46, 9.19), ("Torino", 45.07, 7.69), ("Venezia", 45.44, 12.33),
    ("Bologna", 44.49, 11.34), ("Firenze", 43.77, 11.26), ("Napoli", 40.85, 14.27), ("Bari", 41.12, 16.87),
    ("Palermo", 38.12, 13.36), ("Cagliari", 39.22, 9.12), ("Lecce", 40.35, 18.17), ("Catanzaro", 38.91, 16.59),
    ("Genova", 44.41, 8.93), ("Trieste", 45.65, 13.78), ("Perugia", 43.11, 12.39), ("Pescara", 42.46, 14.21), ("Reggio Calabria", 38.11, 15.65),
    ("Cosenza", 39.30, 16.25), ("Catania", 37.50, 15.09), ("Aosta", 45.74, 7.32), ("Cortina d'Ampezzo", 46.54, 12.14), ("Stromboli", 38.79, 15.21),
    ("Londra", 51.51, -0.13), ("Parigi", 48.86, 2.35), ("Madrid", 40.42, -3.70), ("Berlino", 52.52, 13.40),
    ("Atene", 37.98, 23.73), ("Vienna", 48.21, 16.37), ("Zurigo", 47.38, 8.54), ("Amsterdam", 52.37, 4.90), ("Lisbona", 38.72, -9.14),
    ("Stoccolma", 59.33, 18.07), ("Mosca", 55.76, 37.62), ("Istanbul", 41.01, 28.98), ("Gerusalemme", 31.77, 35.21), ("Nairobi", -1.29, 36.82),
    ("Pechino", 39.90, 116.41), ("Singapore", 1.35, 103.82), ("Bangkok", 13.76, 100.50), ("Delhi", 28.61, 77.21), ("Rio de Janeiro", -22.91, -43.17),
    ("Toronto", 43.65, -79.38), ("Chicago", 41.88, -87.63), ("San Francisco", 37.77, -122.42), ("Deserto di Atacama", -23.86, -69.14), ("Reykjavik", 64.15, -21.94), ("Il Cairo", 30.04, 31.24), ("Città del Capo", -33.92, 18.42),
    ("Dubai", 25.20, 55.27), ("Mumbai", 19.08, 72.88), ("Tokyo", 35.68, 139.69), ("Sydney", -33.87, 151.21),
    ("Auckland", -36.85, 174.76), ("New York", 40.71, -74.01), ("Los Angeles", 34.05, -118.24),
    ("Città del Messico", 19.43, -99.13), ("Buenos Aires", -34.60, -58.38), ("Santiago del Cile", -33.45, -70.67),
    ("Mauna Kea (Hawaii)", 19.82, -155.47), ("Polo Nord", 90.0, 0.0), ("Polo Sud", -90.0, 0.0), ("Equatore (0°, 0°)", 0.0, 0.0),
]


TZ_OVERRIDE = {"Polo Nord": "UTC", "Polo Sud": "UTC", "Equatore (0°, 0°)": "UTC", "Mauna Kea (Hawaii)": "Pacific/Honolulu",
               "Deserto di Atacama": "America/Santiago", "Stromboli": "Europe/Rome", "Cortina d'Ampezzo": "Europe/Rome"}
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cities.json.gz")


def norm(text: str) -> str:
    """Lower-case, accents and punctuation stripped: 'Città del Capo' -> 'citta del capo'."""
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch) and (ch.isalnum() or ch == " ")).strip()


def valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def tzinfo(name: str):
    """ZoneInfo for an IANA name; None (= system local time) when empty or unknown."""
    return ZoneInfo(name) if name and valid_tz(name) else None


class Place(NamedTuple):
    name: str
    lat: float
    lon: float
    tz: str = ""
    cc: str = ""
    pop: int = 0
    mine: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} · {self.cc}" if self.cc else self.name


class PlaceDB:
    """Offline gazetteer (GeoNames cities >= 15000 inhabitants) + the preset list: search by name, nearest-city time zone."""

    def __init__(self, path: str = DB_PATH):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
        tzs = raw["tz"]
        self.cities = [Place(n, la, lo, tzs[ti], cc, pop) for n, cc, la, lo, ti, pop in raw["c"]]
        self._keys = [norm(c.name) for c in self.cities]

    def guess_tz(self, lat: float, lon: float, name: str = "") -> str:
        """Time zone of the nearest city; Etc/GMT±n from the longitude if nothing is within ~6 degrees."""
        if name in TZ_OVERRIDE:
            return TZ_OVERRIDE[name]
        best, best_d = None, 1e9
        cl = math.cos(math.radians(lat))
        for c in self.cities:
            dx = ((c.lon - lon + 180.0) % 360.0 - 180.0) * cl
            d = dx * dx + (c.lat - lat) ** 2
            if d < best_d:
                best, best_d = c, d
        if best is not None and best_d < 36.0:
            return best.tz
        off = round(lon / 15.0)
        return "UTC" if off == 0 else f"Etc/GMT{-off:+d}"

    def search(self, text: str, extra=(), limit: int = 14) -> list:
        """Places whose name starts with / contains `text`; `extra` (saved and preset places) come first, then cities by population."""
        t = norm(text)
        if len(t) < 2:
            return []
        scored = []
        for p in extra:
            k = norm(p.name)
            if k.startswith(t):
                scored.append((0, 0, 0, p))
            elif t in k:
                scored.append((1, 0, 0, p))
        for k, c in zip(self._keys, self.cities):
            if k.startswith(t):
                scored.append((0, 1, -c.pop, c))
            elif t in k:
                scored.append((1, 1, -c.pop, c))
        scored.sort(key=lambda r: r[:3])
        out = []
        for *_, p in scored:
            if any(abs(p.lat - q.lat) < 0.2 and abs(p.lon - q.lon) < 0.2 for q in out):
                continue                                       # same town listed twice (Roma / Rome)
            out.append(p)
            if len(out) >= limit:
                break
        return out


_db = None


def db() -> PlaceDB:
    global _db
    if _db is None:
        _db = PlaceDB()
    return _db


def preset_places() -> list:
    return [Place(n, la, lo, TZ_OVERRIDE.get(n, "")) for n, la, lo in PLACES]


def parse_custom(text: str) -> list:
    """'Nome|lat|lon[|tz];...' -> [Place] (malformed entries are skipped)."""
    out = []
    for part in text.split(";"):
        bits = part.split("|")
        if len(bits) not in (3, 4):
            continue
        try:
            lat, lon = float(bits[1]), float(bits[2])
        except ValueError:
            continue
        if bits[0].strip() and -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append(Place(bits[0].strip(), lat, lon, bits[3].strip() if len(bits) == 4 else "", mine=True))
    return out


def format_custom(places: list) -> str:
    return ";".join(f"{p.name.replace('|', ' ').replace(';', ' ')}|{p.lat:.5f}|{p.lon:.5f}|{p.tz}" for p in places)
