"""Star catalog and the star-route problem used by Pulsarite's proof of work.

The problem: a probe launched from the Sun in LAUNCH_YEAR, cruising at
PROBE_SPEED, must fly past each of a block's 24 stars. Stars move (proper
motion and radial velocity), so each leg aims at where the star *will be* when
the probe arrives. A route is scored by total mission time.

Everything is integer arithmetic so every node gets identical answers:
  positions   milli-light-years (mly), Sun at the origin, J2000 epoch
  velocities  mly per thousand years (equivalently: light-years per million years)
  time        milli-years (thousandths of a year, ~8.8 hours)

The built-in list holds ~50 well-known nearby star systems with approximate
positions and motions (rounded from public catalogs). For real science, build
stars.json from a full catalog with tools/build_catalog.py. Every node on a
network must use the same catalog.
"""
import hashlib
import json
import math
import os

import config as C

# name, RA (hours), Dec (deg), distance (ly), proper motion RA*cos(Dec) and Dec ("/yr), radial velocity (km/s)
_BUILTIN = [
    ("Proxima Centauri", 14.495, -62.68, 4.24, -3.78, 0.77, -22.2),
    ("Alpha Centauri", 14.660, -60.83, 4.37, -3.64, 0.70, -22.0),
    ("Barnard's Star", 17.963, 4.69, 5.96, -0.80, 10.36, -110.5),
    ("Wolf 359", 10.940, 7.01, 7.86, -3.84, -2.73, 19.0),
    ("Lalande 21185", 11.055, 35.97, 8.31, -0.58, -4.77, -85.0),
    ("Sirius", 6.752, -16.72, 8.60, -0.55, -1.22, -5.5),
    ("UV Ceti", 1.650, -17.95, 8.79, 3.32, 0.59, 29.0),
    ("Ross 154", 18.830, -23.84, 9.70, 0.64, -0.19, -10.7),
    ("Ross 248", 23.698, 44.17, 10.30, 0.11, -1.59, -78.0),
    ("Epsilon Eridani", 3.549, -9.46, 10.47, -0.98, 0.02, 16.4),
    ("Lacaille 9352", 23.097, -35.85, 10.72, 6.77, 1.33, 8.8),
    ("Ross 128", 11.795, 0.80, 11.01, 0.61, -1.22, -31.0),
    ("EZ Aquarii", 22.643, -15.30, 11.11, 2.31, 2.24, -60.0),
    ("61 Cygni", 21.115, 38.75, 11.40, 4.16, 3.25, -65.0),
    ("Procyon", 7.655, 5.22, 11.46, -0.71, -1.04, -3.2),
    ("Struve 2398", 18.713, 59.63, 11.49, -1.33, 1.80, -1.0),
    ("Groombridge 34", 0.305, 44.02, 11.62, 2.89, 0.41, 12.0),
    ("DX Cancri", 8.497, 26.78, 11.68, -1.11, -0.56, 10.0),
    ("Epsilon Indi", 22.055, -56.79, 11.87, 3.77, -2.54, -40.0),
    ("Tau Ceti", 1.734, -15.94, 11.91, -1.72, 0.85, -16.7),
    ("GJ 1061", 3.598, -44.51, 11.98, 0.75, -0.30, -20.0),
    ("YZ Ceti", 1.208, -16.99, 12.11, 1.21, 0.64, 28.0),
    ("Luyten's Star", 7.457, 5.23, 12.35, 0.57, -3.69, 18.0),
    ("Teegarden's Star", 2.888, 16.88, 12.50, 3.43, -3.81, 68.0),
    ("Kapteyn's Star", 5.194, -45.02, 12.83, 6.51, -5.73, 245.0),
    ("Lacaille 8760", 21.290, -38.87, 12.95, -3.26, -1.15, 21.0),
    ("SCR 1845-6357", 18.760, -63.96, 13.05, 2.60, 0.60, 0.0),
    ("Kruger 60", 22.466, 57.70, 13.07, -0.73, -0.22, -34.0),
    ("Wolf 1061", 16.508, -12.66, 14.05, -0.09, -1.18, -21.0),
    ("Van Maanen's Star", 0.820, 5.39, 14.07, 1.23, -2.71, 54.0),
    ("Gliese 1", 0.090, -37.36, 14.20, 5.63, -2.34, 23.0),
    ("LHS 292", 10.810, -11.34, 14.80, -0.55, -1.53, 0.0),
    ("Gliese 687", 17.607, 68.34, 14.84, -0.32, -1.27, -29.0),
    ("Gliese 674", 17.479, -46.90, 14.85, 0.57, -0.88, -3.0),
    ("Gliese 876", 22.887, -14.26, 15.24, 0.96, -0.68, -1.6),
    ("Gliese 832", 21.555, -49.01, 16.20, -0.05, -0.82, 13.0),
    ("40 Eridani", 4.254, -7.65, 16.30, -2.24, -3.42, -42.0),
    ("70 Ophiuchi", 18.092, 2.50, 16.60, 0.25, -1.10, -7.0),
    ("Altair", 19.846, 8.87, 16.73, 0.54, 0.39, -26.0),
    ("Sigma Draconis", 19.540, 69.66, 18.80, 0.60, -1.74, 27.0),
    ("Eta Cassiopeiae", 0.818, 57.82, 19.42, 1.09, -0.56, 9.0),
    ("82 Eridani", 3.330, -43.07, 19.71, 3.04, 0.73, 87.0),
    ("Delta Pavonis", 20.146, -66.18, 19.92, 1.21, -1.13, -22.0),
    ("Gliese 581", 15.324, -7.72, 20.50, -1.22, -0.10, -9.0),
    ("Gliese 667 C", 17.314, -34.99, 23.60, 1.13, -0.22, 6.0),
    ("Vega", 18.616, 38.78, 25.04, 0.20, 0.29, -14.0),
    ("Fomalhaut", 22.961, -29.62, 25.13, 0.33, -0.16, 6.5),
    ("Pollux", 7.755, 28.03, 33.78, -0.63, -0.05, 3.2),
    ("Arcturus", 14.261, 19.18, 36.66, -1.09, -2.00, -5.2),
    ("TRAPPIST-1", 23.108, -5.04, 40.66, 0.93, -0.47, -54.0),
    ("Capella", 5.278, 46.00, 42.92, 0.08, -0.43, 30.0),
    ("Aldebaran", 4.599, 16.51, 65.30, 0.06, -0.19, 54.0),
]

