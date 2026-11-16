"""Star / constellation / deep-sky catalogue, loaded from the bundled data/sky.json.gz (see tools/build_catalog.py)."""
from __future__ import annotations

import array
import bisect
import gzip
import json
import math
import os
import struct
import sys
from dataclasses import dataclass, field

from .astro import radec_to_vec

DATA = os.path.join(os.path.dirname(__file__), "data", "sky.json.gz")
STARS = os.path.join(os.path.dirname(__file__), "data", "stars.bin.gz")
CELL_DEG = 5.0

DSO_TYPES = {"gc": "Ammasso globulare", "oc": "Ammasso aperto", "pn": "Nebulosa planetaria", "snr": "Resto di supernova",
             "s": "Galassia", "s0": "Galassia", "g": "Galassia", "gg": "Galassia", "sd": "Galassia", "i": "Galassia irregolare",
             "e": "Galassia ellittica", "en": "Nebulosa a emissione", "rn": "Nebulosa a riflessione", "sfr": "Regione di formazione stellare",
             "bn": "Nebulosa brillante", "dn": "Nebulosa oscura"}

GREEK = {"α": "Alfa", "β": "Beta", "γ": "Gamma", "δ": "Delta", "ε": "Epsilon", "ζ": "Zeta", "η": "Eta", "θ": "Theta", "ι": "Iota",
         "κ": "Kappa", "λ": "Lambda", "μ": "Mu", "ν": "Nu", "ξ": "Xi", "ο": "Omicron", "π": "Pi", "ρ": "Rho", "σ": "Sigma",
         "τ": "Tau", "υ": "Upsilon", "φ": "Phi", "χ": "Chi", "ψ": "Psi", "ω": "Omega"}


@dataclass
class Star:
    ra: float
    dec: float
    mag: float
    bv: float
    vec: tuple
    name: str = ""
    bayer: str = ""
    con: str = ""

    def label(self) -> str:
        if self.name:
            return self.name
        return f"{self.bayer} {self.con}".strip()


@dataclass
class Dso:
    desig: str
    type: str
    mag: float | None
    ra: float
    dec: float
    size: float
    name: str
    vec: tuple

    def label(self) -> str:
        return self.desig.replace("M ", "M") if self.desig.startswith("M ") else self.desig

    def type_name(self) -> str:
        return DSO_TYPES.get(self.type, "Oggetto del profondo cielo")


@dataclass
class Constellation:
    abbr: str
    name: str
    ra: float
    dec: float
    vec: tuple
    lines: list = field(default_factory=list)        # list of polylines, each a list of unit vectors
    segments: list = field(default_factory=list)     # flat list of (v1, v2)


class StarGrid:
    """The stars (up to magnitude 12) as flat arrays plus a sky grid, so that a view only visits the cells it can see."""

    def __init__(self, path: str = STARS):
        with gzip.open(path, "rb") as f:
            raw = f.read()
        if raw[:4] != b"SDK1":
            raise ValueError("not a StarDeck star file")
        n = struct.unpack("<I", raw[4:8])[0]
        pos = 8
        arrs = []
        for code, size in (("f", 4), ("f", 4), ("h", 2), ("b", 1)):
            a = array.array(code)
            a.frombytes(raw[pos:pos + n * size])
            pos += n * size
            arrs.append(a)
        if sys.byteorder == "big":
            for a in arrs[:3]:
                a.byteswap()
        self.n = n
        self.ra, self.dec = arrs[0], arrs[1]
        self.mag = [m / 100.0 for m in arrs[2]]
        self.bv = [b / 40.0 for b in arrs[3]]
        self.cls = [min(25, max(0, int((b + 0.3) * 10))) for b in self.bv]                       # colour class 0..25 from B-V
        self.fal = [int(min(0.75, max(0.15, 0.9 - (m - 6.5) * 0.12)) * 3.99) for m in self.mag]   # alpha class of faint (sub-pixel) stars
        d2r = math.pi / 180.0
        cd = [math.cos(d * d2r) for d in self.dec]
        self.vx = [c * math.cos(r * d2r) for c, r in zip(cd, self.ra)]
        self.vy = [c * math.sin(r * d2r) for c, r in zip(cd, self.ra)]
        self.vz = [math.sin(d * d2r) for d in self.dec]
        # grid: declination bands of CELL_DEG, each cut in RA bins of about the same angular width; lists stay sorted by magnitude
        nb = int(180.0 / CELL_DEG)
        self.bands = nb
        self.bins = [max(1, round(360.0 / CELL_DEG * math.cos(math.radians(-90 + (b + 0.5) * CELL_DEG)))) for b in range(nb)]
        self.cells = {}
        for i in range(n):
            b = min(nb - 1, int((self.dec[i] + 90.0) / CELL_DEG))
            k = min(self.bins[b] - 1, int(self.ra[i] / 360.0 * self.bins[b]))
            self.cells.setdefault((b, k), []).append(i)
        self.cell_geo = {}                                   # (band, bin) -> (centre unit vector, angular radius in rad)
        for (b, k) in self.cells:
            d0, d1 = -90.0 + b * CELL_DEG, -90.0 + (b + 1) * CELL_DEG
            r0, r1 = k * 360.0 / self.bins[b], (k + 1) * 360.0 / self.bins[b]
            c = radec_to_vec((r0 + r1) / 2, (d0 + d1) / 2)
            rad = max(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(c, radec_to_vec(rr, dd))))))
                      for rr in (r0, r1) for dd in (d0, d1, (d0 + d1) / 2))
            self.cell_geo[(b, k)] = (c, rad + 0.002)
        self.flat_cells = [(c[0], c[1], c[2], math.cos(rad), math.sin(rad), self.cells[key]) for key, (c, rad) in self.cell_geo.items()]
        self.sorted_mag = self.mag                          # already sorted: index order is brightness order

    def count_le(self, mag: float) -> int:
        return bisect.bisect_right(self.sorted_mag, mag)


