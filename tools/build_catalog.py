#!/usr/bin/env python3
"""Builds stardeck/data/sky.json.gz (names, constellations, deep sky, Milky Way) and stardeck/data/stars.bin.gz (stars to mag 12).

Sources: d3-celestial (BSD-3, (c) 2015 Olaf Frohn) for names / constellation figures / deep sky / Milky Way, and the HYG database v4.1
(astronexus/HYG-Database, CC-BY-SA 4.0; Hipparcos + Yale Bright Star + Gliese) for the stars.

    python3 tools/build_catalog.py [DIR_WITH_DOWNLOADED_JSON]

Without an argument the files are downloaded from GitHub. Output: a compact gzip-ed JSON with
  names   [[star index (position in stars.bin, brightest first), proper name, Bayer letter, constellation abbr.], ...]
  const   {abbr: {"name": Italian name, "pos": [ra, dec], "lines": [[[ra, dec], ...], ...]}}
  dso     [[designation, type, mag, ra, dec, major axis arcmin, name], ...]
  mw      [[ [[ra, dec], ...] ring, ... ] per brightness level]   (Milky Way outlines)
"""
import array
import csv
import gzip
import json
import os
import struct
import sys
import urllib.request

BASE = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/"
HYG_URL = "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv"
MAG_LIMIT = 12.0
STARS_OUT = os.path.join(os.path.dirname(__file__), "..", "stardeck", "data", "stars.bin.gz")
FILES = ["starnames.json", "constellations.json", "constellations.lines.json",
         "dsos.14.json", "dsonames.json", "mw.json"]
OUT = os.path.join(os.path.dirname(__file__), "..", "stardeck", "data", "sky.json.gz")
DSO_TYPES = {"gc", "oc", "pn", "snr", "s", "s0", "g", "gg", "sd", "i", "e", "en", "rn", "sfr"}


def load(d, name):
    path = os.path.join(d, name)
    if not os.path.exists(path):
        os.makedirs(d, exist_ok=True)
        urllib.request.urlretrieve(BASE + name, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ra360(x):
    return round(x % 360.0, 3)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "/tmp/stardeck_src"
    hyg = os.path.join(d, "hygdata_v41.csv")
    if not os.path.exists(hyg):
        os.makedirs(d, exist_ok=True)
        urllib.request.urlretrieve(HYG_URL, hyg)
    rows = []
    with open(hyg, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["id"] == "0" or not r["mag"] or not r["ra"] or not r["dec"]:
                continue
            mag = float(r["mag"])
            if mag > MAG_LIMIT:
                continue
            try:
                bv = max(-3.2, min(3.1, float(r["ci"]))) if r["ci"] else 0.6
            except ValueError:
                bv = 0.6
            rows.append((mag, int(r["id"]), float(r["ra"]) * 15.0, float(r["dec"]), bv, r["hip"]))
    rows.sort()
    n = len(rows)
    ra = array.array("f", (r[2] for r in rows))
    dec = array.array("f", (r[3] for r in rows))
    mag = array.array("h", (round(r[0] * 100) for r in rows))
    bv = array.array("b", (round(r[4] * 40) for r in rows))
    if sys.byteorder == "big":
        for a_ in (ra, dec, mag):
            a_.byteswap()
    with gzip.open(STARS_OUT, "wb", compresslevel=9) as fh:
        fh.write(b"SDK1" + struct.pack("<I", n) + ra.tobytes() + dec.tobytes() + mag.tobytes() + bv.tobytes())
    hip_to_idx = {int(r[5]): i for i, r in enumerate(rows) if r[5]}
    sn = load(d, "starnames.json")
    names = []
    for sid, info in sn.items():
        i = hip_to_idx.get(int(sid))
        if i is None:
            continue
        m = rows[i][0]
        if info.get("name") or (info.get("bayer") and m < 4.0):
            names.append([i, info.get("name", ""), info.get("bayer", ""), info.get("c", "")])
    names.sort()
    print(f"stars={n} (mag <= {MAG_LIMIT}) -> {os.path.getsize(STARS_OUT) // 1024} KiB")

    cons_meta = load(d, "constellations.json")["features"]
    cons_lines = {f["id"]: f["geometry"]["coordinates"] for f in load(d, "constellations.lines.json")["features"]}
    const = {}
    for f in cons_meta:
        cid = f["id"]
        if cid not in cons_lines:
            continue
        ra, dec = f["geometry"]["coordinates"]
        pr = f["properties"]
        const[cid] = {"name": (pr.get("it") or pr["name"]).replace(" ", " "), "pos": [ra360(ra), round(dec, 2)],
                      "lines": [[[ra360(x), round(y, 3)] for x, y in line] for line in cons_lines[cid]]}

    dn = load(d, "dsonames.json")
    cand = []
    for f in load(d, "dsos.14.json")["features"]:
        pr = f["properties"]
        desig, typ = pr["desig"], pr["type"]
        try:
            mag = float(pr["mag"])
        except ValueError:
            mag = 99.0
        messier = desig.startswith("M ")
        if not messier and not (typ in DSO_TYPES and 0.0 < mag <= 9.0):
            continue
        try:
            dim = float(str(pr.get("dim") or "0").split("x")[0])
        except ValueError:
            dim = 0.0
        lon, lat = f["geometry"]["coordinates"]
        nm = dn.get(desig) or dn.get(str(f["id"])) or {}
        cand.append((0 if messier else 1, [desig, typ, None if mag > 90 or mag <= 0 else mag, ra360(lon), round(lat, 3), dim,
                                          nm.get("it") or nm.get("name", "")]))
    cand.sort(key=lambda t: t[0])
    dso = []                                   # drop NGC/IC duplicates of Messier objects (same position)
    for _, row in cand:
        if any(abs(((row[3] - o[3] + 180) % 360) - 180) < 0.1 and abs(row[4] - o[4]) < 0.1 for o in dso):
            continue
        dso.append(row)
    dso.sort(key=lambda r: (99 if r[2] is None else r[2]))

    mw = []
    for f in load(d, "mw.json")["features"]:
        rings = []
        for poly in f["geometry"]["coordinates"]:
            for ring in poly:
                rings.append([[ra360(x), round(y, 2)] for x, y in ring[::2]])
        mw.append(rings)

    out = {"names": names, "const": const, "dso": dso, "mw": mw}
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"names={len(names)} const={len(const)} dso={len(dso)} mw={len(mw)}"
          f" -> {os.path.getsize(OUT)//1024} KiB")


if __name__ == "__main__":
    main()
