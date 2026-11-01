"""Nebulite's useful work: planet-hopping spacecraft trajectories.

Each block asks for a trajectory from Earth to an outer planet, possibly flying
past other planets on the way (gravity assists). A trajectory is a sequence of
planets and the day the spacecraft reaches each one. Its cost combines:

  * departure speed from Earth        (hyperbolic excess, what the rocket must supply)
  * fuel burned at each flyby         (speed mismatch, or turning harder than gravity allows)
  * arrival speed at the target       (what it must shed to stop or orbit)
  * travel time                       (TIME_PENALTY_MPS_PER_YEAR per year of flight)

Model (see ROADMAP.md for what's next):
  * real planet motion: elliptical, inclined orbits from JPL's approximate
    Keplerian elements and their rates (Standish, "Keplerian Elements for
    Approximate Positions of the Major Planets", table 1, valid 1800-2050),
    in 3D ecliptic coordinates
  * each leg between planets solved with Lambert's problem (universal variables, 3D)
  * patched-conic flybys with a minimum safe passing distance

Units: AU, days, km/s. Day numbers count from J2000 (2000-01-01 12:00 TT).
"""
import copy
import datetime
import hashlib
import json
import math
import os
from functools import lru_cache

import numpy as np

AU_KM = 149597870.7                  # IAU 2012 astronomical unit
MU_SUN = 132712440041.279419 * 86400.0 ** 2 / AU_KM ** 3   # AU^3 / day^2 (JPL DE440 GM of the Sun)
AU_PER_DAY_TO_KMS = AU_KM / 86400.0           # km/s per AU/day
TIME_PENALTY_MPS_PER_YEAR = 250      # default: 1 year of travel costs as much as 250 m/s of fuel
MIN_LEG_DAYS = 20
FLYBY_SAFETY = 1.1                   # closest approach: 1.1 planet radii
MIN_FLYBY_VINF = 1.0                 # km/s: slower than this isn't a gravity assist
LAMBERT_ITERATIONS = 80
MIN_PERIHELION_AU = 0.3              # don't let trajectories dive inside Mercury's orbit
KEPLER_ITERATIONS = 12