# Confirmed planets per system (Wikipedia, "List of nearest exoplanets", checked
# November 2026, plus TRAPPIST-1 and Pollux beyond that list's range). Candidates,
# disputed and refuted planets don't count. Systems not listed have none known.
PLANETS = {
    "Proxima Centauri": 2, "Barnard's Star": 4, "Lalande 21185": 2, "Epsilon Eridani": 1,
    "Lacaille 9352": 4, "Ross 128": 1, "Struve 2398": 2, "Groombridge 34": 2, "Epsilon Indi": 1,
    "GJ 1061": 3, "YZ Ceti": 3, "Luyten's Star": 2, "Teegarden's Star": 3, "Wolf 1061": 3,
    "Gliese 687": 2, "Gliese 674": 1, "Gliese 876": 4, "Gliese 832": 1, "82 Eridani": 3,
    "Gliese 581": 3, "Gliese 667 C": 2, "Pollux": 1, "TRAPPIST-1": 7,
}

STARS_PER_PROBLEM = 24
SOL = (0, 0, 0)
KMS_TO_LY_PER_YR = 1 / 299792.458
INTERCEPT_ITERATIONS = 3


def _from_catalog(name, ra_h, dec_d, dist_ly, pm_ra, pm_dec, rv):
    ra, dec = math.radians(ra_h * 15), math.radians(dec_d)
    r = dist_ly * 1000
    radial = (math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec))
    east = (-math.sin(ra), math.cos(ra), 0.0)
    north = (-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra), math.cos(dec))
    dist_pc = dist_ly / 3.26156
    v_east, v_north = 4.74047 * pm_ra * dist_pc, 4.74047 * pm_dec * dist_pc     # km/s
    vel = [rv * radial[k] + v_east * east[k] + v_north * north[k] for k in range(3)]
    kms_to_mly_per_kyr = KMS_TO_LY_PER_YR * 1e6
    return {"name": name,
            "x": round(r * radial[0]), "y": round(r * radial[1]), "z": round(r * radial[2]),
            "vx": round(vel[0] * kms_to_mly_per_kyr), "vy": round(vel[1] * kms_to_mly_per_kyr),
            "vz": round(vel[2] * kms_to_mly_per_kyr)}


