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
import datetime
import hashlib
import math
from functools import lru_cache

MU_SUN = 2.959122082855911e-4        # AU^3 / day^2
AU_PER_DAY_TO_KMS = 1731.45683681
TIME_PENALTY_MPS_PER_YEAR = 250      # default: 1 year of travel costs as much as 250 m/s of fuel
MIN_LEG_DAYS = 20
FLYBY_SAFETY = 1.1                   # closest approach: 1.1 planet radii
MIN_FLYBY_VINF = 1.0                 # km/s: slower than this isn't a gravity assist
LAMBERT_ITERATIONS = 80
MIN_PERIHELION_AU = 0.3              # don't let trajectories dive inside Mercury's orbit
KEPLER_ITERATIONS = 12

# JPL approximate elements at J2000 and rates per Julian century (table 1, 1800-2050):
#   a (AU), e, I (deg), L mean longitude (deg), long. of perihelion (deg), long. of ascending node (deg)
# plus name, short code, GM (km^3/s^2), radius (km). "Earth" is the Earth-Moon barycentre.
PLANETS = [
    ("Mercury", "Me", 22032.0, 2440.0,
     (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
     (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081)),
    ("Venus", "V", 324859.0, 6052.0,
     (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
     (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    ("Earth", "E", 398600.0, 6371.0,
     (1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
     (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    ("Mars", "Ma", 42828.0, 3390.0,
     (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
     (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    ("Jupiter", "J", 126686534.0, 69911.0,
     (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
     (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    ("Saturn", "S", 37931187.0, 58232.0,
     (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
     (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
    ("Uranus", "U", 5793939.0, 25362.0,
     (19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503),
     (-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589)),
    ("Neptune", "N", 6836529.0, 24622.0,
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
J2000 = datetime.datetime(2000, 1, 1, 12)        # day 0 of the mission calendar (J2000 epoch, noon)


def date_of(day: float) -> str:
    """Calendar date (YYYY-MM-DD) for a mission day number (days since J2000)."""
    return (J2000 + datetime.timedelta(days=day)).date().isoformat()


def elements(pid: int, day: float):
    """Osculating elements at `day`: a, e, I, L, perihelion longitude, node (degrees)."""
    t = day / 36525.0
    e0, rate = PLANETS[pid][4], PLANETS[pid][5]
    return tuple(e0[i] + rate[i] * t for i in range(6))


def planet_state(pid: int, day: float):
    """Heliocentric ecliptic position (AU) and velocity (AU/day), J2000 frame."""
    a, e, inc, L, peri, node = elements(pid, day)
    M = math.radians((L - peri) % 360.0)
    w = math.radians(peri - node)
    O = math.radians(node)
    i = math.radians(inc)
    E = M + e * math.sin(M)
    for _ in range(KEPLER_ITERATIONS):                 # Newton's method on Kepler's equation
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    cE, sE = math.cos(E), math.sin(E)
    b = math.sqrt(1 - e * e)
    xp, yp = a * (cE - e), a * b * sE
    edot = math.sqrt(MU_SUN / a ** 3) / (1 - e * cE)
    vxp, vyp = -a * sE * edot, a * b * cE * edot
    cw, sw, cO, sO, ci, si = math.cos(w), math.sin(w), math.cos(O), math.sin(O), math.cos(i), math.sin(i)
    r11, r12 = cw * cO - sw * sO * ci, -sw * cO - cw * sO * ci
    r21, r22 = cw * sO + sw * cO * ci, -sw * sO + cw * cO * ci
    r31, r32 = sw * si, cw * si
    return ((r11 * xp + r12 * yp, r21 * xp + r22 * yp, r31 * xp + r32 * yp),
            (r11 * vxp + r12 * vyp, r21 * vxp + r22 * vyp, r31 * vxp + r32 * vyp))


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


def lambert(r1, r2, tof):
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
        y = r1n + r2n + A * (psi * c3 - 1) / math.sqrt(c2)
        if A > 0 and y < 0:
            lo = psi                      # too small: move psi up
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
    if h2 / MU_SUN / (1 + ecc) < MIN_PERIHELION_AU:
        return None
    return v1, v2


def flyby_dv(pid, vin, vout):
    """Fuel (km/s) for a flyby given incoming/outgoing speeds relative to the planet (km/s)."""
    mu, radius = PLANETS[pid][2], PLANETS[pid][3]
    a, b = _norm(vin), _norm(vout)
    dv = abs(b - a)
    vavg = (a + b) / 2
    if a < 1e-9 or b < 1e-9:
        return dv                          # no relative speed: nothing to turn
    turn = math.acos(max(-1.0, min(1.0, _dot(vin, vout) / (a * b))))
    max_turn = 2 * math.asin(1 / (1 + FLYBY_SAFETY * radius * vavg ** 2 / mu))
    if turn > max_turn:
        dv += 2 * vavg * math.sin((turn - max_turn) / 2)
    return dv


def evaluate(seq, days, time_penalty=TIME_PENALTY_MPS_PER_YEAR):
    """Cost breakdown of a trajectory, or None if impossible.

    seq:  planet ids, Earth first, target last, flybys in between
    days: arrival day at each planet (days[0] = launch)
    """
    if len(seq) != len(days) or len(seq) < 2:
        return None
    states = [planet_state(p, d) for p, d in zip(seq, days)]
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
    dv = launch + sum(flybys) + arrival
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
            "min_perihelion_au": MIN_PERIHELION_AU, "kepler_iterations": KEPLER_ITERATIONS}


# ---- per-block problems -------------------------------------------------

def problem(prev_hash: str) -> dict:
    """This block's mission, chosen unpredictably from the previous block's hash."""
    h = int.from_bytes(hashlib.sha256(bytes.fromhex(prev_hash) + b"mission").digest(), "big")
    target = TARGETS[h % len(TARGETS)]
    start = WINDOW_START_MIN + (h >> 8) % WINDOW_START_SPREAD
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


# ---- drawing helpers (display only, not consensus) ----------------------

def sample_path(seq, days, per_leg=40):
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
        r1, r2 = planet_state(seq[i], days[i])[0], planet_state(seq[i + 1], days[i + 1])[0]
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


def orbit_points(pid, day, n=96):
    """One full orbit of a planet (AU), sampled around `day`."""
    period = 365.25 * PLANETS[pid][4][0] ** 1.5
    return [list(planet_state(pid, day + period * k / n)[0]) for k in range(n + 1)]