# Planet positions come from the full VSOP87A theory (see VSOP87 below). Each planet also has:
#   name, short code, GM (km^3/s^2, JPL DE440), mean radius (km), and JPL's approximate mean
#   elements at J2000 with rates per century (a, e, I, L, perihelion, node), which are used only
#   for rough sizes (Hohmann transfer times, drawing a whole orbit), never for positions.
PLANETS = [
    ("Mercury", "Me", 22031.868551, 2440.0,
     (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
     (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081)),
    ("Venus", "V", 324858.592, 6052.0,
     (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
     (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    ("Earth", "E", 398600.435507, 6371.0,
     (1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
     (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    ("Mars", "Ma", 42828.375816, 3390.0,
     (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
     (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    ("Jupiter", "J", 126712764.1, 69911.0,
     (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
     (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    ("Saturn", "S", 37940584.8418, 58232.0,
     (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
     (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
    ("Uranus", "U", 5794556.4, 25362.0,
     (19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503),
     (-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589)),
    ("Neptune", "N", 6836527.10058, 24622.0,
     (30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574),
     (0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664)),
]
EARTH = 2
TARGETS = [4, 5, 6, 7]                      # Jupiter, Saturn, Uranus, Neptune
MAX_TOF_YEARS = {4: 8, 5: 12, 6: 20, 7: 30}
MAX_FLYBYS = 3
WINDOW_DAYS = 1461                          # 4-year launch window
WINDOW_START_MIN = 9131                     # ~2025-01-01
WINDOW_START_SPREAD = 3650                  # windows start somewhere in 2025-2035

# Mission types: how much a year of travel is worth in fuel, and the share of the
# target's maximum flight time allowed. Picked per block from the hash, from this
# list (science appears twice, so half of all missions are science missions).
MISSION_TYPES = {
    "science": {"time_penalty_mps_per_year": 250, "tof_share": 1.0,
                "about": "robotic probe: fuel and time both matter"},
    "cargo": {"time_penalty_mps_per_year": 50, "tof_share": 1.0,
              "about": "supplies: slow is fine, fuel is everything"},
    "crewed": {"time_penalty_mps_per_year": 3000, "tof_share": 0.5,
               "about": "people aboard: every year costs dearly, and trips must be short"},
}
MISSION_DRAW = ["science", "science", "cargo", "crewed"]
# Which kind of mission a block gets (from its hash), out of 8: "planet" then draws from MISSION_DRAW.
KIND_DRAW = ["escape", "escape", "heliopause", "intercept", "planet", "planet", "planet", "planet"]
ESCAPE_ABOUT = "interstellar departure: leave the solar system pointed at a Pulsarite star, as fast as possible"
J2000 = datetime.datetime(2000, 1, 1, 12)        # day 0 of the mission calendar (J2000 epoch, noon)


def date_of(day: float) -> str:
    """Calendar date (YYYY-MM-DD) for a mission day number (days since J2000)."""
    return (J2000 + datetime.timedelta(days=day)).date().isoformat()


def elements(pid: int, day: float):
    """Approximate mean elements at `day` (for rough sizes only): a, e, I, L, perihelion, node."""
    t = day / 36525.0
    e0, rate = PLANETS[pid][4], PLANETS[pid][5]
    return tuple(e0[i] + rate[i] * t for i in range(6))


# ---- VSOP87A: the planets' real positions ------------------------------
#
# The full VSOP87A series (Bretagnon & Francou 1988): heliocentric rectangular
# coordinates in the J2000 ecliptic frame, 39,198 terms for the eight planets
# (Earth itself, not the Earth-Moon barycentre). Accurate to about 1 arcsecond
# against JPL's numerical ephemerides for thousands of years around 2000, so it
# covers every mission window and arrival this coin uses. Nothing is truncated.
# Velocities are the series' exact time derivatives.

VSOP87_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vsop87a.txt")


def _load_vsop87():
    raw = open(VSOP87_FILE, "rb").read()
    rows = [line.split() for line in raw.decode().splitlines() if line and not line.startswith("#")]
    out = []
    for pid in range(8):
        r = [x for x in rows if int(x[0]) == pid]
        out.append({"coord": np.array([int(x[1]) for x in r]), "power": np.array([int(x[2]) for x in r]),
                    "A": np.array([float(x[3]) for x in r]), "B": np.array([float(x[4]) for x in r]),
                    "C": np.array([float(x[5]) for x in r])})
    return out, hashlib.sha256(raw).hexdigest()[:16]


VSOP87, EPHEMERIS_ID = _load_vsop87()
EPHEMERIS = "VSOP87A full series (Bretagnon & Francou 1988)"


@lru_cache(maxsize=400_000)
def planet_state(pid: int, day: float):
    """Heliocentric ecliptic J2000 position (AU) and velocity (AU/day) on `day` (days since J2000, TDB)."""
    v = VSOP87[pid]
    t = day / 365250.0                                   # Julian millennia
    ph = v["B"] + v["C"] * t
    cs, sn = np.cos(ph), np.sin(ph)
    tp = t ** v["power"]
    dtp = np.where(v["power"] > 0, v["power"] * t ** np.maximum(v["power"] - 1, 0), 0.0)
    pos = np.bincount(v["coord"], weights=v["A"] * cs * tp, minlength=3)
    vel = np.bincount(v["coord"], weights=v["A"] * (cs * dtp - sn * v["C"] * tp), minlength=3) / 365250.0
    return (float(pos[0]), float(pos[1]), float(pos[2])), (float(vel[0]), float(vel[1]), float(vel[2]))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _stumpff(psi):
    if psi > 1e-6:
        s = math.sqrt(psi)
        return (1 - math.cos(s)) / psi, (s - math.sin(s)) / (s ** 3)
    if psi < -1e-6:
        s = math.sqrt(-psi)
        return (1 - math.cosh(s)) / psi, (math.sinh(s) - s) / (s ** 3)
    return 0.5, 1.0 / 6.0


def lambert(r1, r2, tof, min_perihelion=MIN_PERIHELION_AU):
    """Prograde (relative to the ecliptic), zero-revolution Lambert solver in 3D.

    Returns (v1, v2) in AU/day, or None if there's no acceptable solution.
    """
    r1n, r2n = _norm(r1), _norm(r2)
    cos_dnu = max(-1.0, min(1.0, _dot(r1, r2) / (r1n * r2n)))
    dnu = math.acos(cos_dnu)
    if _cross(r1, r2)[2] < 0:
        dnu = 2 * math.pi - dnu
    if abs(1 - cos_dnu) < 1e-12:
        return None
    A = math.sin(dnu) * math.sqrt(r1n * r2n / (1 - cos_dnu))
    if abs(A) < 1e-12:
        return None
    lo, hi = -400.0, 4 * math.pi ** 2   # psi < 0: hyperbolic, > 0: elliptic (one revolution max)
    psi = 0.0
    for _ in range(LAMBERT_ITERATIONS):
        c2, c3 = _stumpff(psi)
        if c2 <= 0:                       # at the one-revolution limit: psi is too large
            hi = psi
            psi = (lo + hi) / 2
            continue
        y = r1n + r2n + A * (psi * c3 - 1) / math.sqrt(c2)
        if A > 0 and y < 0:
            lo = psi                      # too small: move psi up
            psi = (lo + hi) / 2
            continue
        if y <= 0:                        # long-way transfer past its limit: psi is too large
            hi = psi
            psi = (lo + hi) / 2
            continue
        chi = math.sqrt(y / c2)
        dt = (chi ** 3 * c3 + A * math.sqrt(y)) / math.sqrt(MU_SUN)
        if dt <= tof:
            lo = psi
        else:
            hi = psi
        psi = (lo + hi) / 2
    c2, c3 = _stumpff(psi)
    if c2 <= 0:
        return None
    y = r1n + r2n + A * (psi * c3 - 1) / math.sqrt(c2)
    if y <= 0:
        return None
    # Refuse transfers outside the solver's range instead of returning a wrong answer.
    chi = math.sqrt(y / c2)
    if abs((chi ** 3 * c3 + A * math.sqrt(y)) / math.sqrt(MU_SUN) - tof) > 1e-6 * tof:
        return None
    f = 1 - y / r1n
    g = A * math.sqrt(y / MU_SUN)
    gdot = 1 - y / r2n
    v1 = tuple((r2[k] - f * r1[k]) / g for k in range(3))
    v2 = tuple((gdot * r2[k] - r1[k]) / g for k in range(3))
    # Refuse paths that would dive too close to the Sun (perihelion < MIN_PERIHELION_AU).
    h2 = _dot(_cross(r1, v1), _cross(r1, v1))
    energy = _dot(v1, v1) / 2 - MU_SUN / r1n
    ecc = math.sqrt(max(0.0, 1 + 2 * energy * h2 / MU_SUN ** 2))
    if h2 / MU_SUN / (1 + ecc) < min_perihelion:
        return None
    return v1, v2


FLYBY_RP_ITERATIONS = 60


def flyby_dv(pid, vin, vout):
    """Fuel (km/s) for a flyby, given the speeds relative to the planet before and after (km/s).

    The standard powered swing-by: the incoming and outgoing hyperbolas share one closest
    approach, and any change of speed is an engine burn made there, deep in the planet's gravity
    well, where it is most effective (the Oberth effect). The closest approach is chosen so the
    two hyperbolas turn the path by the required angle, but never lower than FLYBY_SAFETY planet
    radii; if even that can't turn far enough, the rest of the turn costs extra fuel.
    """
    mu, radius = PLANETS[pid][2], PLANETS[pid][3]
    a, b = _norm(vin), _norm(vout)
    if a < 1e-9 or b < 1e-9:
        return abs(b - a)                      # no relative speed: nothing to turn
    turn = math.acos(max(-1.0, min(1.0, _dot(vin, vout) / (a * b))))
    rp_min = FLYBY_SAFETY * radius

    def max_turn(rp):
        return math.asin(1 / (1 + rp * a * a / mu)) + math.asin(1 / (1 + rp * b * b / mu))
    if turn > max_turn(rp_min):
        rp, extra = rp_min, turn - max_turn(rp_min)
    else:
        lo, hi = rp_min, 1e12                  # max_turn falls as the flyby gets wider
        for _ in range(FLYBY_RP_ITERATIONS):
            mid = math.sqrt(lo * hi)
            if max_turn(mid) > turn:
                lo = mid
            else:
                hi = mid
        rp, extra = math.sqrt(lo * hi), 0.0
    burn = abs(math.sqrt(b * b + 2 * mu / rp) - math.sqrt(a * a + 2 * mu / rp))
    if extra > 0:
        vavg = (a + b) / 2
        burn += 2 * vavg * math.sin(extra / 2)
    return burn


def body_state(prob, pid, day):
    """Position and velocity of a planet, or of the block's interstellar object (ISO)."""
    if pid == ISO:
        return iso_state(prob["iso"], day)
    return planet_state(pid, day)


def evaluate(seq, days, time_penalty=TIME_PENALTY_MPS_PER_YEAR, prob=None):
    """Cost breakdown of a trajectory, or None if impossible.

    seq:  planet ids, Earth first, target last, flybys in between
    days: arrival day at each planet (days[0] = launch)
    prob: the mission (needed for interstellar-object intercepts, whose target isn't a planet)
    """
    if len(seq) != len(days) or len(seq) < 2:
        return None
    states = [body_state(prob, p, d) for p, d in zip(seq, days)]
    legs = []
    for i in range(len(seq) - 1):
        tof = days[i + 1] - days[i]
        if tof < MIN_LEG_DAYS:
            return None
        sol = lambert(states[i][0], states[i + 1][0], tof)
        if sol is None:
            return None
        legs.append(sol)

    k = AU_PER_DAY_TO_KMS
    launch = _norm(_sub(legs[0][0], states[0][1])) * k
    flybys = []
    for i in range(1, len(seq) - 1):
        vp = states[i][1]
        vin = tuple(c * k for c in _sub(legs[i - 1][1], vp))
        vout = tuple(c * k for c in _sub(legs[i][0], vp))
        if _norm(vin) < MIN_FLYBY_VINF:
            return None
        flybys.append(flyby_dv(seq[i], vin, vout))
    arrival = _norm(_sub(legs[-1][1], states[-1][1])) * k
    years = (days[-1] - days[0]) / 365.25
    # An intercept doesn't brake at the target, it flies through: the encounter speed only
    # counts at ARRIVAL_WEIGHT (a slower pass gives a longer, sharper look, as for Comet Interceptor).
    weight = prob.get("arrival_weight", 1.0) if prob else 1.0
    dv = launch + sum(flybys) + weight * arrival
    return {
        "launch_kms": launch, "flyby_kms": flybys, "arrival_kms": arrival,
        "dv_kms": dv, "years": years,
        "cost": dv * 1000 + time_penalty * years,   # m/s-equivalent
    }


def planets_json():
    """Planet data as sent to miners (the phone computes the same orbits)."""
    keys = ("a", "e", "i", "l", "peri", "node")
    return [{"id": n, "name": p[0], "code": p[1], "gm": p[2], "radius_km": p[3],
             "elements": dict(zip(keys, p[4])), "rates": dict(zip(keys, p[5]))}
            for n, p in enumerate(PLANETS)]


def physics_json():
    return {"mu_sun": MU_SUN, "au_per_day_to_kms": AU_PER_DAY_TO_KMS,
            "time_penalty_mps_per_year": TIME_PENALTY_MPS_PER_YEAR, "min_leg_days": MIN_LEG_DAYS,
            "flyby_safety": FLYBY_SAFETY, "min_flyby_vinf": MIN_FLYBY_VINF,
            "min_perihelion_au": MIN_PERIHELION_AU, "kepler_iterations": KEPLER_ITERATIONS,
            "hyperbola_iterations": HYPERBOLA_ITERATIONS,
            "ephemeris": EPHEMERIS, "ephemeris_id": EPHEMERIS_ID}


# ---- per-block problems -------------------------------------------------

def problem(prev_hash: str) -> dict:
    """This block's mission, chosen unpredictably from the previous block's hash."""
    return copy.deepcopy(_problem(prev_hash))


@lru_cache(maxsize=256)
def _problem(prev_hash: str) -> dict:
    h = int.from_bytes(hashlib.sha256(bytes.fromhex(prev_hash) + b"mission").digest(), "big")
    target = TARGETS[h % len(TARGETS)]
    start = WINDOW_START_MIN + (h >> 8) % WINDOW_START_SPREAD
    # Out of every 8 blocks: 2 escapes toward a Pulsarite star, 1 heliopause mission, 1 interstellar-object
    # intercept, 4 planet missions. A special mission is used only if a path is known to exist (the
    # baseline search finds one), so every block can always be mined; otherwise it's a planet mission.
    kind = KIND_DRAW[_hash_int(prev_hash, b"kind") % len(KIND_DRAW)]
    special = None
    if kind == "escape":
        special = escape_problem(prev_hash, start)
    elif kind == "heliopause":
        special = heliopause_problem(prev_hash, start)
    elif kind == "intercept":
        special = intercept_problem(prev_hash, start)
    if special is not None:
        solvable = (_intercept_grid(special) if special["type"] == "intercept" else _escape_grid(special)) is not None
        if solvable:
            return special
    flyby_bodies = [1, 2, 3] + [p for p in (4, 5) if p < target]
    kind = MISSION_DRAW[int.from_bytes(hashlib.sha256(bytes.fromhex(prev_hash) + b"type").digest(), "big")
                        % len(MISSION_DRAW)]
    mt = MISSION_TYPES[kind]
    return {
        "type": kind,
        "time_penalty_mps_per_year": mt["time_penalty_mps_per_year"],
        "target": target,
        "window_start": start,
        "window_end": start + WINDOW_DAYS,
        "max_tof_days": int(MAX_TOF_YEARS[target] * 365.25 * mt["tof_share"]),
        "flyby_bodies": flyby_bodies,
        "max_flybys": MAX_FLYBYS,
    }


def check(prob, seq, days):
    """Validate a trajectory against the mission rules; returns an error string or None."""
    if not (isinstance(seq, list) and isinstance(days, list)):
        return "trajectory needs seq and days lists"
    if any(not isinstance(x, int) or isinstance(x, bool) for x in seq + days):
        return "seq and days must be whole numbers"
    if len(seq) < 2 or len(seq) > prob["max_flybys"] + 2 or len(days) != len(seq):
        return "wrong number of planets"
    if seq[0] != EARTH or seq[-1] != prob["target"]:
        return "must launch from Earth and end at the target"
    if any(p not in prob["flyby_bodies"] for p in seq[1:-1]):
        return "flyby planet not allowed for this mission"
    if not prob["window_start"] <= days[0] <= prob["window_end"]:
        return "launch outside the window"
    if days[-1] - days[0] > prob["max_tof_days"]:
        return "flight too long"
    return None


def hohmann_days(target):
    a = (1 + PLANETS[target][4][0]) / 2
    return math.pi * math.sqrt(a ** 3 / MU_SUN)


@lru_cache(maxsize=64)
def baseline(prev_hash: str) -> dict:
    """Best direct Earth-to-target transfer on a coarse grid: the bar to beat."""
    prob = problem(prev_hash)
    if is_escape(prob):
        return escape_baseline(prev_hash)
    if prob["type"] == "intercept":
        return intercept_baseline(prev_hash)
    t = prob["target"]
    h = hohmann_days(t)
    best = None
    for i in range(49):
        launch = prob["window_start"] + round(i * WINDOW_DAYS / 48)
        for j in range(32):
            tof = round(h * (0.4 + 1.6 * j / 31))
            if tof > prob["max_tof_days"]:
                continue
            ev = evaluate([EARTH, t], [launch, launch + tof], prob["time_penalty_mps_per_year"])
            if ev and (best is None or ev["cost"] < best[0]):
                best = (ev["cost"], [EARTH, t], [launch, launch + tof])
    return {"cost": best[0], "seq": best[1], "days": best[2]}


# ---- interstellar-object intercepts ---------------------------------------
#
# One block in 8 asks for a probe to meet an object passing through the solar system
# from another star, like 1I/'Oumuamua (2017), 2I/Borisov (2019) and 3I/ATLAS (2025).
# They are found only months before their closest approach to the Sun and leave
# for good, so the mission is a fast, launch-on-short-notice flyby, the plan behind
# ESA's Comet Interceptor and the "Project Lyra" studies.
#
# Each block's object follows a hyperbolic orbit drawn from the block hash, within
# the range of the three real ones: speed far from the Sun (v-infinity) 20 to 60 km/s
# ('Oumuamua 26, Borisov 32, ATLAS 58), perihelion 0.3 to 3 AU, arriving from any
# direction in the sky, with its closest approach 300 to 900 days after discovery.
# The probe launches within two years of discovery and must reach the object within
# six years of launch. Cost: launch and flyby burns, plus the encounter speed at
# ARRIVAL_WEIGHT (it's a flyby, not a rendezvous), plus 250 m/s per year of flight.

ISO = 9                                       # pseudo-body: the block's interstellar object
ISO_VINF_KMS = (20.0, 60.0)
ISO_Q_AU = (0.3, 3.0)
ISO_PERI_AFTER_DAYS = (300, 900)              # perihelion this long after discovery (= window start)
INTERCEPT_LAUNCH_AFTER = 60                   # days from discovery to the earliest launch
INTERCEPT_WINDOW_DAYS = 670                   # launch window: 60 to 730 days after discovery
INTERCEPT_MAX_TOF_DAYS = int(6 * 365.25)
INTERCEPT_FLYBY_BODIES = [1, 2, 3, 4]         # Venus, Earth, Mars, Jupiter
INTERCEPT_ARRIVAL_WEIGHT = 0.1                # 1 km/s of encounter speed costs as much as 100 m/s of fuel
INTERCEPT_TIME_PENALTY = 250
HYPERBOLA_ITERATIONS = 30
INTERCEPT_ABOUT = "interstellar-object intercept: catch a visitor from another star before it leaves forever"


def _unit_draws(prev_hash, tag, n):
    """n numbers in [0, 1) from the block hash, 32 bits each."""
    d = hashlib.sha256(bytes.fromhex(prev_hash) + tag).digest()
    return [int.from_bytes(d[4 * i:4 * i + 4], "big") / 2 ** 32 for i in range(n)]


def intercept_problem(prev_hash, start):
    u = _unit_draws(prev_hash, b"iso", 6)
    vinf = ISO_VINF_KMS[0] + (ISO_VINF_KMS[1] - ISO_VINF_KMS[0]) * u[0]
    q = ISO_Q_AU[0] + (ISO_Q_AU[1] - ISO_Q_AU[0]) * u[1]
    z, lon = 2 * u[2] - 1, 2 * math.pi * u[3]                # direction of travel: uniform over the sky
    xy = math.sqrt(max(0.0, 1 - z * z))
    s_in = (xy * math.cos(lon), xy * math.sin(lon), z)
    # the orbit plane contains s_in; turn it by psi about s_in
    ref = (0.0, 0.0, 1.0) if abs(z) < 0.9 else (1.0, 0.0, 0.0)
    e1 = _unit(_cross(s_in, ref))
    e2 = _cross(s_in, e1)
    psi = 2 * math.pi * u[4]
    n_hat = _add(_scale(e1, math.cos(psi)), _scale(e2, math.sin(psi)))
    vinf_au = vinf / AU_PER_DAY_TO_KMS
    e = 1 + q * vinf_au * vinf_au / MU_SUN
    # perihelion direction p: s_in is p turned by angle alpha about n, with cos(alpha) = 1/e
    ca, sa = 1 / e, math.sqrt(e * e - 1) / e
    p_hat = _sub(_scale(s_in, ca), _scale(_cross(n_hat, s_in), sa))
    q_hat = _cross(n_hat, p_hat)
    t_peri = start + ISO_PERI_AFTER_DAYS[0] + int(u[5] * (ISO_PERI_AFTER_DAYS[1] - ISO_PERI_AFTER_DAYS[0] + 1))
    return {
        "type": "intercept", "time_penalty_mps_per_year": INTERCEPT_TIME_PENALTY, "target": ISO,
        "window_start": start + INTERCEPT_LAUNCH_AFTER,
        "window_end": start + INTERCEPT_LAUNCH_AFTER + INTERCEPT_WINDOW_DAYS,
        "max_tof_days": INTERCEPT_MAX_TOF_DAYS, "flyby_bodies": INTERCEPT_FLYBY_BODIES, "max_flybys": MAX_FLYBYS,
        "arrival_weight": INTERCEPT_ARRIVAL_WEIGHT,
        "iso": {"discovery_day": start, "vinf_kms": vinf, "q_au": q, "e": e, "t_peri": t_peri,
                "p_hat": list(p_hat), "q_hat": list(q_hat), "dir_in": list(s_in)},
    }


def iso_state(iso, day):
    """Position (AU) and velocity (AU/day) of the interstellar object: a Kepler hyperbola about the Sun."""
    e, q = iso["e"], iso["q_au"]
    a = -q / (e - 1)                              # negative for a hyperbola
    n = math.sqrt(MU_SUN / (-a) ** 3)
    m = n * (day - iso["t_peri"])
    f = math.asinh(m / e)
    for _ in range(HYPERBOLA_ITERATIONS):         # Newton on e sinh F - F = M
        f -= (e * math.sinh(f) - f - m) / (e * math.cosh(f) - 1)
    ch, sh = math.cosh(f), math.sinh(f)
    b = -a * math.sqrt(e * e - 1)
    x, y = a * (ch - e), b * sh
    fdot = n / (e * ch - 1)
    vx, vy = a * sh * fdot, b * ch * fdot
    p, qh = iso["p_hat"], iso["q_hat"]
    r = tuple(x * p[i] + y * qh[i] for i in range(3))
    v = tuple(vx * p[i] + vy * qh[i] for i in range(3))
    return r, v


INTERCEPT_GRID_LAUNCHES = 25
INTERCEPT_GRID_TOFS = 32


def _intercept_grid(prob):
    """Best direct Earth-to-object transfer on a coarse grid (the baseline), or None if none works."""
    best = None
    for i in range(INTERCEPT_GRID_LAUNCHES):
        launch = prob["window_start"] + round(i * INTERCEPT_WINDOW_DAYS / (INTERCEPT_GRID_LAUNCHES - 1))
        for j in range(INTERCEPT_GRID_TOFS):
            tof = round(60 + 1740 * j / (INTERCEPT_GRID_TOFS - 1))
            ev = evaluate([EARTH, ISO], [launch, launch + tof], prob["time_penalty_mps_per_year"], prob)
            if ev and (best is None or ev["cost"] < best[0]):
                best = (ev["cost"], [EARTH, ISO], [launch, launch + tof])
    return best


@lru_cache(maxsize=64)
def intercept_baseline(prev_hash: str) -> dict:
    best = _intercept_grid(problem(prev_hash))
    return {"cost": best[0], "seq": best[1], "days": best[2]}


# ---- escape missions: leaving the solar system toward a Pulsarite star ----
#
# Two blocks in 8 (KIND_DRAW) ask for an interstellar departure instead of a planet
# trip: launch from Earth, fly past planets (and optionally dive close to the Sun
# to burn at perihelion, the "solar Oberth" manoeuvre), then leave on a hyperbola
# whose asymptote points exactly at the block's target star from Pulsarite's
# catalog. The score is the time from launch until the craft passes ESCAPE_GOAL_AU
# (550 AU, where the Sun's gravity starts to focus light from the target star into
# a telescope). Pulsarite plans the journey between the stars from there.
#
# A trajectory is seq (planet ids, Earth first; the last entry may be SUN for a
# Sun dive), days (one per planet encounter; a dive's perihelion date follows from
# the physics), and escape = {"vinf_ms": final speed away from the Sun, m/s}, plus
# "rp_mau" (perihelion distance in thousandths of an AU) for a Sun dive.
#
# A Sun dive works like the real "solar Oberth" mission studies: the last flyby
# drops the craft onto an orbit that falls to perihelion rp, where it burns along
# its direction of motion; the infall and escape orbits share one plane (through
# the last planet and the target star), so the escape asymptote points exactly at
# the star. Burning deep in the Sun's gravity well multiplies the burn's effect.

SUN = 8                                       # pseudo-body: a perihelion burn near the Sun
ESCAPE_GOAL_AU = 550
ESCAPE_LAUNCH_VINF_MAX = 17.0                 # km/s: SLS-class with kick stages (C3 ~ 290 km2/s2), as in
                                              # the Johns Hopkins APL Interstellar Probe study
ESCAPE_BURN_BUDGET = 3.0                      # km/s for every burn after launch (flybys + perihelion)
ESCAPE_MIN_PERIHELION_AU = 0.05               # about the Parker Solar Probe's closest approach
ESCAPE_MAX_CRUISE_DAYS = int(20 * 365.25)     # launch until the final escape point
ESCAPE_FLYBY_BODIES = [1, 2, 3, 4, 5]         # Venus, Earth, Mars, Jupiter, Saturn
STAR_TARGETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "star_targets.json")
with open(STAR_TARGETS_FILE) as _f:
    STAR_TARGETS = json.load(_f)
STAR_WEIGHT_PER_PLANET = 3                    # as Pulsarite's survey stops: favour planetary systems
KM_S_PER_AU_YEAR = AU_KM / (365.25 * 86400)  # 1 AU per year = 4.74 km/s


def body_name(p):
    return "Sun" if p == SUN else "Interstellar object" if p == ISO else PLANETS[p][0]


def _hash_int(prev_hash, tag):
    return int.from_bytes(hashlib.sha256(bytes.fromhex(prev_hash) + tag).digest(), "big")


def is_escape(prob) -> bool:
    """Escape-type missions (toward a star, or toward the heliosphere's nose) share one set of physics."""
    return prob["type"] in ("escape", "heliopause")


# The heliosphere's "nose": where the interstellar gas flows in from, ecliptic longitude 255.7 deg,
# latitude 5.1 deg (IBEX, McComas et al. 2015). Both Voyagers crossed the heliopause, the edge of the
# Sun's bubble of solar wind, at about 120 AU (Voyager 1 at 121.6 AU in 2012, Voyager 2 at 119 AU in 2018).
HELIOPAUSE_AU = 120
HELIOPAUSE_ABOUT = "heliopause precursor: reach the edge of the Sun's bubble, 120 AU toward the interstellar wind, as fast as possible"
_NOSE_LON, _NOSE_LAT = math.radians(255.7), math.radians(5.1)
NOSE_DIR = [round(math.cos(_NOSE_LAT) * math.cos(_NOSE_LON), 12), round(math.cos(_NOSE_LAT) * math.sin(_NOSE_LON), 12),
            round(math.sin(_NOSE_LAT), 12)]


def heliopause_problem(prev_hash, start):
    """A heliopause mission: an escape aimed at the heliosphere's nose, scored on reaching 120 AU."""
    p = escape_problem(prev_hash, start)
    p.update(type="heliopause", goal_au=HELIOPAUSE_AU,
             target_star={"id": -1, "name": "Heliosphere nose", "planets": 0, "distance_ly": 0.0, "dir": NOSE_DIR})
    return p


def escape_problem(prev_hash, start):
    """An escape mission: which star to aim at, plus the launch window and limits."""
    stars = STAR_TARGETS["stars"]
    weights = [1 + STAR_WEIGHT_PER_PLANET * st["planets"] for st in stars]
    r = _hash_int(prev_hash, b"star") % sum(weights)
    k = 0
    while r >= weights[k]:
        r -= weights[k]
        k += 1
    st = stars[k]
    return {
        "type": "escape", "time_penalty_mps_per_year": 0, "target": SUN,
        "target_star": {"id": st["id"], "name": st["name"], "planets": st["planets"],
                        "distance_ly": st["distance_ly"], "dir": st["dir"]},
        "window_start": start, "window_end": start + WINDOW_DAYS,
        "max_tof_days": ESCAPE_MAX_CRUISE_DAYS,
        "flyby_bodies": ESCAPE_FLYBY_BODIES, "max_flybys": MAX_FLYBYS,
        "goal_au": ESCAPE_GOAL_AU, "launch_vinf_max_kms": ESCAPE_LAUNCH_VINF_MAX,
        "burn_budget_kms": ESCAPE_BURN_BUDGET, "min_perihelion_au": ESCAPE_MIN_PERIHELION_AU,
        "star_catalog_id": STAR_TARGETS["catalog_id"],
    }


def _scale(a, k):
    return a[0] * k, a[1] * k, a[2] * k


def _unit(a):
    n = _norm(a)
    return a[0] / n, a[1] / n, a[2] / n


def _add(a, b):
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _hyperbola_time(r, e, a, nu, goal):
    """Days from radius r (true anomaly nu) to radius `goal` (outbound) on a hyperbola (a < 0)."""
    if r >= goal:
        return None
    f1 = math.acosh(max(1.0, (1 - r / a) / e))
    if nu < 0:
        f1 = -f1
    f2 = math.acosh((1 - goal / a) / e)
    n = math.sqrt(MU_SUN / (-a) ** 3)
    return ((e * math.sinh(f2) - f2) - (e * math.sinh(f1) - f1)) / n


def escape_from_point(r, s_hat, vinf, long_way=False, goal=ESCAPE_GOAL_AU):
    """The heliocentric velocity (AU/day) needed at position r to leave on a hyperbola whose
    asymptote is s_hat at speed vinf (AU/day), and the days from r to ESCAPE_GOAL_AU.
    Returns (v, days_to_goal) or None if impossible."""
    rn = _norm(r)
    rh = _scale(r, 1 / rn)
    cross = _cross(r, s_hat)
    if _norm(cross) < 1e-9 * rn:
        return None                                   # already pointing straight at the star
    h_hat = _unit(cross)
    theta = math.acos(max(-1.0, min(1.0, _dot(rh, s_hat))))
    if long_way:
        h_hat, theta = _scale(h_hat, -1), 2 * math.pi - theta
    v2 = vinf * vinf

    def f(e):
        nu = math.acos(-1 / e) - theta
        return MU_SUN * (e * e - 1) / v2 - rn * (1 + e * math.cos(nu))
    lo, hi = 1e-12, 1e6                               # e - 1, searched geometrically
    if f(1 + lo) >= 0 or f(1 + hi) <= 0:
        return None
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if f(1 + mid) < 0:
            lo = mid
        else:
            hi = mid
    e = 1 + math.sqrt(lo * hi)
    nu = math.acos(-1 / e) - theta
    if nu <= -math.acos(-1 / e):
        return None
    p = MU_SUN * (e * e - 1) / v2
    if nu < 0 and p / (1 + e) < ESCAPE_MIN_PERIHELION_AU:
        return None                                   # would pass too close to the Sun on the way out
    c = math.sqrt(MU_SUN / p)
    t_hat = _cross(h_hat, rh)
    v = _add(_scale(rh, c * e * math.sin(nu)), _scale(t_hat, c * (1 + e * math.cos(nu))))
    days = _hyperbola_time(rn, e, -MU_SUN / v2, nu, goal)
    return None if days is None else (v, days)


def _time_from_perihelion(q, e, nu):
    """Days from true anomaly nu to perihelion (positive for nu < 0) on a conic with perihelion q."""
    if abs(e - 1) < 1e-9:                                         # parabola (Barker's equation)
        d = math.tan(nu / 2)
        return -math.sqrt(2 * q ** 3 / MU_SUN) * (d + d ** 3 / 3)
    a = q / (1 - e)
    if e < 1:
        ea = 2 * math.atan(math.sqrt((1 - e) / (1 + e)) * math.tan(nu / 2))
        return -(ea - e * math.sin(ea)) / math.sqrt(MU_SUN / a ** 3)
    fa = 2 * math.atanh(math.sqrt((e - 1) / (e + 1)) * math.tan(nu / 2))
    return -(e * math.sinh(fa) - fa) / math.sqrt(MU_SUN / (-a) ** 3)


def sun_dive(r, s_hat, vinf, rp, long_way=False, goal=ESCAPE_GOAL_AU):
    """A Sun dive from position r (AU): the craft falls to perihelion rp, burns along its motion and
    leaves toward s_hat at vinf (AU/day). Returns (velocity needed at r, days to perihelion,
    burn speed in AU/day, days from perihelion to ESCAPE_GOAL_AU), or None if impossible."""
    rn = _norm(r)
    rh = _scale(r, 1 / rn)
    cross = _cross(r, s_hat)
    if _norm(cross) < 1e-9 * rn or rn <= rp:
        return None
    h_hat = _unit(cross)
    theta = math.acos(max(-1.0, min(1.0, _dot(rh, s_hat))))     # sweep from r to the star direction
    if long_way:
        h_hat, theta = _scale(h_hat, -1), 2 * math.pi - theta
    e_out = 1 + rp * vinf * vinf / MU_SUN
    sweep = theta - math.acos(-1 / e_out)                          # r -> perihelion
    if not 0 < sweep < math.pi:
        return None
    nu = -sweep                                                     # r's true anomaly on the infall orbit
    e = (rn - rp) / (rp - rn * math.cos(nu))
    if e < 0 or 1 + e * math.cos(nu) <= 0:
        return None
    pf = rp * (1 + e)
    c = math.sqrt(MU_SUN / pf)
    t_hat = _cross(h_hat, rh)
    v = _add(_scale(rh, c * e * math.sin(nu)), _scale(t_hat, c * (1 + e * math.cos(nu))))
    burn = math.sqrt(vinf * vinf + 2 * MU_SUN / rp) - c * (1 + e)
    fall = _time_from_perihelion(rp, e, nu)
    out = _hyperbola_time(rp, e_out, -MU_SUN / (vinf * vinf), 0.0, goal)
    return None if out is None else (v, fall, abs(burn), out)


def escape_check(prob, seq, days, esc):
    """Validate an escape trajectory's shape against the mission rules; error string or None."""
    if not (isinstance(seq, list) and isinstance(days, list) and isinstance(esc, dict)):
        return "escape trajectory needs seq, days and escape"
    if any(not isinstance(x, int) or isinstance(x, bool) for x in seq + days + list(esc.values())):
        return "seq, days and escape values must be whole numbers"
    if not 1 <= len(seq) <= prob["max_flybys"] + 2:
        return "wrong number of encounters"
    if seq[0] != EARTH:
        return "must launch from Earth"
    if any(p not in prob["flyby_bodies"] for p in seq[1:] if p != SUN) or SUN in seq[:-1]:
        return "flyby planet not allowed (the Sun can only be the last encounter)"
    dive = seq[-1] == SUN and len(seq) > 2
    if seq[-1] == SUN and not dive:
        return "a Sun dive needs a planet flyby first (a launch can't shed enough speed)"
    if len(days) != len(seq) - (1 if dive else 0):
        return "one day per planet encounter"
    if set(esc) != ({"vinf_ms", "rp_mau"} if dive else {"vinf_ms"}):
        return "escape needs vinf_ms" + (" and rp_mau for a Sun dive" if dive else "")
    if not 100 <= esc["vinf_ms"] <= 200_000:
        return "escape speed out of range"
    if dive and not round(ESCAPE_MIN_PERIHELION_AU * 1000) <= esc["rp_mau"] <= 1000:
        return "perihelion out of range"
    if not prob["window_start"] <= days[0] <= prob["window_end"]:
        return "launch outside the window"
    if days[-1] - days[0] > prob["max_tof_days"]:
        return "too long before the final escape"
    return None


def escape_evaluate(prob, seq, days, esc):
    """Score an escape trajectory: dict with "cost" (days from launch to ESCAPE_GOAL_AU), or None."""
    k = AU_PER_DAY_TO_KMS
    s_hat = tuple(prob["target_star"]["dir"])
    vinf = esc["vinf_ms"] / 1000 / k
    dive = seq[-1] == SUN and len(seq) > 2
    planets = seq[:-1] if dive else seq
    states = [planet_state(p, d) for p, d in zip(planets, days)]
    legs = []
    for i in range(len(planets) - 1):
        tof = days[i + 1] - days[i]
        if tof < MIN_LEG_DAYS:
            return None
        sol = lambert(states[i][0], states[i + 1][0], tof, ESCAPE_MIN_PERIHELION_AU)
        if sol is None:
            return None
        legs.append(sol)
    burns = []
    for i in range(1, len(planets) - 1):                            # flybys before the last planet
        vp = states[i][1]
        vin = _scale(_sub(legs[i - 1][1], vp), k)
        vout = _scale(_sub(legs[i][0], vp), k)
        if _norm(vin) < MIN_FLYBY_VINF:
            return None
        burns.append(flyby_dv(planets[i], vin, vout))
    # leave from the last planet (or straight from Earth): try both ways round the Sun, keep the
    # option with the least fuel after launch (for a direct launch: the smallest launch speed)
    best = None
    for long_way in (False, True):
        if dive:
            out = sun_dive(states[-1][0], s_hat, vinf, esc["rp_mau"] / 1000, long_way, prob["goal_au"])
            if out is None:
                continue
            v_need, extra_days, peri_burn, to_goal = out[0], out[1], out[2] * k, out[3]
        else:
            out = escape_from_point(states[-1][0], s_hat, vinf, long_way, prob["goal_au"])
            if out is None:
                continue
            v_need, extra_days, peri_burn, to_goal = out[0], 0.0, 0.0, out[1]
        vp = states[-1][1]
        if len(planets) == 1:
            launch_v, last = v_need, []
            key = _norm(_sub(v_need, vp))
        else:
            vin = _scale(_sub(legs[-1][1], vp), k)
            if _norm(vin) < MIN_FLYBY_VINF:
                continue
            launch_v = legs[0][0]
            last = [flyby_dv(planets[-1], vin, _scale(_sub(v_need, vp), k))] + ([peri_burn] if dive else [])
            key = sum(last)
        if best is None or key < best[0]:
            best = (key, launch_v, last, extra_days, to_goal)
    if best is None:
        return None
    _, launch_v, last, extra_days, to_goal = best
    burns += last
    launch = _norm(_sub(launch_v, states[0][1])) * k
    if launch > prob["launch_vinf_max_kms"] or sum(burns) > prob["burn_budget_kms"]:
        return None
    total = days[-1] - days[0] + extra_days + to_goal
    vinf_kms = esc["vinf_ms"] / 1000
    return {"cost": total, "launch_kms": launch, "burn_kms": burns, "burns_total_kms": sum(burns),
            "vinf_kms": vinf_kms, "au_per_year": vinf_kms / KM_S_PER_AU_YEAR, "years": total / 365.25,
            "perihelion_day": days[-1] + extra_days if dive else None,
            "years_to_star": prob["target_star"]["distance_ly"] * 63241.077 / (vinf_kms / KM_S_PER_AU_YEAR)}


def _max_vinf(prob, seq, days, extra, lo=1000, hi=80_000):
    """Fastest escape speed (whole m/s) that still meets the launch and fuel limits, by bisection."""
    if escape_evaluate(prob, seq, days, dict(extra, vinf_ms=lo)) is None:
        return None
    for _ in range(17):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        if escape_evaluate(prob, seq, days, dict(extra, vinf_ms=mid)) is None:
            hi = mid
        else:
            lo = mid
    return lo


def _escape_grid(prob):
    """The best of three textbook strategies on a coarse grid, each at the fastest escape speed
    its launch and fuel allow: a direct launch, a Jupiter flyby, and a Jupiter flyby that drops
    the craft into a Sun dive (perihelion 0.05 or 0.1 AU). (cost, seq, days, escape) or None."""
    ws = prob["window_start"]
    hj = hohmann_days(4)
    rp = round(ESCAPE_MIN_PERIHELION_AU * 1000)
    best = None

    def consider(seq, days, extra):
        nonlocal best
        v = _max_vinf(prob, seq, days, extra)
        if v is None:
            return
        esc = dict(extra, vinf_ms=v)
        ev = escape_evaluate(prob, seq, days, esc)
        if ev and (best is None or ev["cost"] < best[0]):
            best = (ev["cost"], seq, days, esc)
    for i in range(13):
        launch = ws + round(i * WINDOW_DAYS / 12)
        consider([EARTH], [launch], {})
    for i in range(13):
        launch = ws + round(i * WINDOW_DAYS / 12)
        for j in range(9):
            dj = launch + round(hj * (0.4 + 0.15 * j))
            consider([EARTH, 4], [launch, dj], {})
            for rpm in (rp, 2 * rp):
                consider([EARTH, 4, SUN], [launch, dj], {"rp_mau": rpm})
    return best


@lru_cache(maxsize=64)
def escape_baseline(prev_hash: str) -> dict:
    """The bar for an escape block (see _escape_grid). Escape blocks always have one."""
    best = _escape_grid(problem(prev_hash))
    return {"cost": best[0], "seq": best[1], "days": best[2], "escape": best[3]}


# ---- drawing helpers (display only, not consensus) ----------------------

def sample_path(seq, days, per_leg=40, prob=None):
    """Points (AU) along a trajectory: each leg's Lambert arc integrated with RK4."""
    def deriv(st):
        r = math.sqrt(st[0] ** 2 + st[1] ** 2 + st[2] ** 2)
        k = -MU_SUN / r ** 3
        return [st[3], st[4], st[5], k * st[0], k * st[1], k * st[2]]

    def rk4(st, h):
        k1 = deriv(st)
        k2 = deriv([a + h / 2 * b for a, b in zip(st, k1)])
        k3 = deriv([a + h / 2 * b for a, b in zip(st, k2)])
        k4 = deriv([a + h * b for a, b in zip(st, k3)])
        return [a + h / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(st, k1, k2, k3, k4)]

    out = []
    for i in range(len(seq) - 1):
        r1, r2 = body_state(prob, seq[i], days[i])[0], body_state(prob, seq[i + 1], days[i + 1])[0]
        tof = days[i + 1] - days[i]
        sol = lambert(r1, r2, tof)
        if sol is None:
            continue
        st = list(r1) + list(sol[0])
        h = tof / (per_leg * 10)
        out.append(st[:3])
        for _ in range(per_leg):
            for _ in range(10):
                st = rk4(st, h)
            out.append(st[:3])
    return out


def iso_path(prob, out_to_au=12.0, n=160):
    """Points (AU) along the interstellar object's hyperbola, out to `out_to_au` on either side."""
    iso = prob["iso"]
    e, q = iso["e"], iso["q_au"]
    nu_max = math.acos(min(1.0, (q * (1 + e) / out_to_au - 1) / e))
    out = []
    for i in range(n + 1):
        nu = -nu_max + 2 * nu_max * i / n
        r = q * (1 + e) / (1 + e * math.cos(nu))
        out.append([r * (math.cos(nu) * iso["p_hat"][k] + math.sin(nu) * iso["q_hat"][k]) for k in range(3)])
    return out


def mission_about(prob):
    t = prob["type"]
    if t == "escape":
        return ESCAPE_ABOUT
    if t == "heliopause":
        return HELIOPAUSE_ABOUT
    if t == "intercept":
        return INTERCEPT_ABOUT
    return MISSION_TYPES[t]["about"]


def orbit_points(pid, day, n=96):
    """One full orbit of a planet (AU), sampled around `day`."""
    period = 365.25 * PLANETS[pid][4][0] ** 1.5
    return [list(planet_state(pid, day + period * k / n)[0]) for k in range(n + 1)]


def escape_path(prob, seq, days, esc, out_to_au=40.0, per_leg=40):
    """Points (AU) along an escape trajectory for drawing: the planet legs, then the departure
    (through the Sun dive and its burn, if any) out to `out_to_au`."""
    k = AU_PER_DAY_TO_KMS
    s_hat = tuple(prob["target_star"]["dir"])
    vinf = esc["vinf_ms"] / 1000 / k
    dive = seq[-1] == SUN and len(seq) > 2
    planets = seq[:-1] if dive else seq
    pts = sample_path(planets, days, per_leg) if len(planets) > 1 else []
    r = planet_state(planets[-1], days[-1])[0]
    best = None
    for long_way in (False, True):                 # the same choice escape_evaluate makes
        out = (sun_dive(r, s_hat, vinf, esc["rp_mau"] / 1000, long_way, prob["goal_au"]) if dive
               else escape_from_point(r, s_hat, vinf, long_way, prob["goal_au"]))
        if out is None:
            continue
        vp = planet_state(planets[-1], days[-1])[1]
        key = _norm(_sub(out[0], vp))
        if best is None or key < best[0]:
            best = (key, out)
    if best is None:
        return pts
    out = best[1]
    st = list(r) + list(out[0])
    burned = not dive
    v_after = math.sqrt(vinf * vinf + 2 * MU_SUN / (esc["rp_mau"] / 1000)) if dive else 0.0

    def acc(x):
        d = math.sqrt(x[0] ** 2 + x[1] ** 2 + x[2] ** 2) ** 3
        return [x[3], x[4], x[5], -MU_SUN * x[0] / d, -MU_SUN * x[1] / d, -MU_SUN * x[2] / d]
    pts.append(st[:3])
    t, nxt = 0.0, 0.0
    for _ in range(200_000):
        rn = math.sqrt(st[0] ** 2 + st[1] ** 2 + st[2] ** 2)
        if rn > out_to_au:
            break
        h = 0.02 * rn ** 1.5 / math.sqrt(MU_SUN)   # small steps near the Sun
        if not burned and t + h >= out[1]:
            h = max(out[1] - t, 1e-9)
        k1 = acc(st); k2 = acc([a + h / 2 * b for a, b in zip(st, k1)])
        k3 = acc([a + h / 2 * b for a, b in zip(st, k2)]); k4 = acc([a + h * b for a, b in zip(st, k3)])
        st = [a + h / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(st, k1, k2, k3, k4)]
        t += h
        if not burned and t >= out[1] - 1e-9:      # perihelion: burn along the direction of motion
            sp = math.sqrt(st[3] ** 2 + st[4] ** 2 + st[5] ** 2)
            st = st[:3] + [c * v_after / sp for c in st[3:]]
            burned = True
        if t >= nxt:
            pts.append(st[:3])
            nxt = t + 0.004 * rn ** 1.5 / math.sqrt(MU_SUN) * 25
    pts.append(st[:3])
    return pts
