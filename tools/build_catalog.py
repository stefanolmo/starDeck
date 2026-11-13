#!/usr/bin/env python3
"""Builds stardeck/data/sky.json.gz from the d3-celestial data files (BSD-3, (c) 2015 Olaf Frohn).

    python3 tools/build_catalog.py [DIR_WITH_DOWNLOADED_JSON]

Without an argument the files are downloaded from GitHub. Output: a compact gzip-ed JSON with
  stars   [[ra°, dec°, mag, B-V], ...]  sorted by magnitude (brightest first)
  names   [[star index, proper name, Bayer letter, constellation abbr.], ...]
  const   {abbr: {"name": Italian name, "pos": [ra, dec], "lines": [[[ra, dec], ...], ...]}}
  dso     [[designation, type, mag, ra, dec, major axis arcmin, name], ...]
  mw      [[ [[ra, dec], ...] ring, ... ] per brightness level]   (Milky Way outlines)
"""
import gzip
import json
import os
import sys
import urllib.request

BASE = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/"
FILES = ["stars.6.json", "starnames.json", "constellations.json", "constellations.lines.json",
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
    stars_raw = load(d, "stars.6.json")["features"]
    sn = load(d, "starnames.json")
    stars = []
    for f in stars_raw:
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        try:
            bv = float(p.get("bv") or 0.6)
        except ValueError:
            bv = 0.6
        stars.append((float(p["mag"]), ra360(lon), round(lat, 3), round(bv, 2), str(f["id"])))
    stars.sort()
    names = []
    for i, (mag, ra, dec, bv, sid) in enumerate(stars):
        info = sn.get(sid)
        if info and (info.get("name") or (info.get("bayer") and mag < 4.0)):
            names.append([i, info.get("name", ""), info.get("bayer", ""), info.get("c", "")])
    stars_out = [[ra, dec, mag, bv] for mag, ra, dec, bv, _ in stars]

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

    out = {"stars": stars_out, "names": names, "const": const, "dso": dso, "mw": mw}
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"stars={len(stars_out)} names={len(names)} const={len(const)} dso={len(dso)} mw={len(mw)}"
          f" -> {os.path.getsize(OUT)//1024} KiB")


if __name__ == "__main__":
    main()
