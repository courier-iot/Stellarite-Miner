"""Star catalog and the star-route problem used by Pulsarite's proof of work.

Coordinates are integers in milli-light-years with the Sun at the origin, so
every node computes identical distances (no floating point in consensus).

The built-in list holds ~50 well-known nearby star systems with approximate
positions (RA/Dec/distance rounded from public catalogs). For real science,
build stars.json from a full catalog with tools/build_catalog.py. Every node
on a network must use the same catalog.
"""
import hashlib
import json
import math
import os

# name, right ascension (hours), declination (degrees), distance (light-years)
_BUILTIN = [
    ("Proxima Centauri", 14.495, -62.68, 4.24), ("Alpha Centauri", 14.660, -60.83, 4.37),
    ("Barnard's Star", 17.963, 4.69, 5.96), ("Wolf 359", 10.940, 7.01, 7.86),
    ("Lalande 21185", 11.055, 35.97, 8.31), ("Sirius", 6.752, -16.72, 8.60),
    ("UV Ceti", 1.650, -17.95, 8.79), ("Ross 154", 18.830, -23.84, 9.70),
    ("Ross 248", 23.698, 44.17, 10.30), ("Epsilon Eridani", 3.549, -9.46, 10.47),
    ("Lacaille 9352", 23.097, -35.85, 10.72), ("Ross 128", 11.795, 0.80, 11.01),
    ("EZ Aquarii", 22.643, -15.30, 11.11), ("61 Cygni", 21.115, 38.75, 11.40),
    ("Procyon", 7.655, 5.22, 11.46), ("Struve 2398", 18.713, 59.63, 11.49),
    ("Groombridge 34", 0.305, 44.02, 11.62), ("DX Cancri", 8.497, 26.78, 11.68),
    ("Epsilon Indi", 22.055, -56.79, 11.87), ("Tau Ceti", 1.734, -15.94, 11.91),
    ("GJ 1061", 3.598, -44.51, 11.98), ("YZ Ceti", 1.208, -16.99, 12.11),
    ("Luyten's Star", 7.457, 5.23, 12.35), ("Teegarden's Star", 2.888, 16.88, 12.50),
    ("Kapteyn's Star", 5.194, -45.02, 12.83), ("Lacaille 8760", 21.290, -38.87, 12.95),
    ("SCR 1845-6357", 18.760, -63.96, 13.05), ("Kruger 60", 22.466, 57.70, 13.07),
    ("Wolf 1061", 16.508, -12.66, 14.05), ("Van Maanen's Star", 0.820, 5.39, 14.07),
    ("Gliese 1", 0.090, -37.36, 14.20), ("LHS 292", 10.810, -11.34, 14.80),
    ("Gliese 687", 17.607, 68.34, 14.84), ("Gliese 674", 17.479, -46.90, 14.85),
    ("Gliese 876", 22.887, -14.26, 15.24), ("Gliese 832", 21.555, -49.01, 16.20),
    ("40 Eridani", 4.254, -7.65, 16.30), ("70 Ophiuchi", 18.092, 2.50, 16.60),
    ("Altair", 19.846, 8.87, 16.73), ("Sigma Draconis", 19.540, 69.66, 18.80),
    ("Eta Cassiopeiae", 0.818, 57.82, 19.42), ("82 Eridani", 3.330, -43.07, 19.71),
    ("Delta Pavonis", 20.146, -66.18, 19.92), ("Gliese 581", 15.324, -7.72, 20.50),
    ("Gliese 667 C", 17.314, -34.99, 23.60), ("Vega", 18.616, 38.78, 25.04),
    ("Fomalhaut", 22.961, -29.62, 25.13), ("Pollux", 7.755, 28.03, 33.78),
    ("Arcturus", 14.261, 19.18, 36.66), ("TRAPPIST-1", 23.108, -5.04, 40.66),
    ("Capella", 5.278, 46.00, 42.92), ("Aldebaran", 4.599, 16.51, 65.30),
]

STARS_PER_PROBLEM = 24
SOL = (0, 0, 0)


def _from_equatorial(name, ra_h, dec_d, dist_ly):
    ra, dec = math.radians(ra_h * 15), math.radians(dec_d)
    r = dist_ly * 1000
    return {"name": name,
            "x": round(r * math.cos(dec) * math.cos(ra)),
            "y": round(r * math.cos(dec) * math.sin(ra)),
            "z": round(r * math.sin(dec))}


def _load():
    path = os.environ.get("PULSARITE_STARS") or os.path.join(os.path.dirname(__file__), "stars.json")
    if os.path.exists(path):
        with open(path) as f:
            stars = json.load(f)
        source = os.path.basename(path)
    else:
        stars = [_from_equatorial(*s) for s in _BUILTIN]
        source = "built-in"
    for i, s in enumerate(stars):
        s["id"] = i
    return stars, source


CATALOG, CATALOG_SOURCE = _load()
if len(CATALOG) < STARS_PER_PROBLEM:
    raise RuntimeError("star catalog is smaller than STARS_PER_PROBLEM")

# Fingerprint so nodes can tell they're using the same catalog.
CATALOG_ID = hashlib.sha256(json.dumps(
    [[s["x"], s["y"], s["z"]] for s in CATALOG]).encode()).hexdigest()[:16]


def pos(star_id):
    s = CATALOG[star_id]
    return s["x"], s["y"], s["z"]


def distance(a, b) -> int:
    """Exact integer distance in milli-light-years (floor of the true distance)."""
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def problem(prev_hash: str) -> list:
    """The stars a block must route through, chosen unpredictably from the previous block's hash."""
    pool = list(range(len(CATALOG)))
    chosen = []
    seed = bytes.fromhex(prev_hash)
    i = 0
    while len(chosen) < STARS_PER_PROBLEM:
        r = int.from_bytes(hashlib.sha256(seed + b"stars" + i.to_bytes(4, "big")).digest(), "big")
        chosen.append(pool.pop(r % len(pool)))
        i += 1
    return sorted(chosen)


def route_length(route) -> int:
    """Length of an open path that starts at the Sun and visits the stars in order."""
    total, here = 0, SOL
    for sid in route:
        p = pos(sid)
        total += distance(here, p)
        here = p
    return total


def baseline_route(stars) -> list:
    """Greedy nearest-neighbour route from the Sun: the bar a miner's route is scored against."""
    left = sorted(stars)
    here, route = SOL, []
    while left:
        nxt = min(left, key=lambda s: (distance(here, pos(s)), s))
        left.remove(nxt)
        route.append(nxt)
        here = pos(nxt)
    return route
