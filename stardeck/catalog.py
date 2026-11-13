"""Star / constellation / deep-sky catalogue, loaded from the bundled data/sky.json.gz (see tools/build_catalog.py)."""
from __future__ import annotations

import gzip
import json
import math
import os
from dataclasses import dataclass, field

from .astro import radec_to_vec

DATA = os.path.join(os.path.dirname(__file__), "data", "sky.json.gz")

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


class Catalog:
    def __init__(self, path: str = DATA):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
        self.stars = [Star(ra, dec, mag, bv, radec_to_vec(ra, dec)) for ra, dec, mag, bv in raw["stars"]]
        for idx, name, bayer, con in raw["names"]:
            s = self.stars[idx]
            s.name, s.bayer, s.con = name, bayer, con
        self.named = [s for s in self.stars if s.name or s.bayer]
        self.dsos = [Dso(d, t, m, ra, dec, size, name, radec_to_vec(ra, dec)) for d, t, m, ra, dec, size, name in raw["dso"]]
        self.constellations: dict[str, Constellation] = {}
        for abbr, c in raw["const"].items():
            con = Constellation(abbr, c["name"], c["pos"][0], c["pos"][1], radec_to_vec(*c["pos"]))
            for line in c["lines"]:
                vecs = [radec_to_vec(ra, dec) for ra, dec in line]
                con.lines.append(vecs)
                con.segments.extend(zip(vecs[:-1], vecs[1:]))
            self.constellations[abbr] = con
        self.milky_way = [[[radec_to_vec(ra, dec) for ra, dec in ring] for ring in level] for level in raw["mw"]]

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