class Catalog:
    def __init__(self, path: str = DATA, stars_path: str = STARS):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
        self.grid = StarGrid(stars_path)
        self.names_by_index = {idx: (name, bayer, con) for idx, name, bayer, con in raw["names"]}
        self.named = [self.star(idx) for idx in self.names_by_index]
        self.dsos = [Dso(d, t, m, ra, dec, size, name, radec_to_vec(ra, dec)) for d, t, m, ra, dec, size, name in raw["dso"]]
        self.constellations: dict[str, Constellation] = {}
        for abbr, c in raw["const"].items():
            con = Constellation(abbr, c["name"], c["pos"][0], c["pos"][1], radec_to_vec(*c["pos"]))
            for line in c["lines"]:
                vecs = [radec_to_vec(ra, dec) for ra, dec in line]
                con.lines.append(vecs)
                con.segments.extend(zip(vecs[:-1], vecs[1:]))
            self.constellations[abbr] = con
        self.milky_way = [[[radec_to_vec(ra, dec) for ra, dec in ring[::2]] for ring in level if len(ring) > 6] for level in raw["mw"]]

    def star(self, i: int) -> Star:
        g = self.grid
        name, bayer, con = self.names_by_index.get(i, ("", "", ""))
        return Star(float(g.ra[i]), float(g.dec[i]), g.mag[i], g.bv[i], (g.vx[i], g.vy[i], g.vz[i]), name, bayer, con)

    def find_star(self, name: str):
        """A named star by exact (case-insensitive) proper name, or None."""
        n = name.lower()
        return next((s for s in self.named if s.name.lower() == n), None)

    def find(self, text: str, limit: int = 12) -> list:
        """Case-insensitive search over star names, constellations and deep-sky objects: [(kind, label, object)]."""
        t = text.strip().lower()
        if not t:
            return []
        out = []
        for s in self.named:
            if s.name and t in s.name.lower():
                out.append((0 if s.name.lower().startswith(t) else 1, "star", s.name, s))
        for c in self.constellations.values():
            if t in c.name.lower() or t == c.abbr.lower():
                out.append((0 if c.name.lower().startswith(t) else 1, "const", c.name, c))
        for d in self.dsos:
            lab = d.label()
            if t in lab.lower() or t in d.name.lower() or t.replace(" ", "") == lab.lower().replace(" ", ""):
                out.append((0 if lab.lower().replace(" ", "") == t.replace(" ", "") or d.name.lower().startswith(t) else 1, "dso",
                            f"{lab} — {d.name}" if d.name else lab, d))
        out.sort(key=lambda r: (r[0], len(r[2])))
        return [(k, lab, o) for _, k, lab, o in out[:limit]]
