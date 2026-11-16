#!/usr/bin/env python3
"""Builds stardeck/data/cities.json.gz (cities >= 15000 inhabitants with coordinates and IANA time zone) from GeoNames.

    pip install geonamescache && python3 tools/build_places.py

Data: GeoNames (https://www.geonames.org), licence CC-BY 4.0 - credit in README.
"""
import gzip
import json
import os

import geonamescache

OUT = os.path.join(os.path.dirname(__file__), "..", "stardeck", "data", "cities.json.gz")


def main():
    rows = [c for c in geonamescache.GeonamesCache().get_cities().values() if c["population"] >= 15000 and c.get("timezone")]
    rows.sort(key=lambda c: -c["population"])
    tzs = sorted({c["timezone"] for c in rows})
    idx = {t: i for i, t in enumerate(tzs)}
    out = {"tz": tzs, "c": [[c["name"], c["countrycode"], round(c["latitude"], 3), round(c["longitude"], 3), idx[c["timezone"]], c["population"]]
                            for c in rows]}
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(rows)} cities, {len(tzs)} time zones -> {os.path.getsize(OUT) // 1024} KiB")


if __name__ == "__main__":
    main()