def _load():
    path = os.environ.get("PULSARITE_STARS") or os.path.join(os.path.dirname(__file__), "stars.json")
    if os.path.exists(path):
        with open(path) as f:
            stars = json.load(f)
        source = os.path.basename(path)
    else:
        stars = [_from_catalog(*s) for s in _BUILTIN]
        source = "built-in"
    for i, s in enumerate(stars):
        s["id"] = i
        for k in ("vx", "vy", "vz"):
            s.setdefault(k, 0)
        s.setdefault("planets", PLANETS.get(s.get("name"), 0))
    return stars, source


CATALOG, CATALOG_SOURCE = _load()
if len(CATALOG) < STARS_PER_PROBLEM:
    raise RuntimeError("star catalog is smaller than STARS_PER_PROBLEM")

# Fingerprint so nodes can tell they're using the same catalog.
CATALOG_ID = hashlib.sha256(json.dumps(
    [[s["x"], s["y"], s["z"], s["vx"], s["vy"], s["vz"], s["planets"]] for s in CATALOG]).encode()).hexdigest()[:16]

SPEED = C.PROBE_SPEED_MLY_PER_YEAR                 # mly per year
LAUNCH_T = (C.LAUNCH_YEAR - 2000) * 1000          # milli-years after J2000

# Kinematics run in finer integer units: distances in micro-light-years (uly),
# speeds in uly per year, acceleration in uly per year squared, times in milli-years.
V = SPEED * 1000                                  # top cruise speed, uly/yr
A = C.PROBE_ACCEL_MLY_PER_YEAR2 * 1000            # acceleration, uly/yr^2
PCT = V // 10                                     # 1% of light speed, uly/yr
MAX_PCT = 10                                      # cruise speeds are 1..MAX_PCT % of c
SURVEY_STOPS = C.SURVEY_STOPS
SURVEY_T = C.SURVEY_YEARS * 1000                  # milli-years at each stop, plus...
SURVEY_T_PER_PLANET = C.SURVEY_YEARS_PER_PLANET * 1000   # ...this per known planet


def survey_t(star_id) -> int:
    """Milli-years the probe spends surveying a stop: longer for systems with known planets."""
    return SURVEY_T + SURVEY_T_PER_PLANET * CATALOG[star_id]["planets"]
DV_BUDGET = C.DV_BUDGET_PCT_C * PCT               # uly/yr of total speed change


def pos(star_id, t=0):
    """Star position (mly) at time t (milli-years after J2000)."""
    s = CATALOG[star_id]
    return (s["x"] + s["vx"] * t // 1_000_000,
            s["y"] + s["vy"] * t // 1_000_000,
            s["z"] + s["vz"] * t // 1_000_000)


def distance(a, b) -> int:
    """Exact integer distance in milli-light-years (floor of the true distance)."""
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def distance_uly(a, b) -> int:
    """Distance between mly positions, in micro-light-years (floor)."""
    return math.isqrt(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) * 1_000_000)


