"""Preset observing locations (name, latitude °N, longitude °E)."""
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


def parse_custom(text: str) -> list:
    """'Nome|lat|lon;Nome2|lat|lon' -> [(name, lat, lon)] (malformed entries are skipped)."""
    out = []
    for part in text.split(";"):
        bits = part.split("|")
        if len(bits) != 3:
            continue
        try:
            lat, lon = float(bits[1]), float(bits[2])
        except ValueError:
            continue
        if bits[0].strip() and -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((bits[0].strip(), lat, lon))
    return out


def format_custom(places: list) -> str:
    return ";".join(f"{n.replace('|', ' ').replace(';', ' ')}|{la:.5f}|{lo:.5f}" for n, la, lo in places)