def leg(d, u, c, stop):
    """
    One leg of d uly, starting at speed u, cruising at c (uly/yr).
    Returns (milli-years, end speed, delta-v used).

    The probe speeds up or slows down at A towards c. For a flyby it keeps
    whatever speed it has reached; for a stop it brakes at A to arrive at rest.
    If it is too fast to stop in time, it brakes, overshoots, and comes back.
    """
    if not stop:
        if u <= c:
            ramp = (c * c - u * u) // (2 * A)
            if d >= ramp:
                return (c - u) * 1000 // A + (d - ramp) * 1000 // c, c, c - u
            w = math.isqrt(u * u + 2 * A * d)
            return (w - u) * 1000 // A, w, w - u
        ramp = (u * u - c * c) // (2 * A)
        if d >= ramp:
            return (u - c) * 1000 // A + (d - ramp) * 1000 // c, c, u - c
        w = math.isqrt(u * u - 2 * A * d)
        return (u - w) * 1000 // A, w, u - w
    brake = u * u // (2 * A)                                    # distance to stop from u
    if brake >= d:                                              # overshoot, then rest-to-rest back
        e = brake - d
        return u * 1000 // A + 2 * math.isqrt(e * 1_000_000 // A), 0, u + 2 * math.isqrt(A * e)
    if u > c:                                                   # slow to c, cruise, brake
        return (u - c) * 1000 // A + c * 1000 // A + (d - brake) * 1000 // c, 0, u
    up, down = (c * c - u * u) // (2 * A), c * c // (2 * A)
    if up + down <= d:                                          # reaches cruise speed
        return (c - u) * 1000 // A + c * 1000 // A + (d - up - down) * 1000 // c, 0, 2 * c - u
    p = math.isqrt((2 * A * d + u * u) // 2)                    # peak speed short of c
    return (p - u) * 1000 // A + p * 1000 // A, 0, 2 * p - u


def intercept(here, t, star_id, u=0, c=V, stop=False):
    """(arrival time, arrival place, speed there, delta-v) for a probe at `here` at time t, speed u,
    cruising at c towards a moving star."""
    arrive, speed, dv = t, u, 0
    for _ in range(INTERCEPT_ITERATIONS):
        dt, speed, dv = leg(distance_uly(here, pos(star_id, arrive)), u, c, stop)
        arrive = t + dt
    return arrive, pos(star_id, arrive), speed, dv


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


def stops(prev_hash: str) -> list:
    """The block's survey stars: SURVEY_STOPS of its problem stars where the probe must come to rest.
    Stars with known planets are likelier picks (weight 1 + STOP_WEIGHT_PER_PLANET x planets)."""
    pool = problem(prev_hash)
    chosen = []
    seed = bytes.fromhex(prev_hash)
    i = 0
    while len(chosen) < SURVEY_STOPS:
        weights = [1 + C.STOP_WEIGHT_PER_PLANET * CATALOG[s]["planets"] for s in pool]
        r = int.from_bytes(hashlib.sha256(seed + b"stops" + i.to_bytes(4, "big")).digest(), "big") % sum(weights)
        k = 0
        while r >= weights[k]:
            r -= weights[k]
            k += 1
        chosen.append(pool.pop(k))
        i += 1
    return sorted(chosen)


def check_plan(plan) -> bool:
    """A route plan is a list of [star id, cruise speed in % of c] pairs."""
    return isinstance(plan, list) and all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in p)
        and 1 <= p[1] <= MAX_PCT for p in plan)


def route_legs(plan, stop_ids=()):
    """[(star, arrival time, arrival position, speed there, delta-v, departure time)] for a probe
    launched from rest at the Sun, flying plan = [[star, cruise %c], ...]."""
    stop_set = set(stop_ids)
    here, t, u, legs = SOL, LAUNCH_T, 0, []
    for sid, pct in plan:
        stop = sid in stop_set
        arrive, here, u, dv = intercept(here, t, sid, u, pct * PCT, stop)
        t = arrive + survey_t(sid) if stop else arrive
        if stop:
            here = pos(sid, t)                                  # it rides along with the star while surveying
        legs.append((sid, arrive, here, u, dv, t))
    return legs


def route_time(plan, stop_ids=()) -> int:
    """Mission time in milli-years: launch until the last star is done (surveys included)."""
    legs = route_legs(plan, stop_ids)
    return (legs[-1][5] if legs else LAUNCH_T) - LAUNCH_T


def route_dv(plan, stop_ids=()) -> int:
    """Total speed change (uly/yr): the fuel the mission burns."""
    return sum(l[4] for l in route_legs(plan, stop_ids))


def route_length(plan, stop_ids=()) -> int:
    """Distance flown in mly (for display)."""
    total, prev = 0, SOL
    for sid, arrive, depart_at, _, _, _ in route_legs(plan, stop_ids):
        total += distance(prev, pos(sid, arrive))
        prev = depart_at
    return total


def mass_ratio(dv) -> float:
    """Rocket equation: launch mass / dry mass for a delta-v (display only)."""
    return math.exp(dv / (C.EXHAUST_PCT_C * PCT))


def _greedy(stars, stop_set, c):
    left = sorted(stars)
    here, t, u, route = SOL, LAUNCH_T, 0, []
    while left:
        best = min(left, key=lambda s: (intercept(here, t, s, u, c, s in stop_set)[0], s))
        left.remove(best)
        t, here, u, _ = intercept(here, t, best, u, c, best in stop_set)
        if best in stop_set:
            t += survey_t(best)
            here = pos(best, t)
        route.append(best)
    return route


def baseline_route(stars, stop_ids=()) -> list:
    """The bar a miner's plan is scored against: always fly to the star you can reach soonest,
    at the fastest single cruise speed whose fuel fits the budget."""
    stop_set = set(stop_ids)
    for pct in range(MAX_PCT, 0, -1):
        plan = [[s, pct] for s in _greedy(stars, stop_set, pct * PCT)]
        if route_dv(plan, stop_ids) <= DV_BUDGET:
            return plan
    raise RuntimeError("no cruise speed fits the fuel budget")
