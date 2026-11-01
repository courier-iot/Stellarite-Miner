"""Nebulite's useful work: planet-hopping spacecraft trajectories.

Each block asks for a trajectory from Earth to an outer planet, possibly flying
past other planets on the way (gravity assists). A trajectory is a sequence of
planets and the day the spacecraft reaches each one. Its cost combines:

  * departure speed from Earth        (hyperbolic excess, what the rocket must supply)
  * fuel burned at each flyby         (speed mismatch, or turning harder than gravity allows)
  * arrival speed at the target       (what it must shed to stop or orbit)
  * travel time                       (TIME_PENALTY_MPS_PER_YEAR per year of flight)

Model (good enough for a prototype, see ROADMAP.md for what's next):
  * planets on circular, coplanar orbits with real sizes and J2000 positions
  * each leg between planets solved with Lambert's problem (universal variables)
  * patched-conic flybys with a minimum safe passing distance

Units: AU, days, km/s. Day numbers count from J2000 (2000-01-01 12:00 TT).
"""
import hashlib
import math
from functools import lru_cache

MU_SUN = 2.959122082855911e-4        # AU^3 / day^2
AU_PER_DAY_TO_KMS = 1731.45683681
TIME_PENALTY_MPS_PER_YEAR = 250      # 1 year of travel costs as much as 250 m/s of fuel
MIN_LEG_DAYS = 20
FLYBY_SAFETY = 1.1                   # closest approach: 1.1 planet radii
MIN_FLYBY_VINF = 1.0                 # km/s: slower than this isn't a gravity assist
LAMBERT_ITERATIONS = 80
MIN_PERIHELION_AU = 0.3              # don't let trajectories dive inside Mercury's orbit

# name, short code, semi-major axis (AU), mean longitude at J2000 (deg), GM (km^3/s^2), radius (km)
PLANETS = [
    ("Mercury", "Me", 0.387098, 252.25, 22032.0, 2440.0),
    ("Venus", "V", 0.723332, 181.98, 324859.0, 6052.0),
    ("Earth", "E", 1.000000, 100.46, 398600.0, 6371.0),
    ("Mars", "Ma", 1.523679, 355.45, 42828.0, 3390.0),
    ("Jupiter", "J", 5.204400, 34.40, 126686534.0, 69911.0),
    ("Saturn", "S", 9.582600, 49.94, 37931187.0, 58232.0),
    ("Uranus", "U", 19.218400, 313.23, 5793939.0, 25362.0),
    ("Neptune", "N", 30.110000, 304.88, 6836529.0, 24622.0),
]
EARTH = 2
TARGETS = [4, 5, 6, 7]                      # Jupiter, Saturn, Uranus, Neptune
MAX_TOF_YEARS = {4: 8, 5: 12, 6: 20, 7: 30}
MAX_FLYBYS = 3
WINDOW_DAYS = 1461                          # 4-year launch window
WINDOW_START_MIN = 9131                     # ~2025-01-01
WINDOW_START_SPREAD = 3650                  # windows start somewhere in 2025-2035


def planet_state(pid: int, day: float):
    """Position (AU) and velocity (AU/day) of a planet on its circular orbit."""
    _, _, a, l0, _, _ = PLANETS[pid]
    n = math.sqrt(MU_SUN / a ** 3)
    th = math.radians(l0) + n * day
    v = math.sqrt(MU_SUN / a)
    return (a * math.cos(th), a * math.sin(th)), (-v * math.sin(th), v * math.cos(th))


def _stumpff(psi):
    if psi > 1e-6:
        s = math.sqrt(psi)
        return (1 - math.cos(s)) / psi, (s - math.sin(s)) / (s ** 3)
    if psi < -1e-6:
        s = math.sqrt(-psi)
        return (1 - math.cosh(s)) / psi, (math.sinh(s) - s) / (s ** 3)
    return 0.5, 1.0 / 6.0


def lambert(r1, r2, tof):
    """Prograde, zero-revolution Lambert solver. Returns (v1, v2) in AU/day, or None."""
    r1n, r2n = math.hypot(*r1), math.hypot(*r2)
    cos_dnu = max(-1.0, min(1.0, (r1[0] * r2[0] + r1[1] * r2[1]) / (r1n * r2n)))
    dnu = math.acos(cos_dnu)
    if r1[0] * r2[1] - r1[1] * r2[0] < 0:
        dnu = 2 * math.pi - dnu
    if abs(1 - cos_dnu) < 1e-12:
        return None
    A = math.sin(dnu) * math.sqrt(r1n * r2n / (1 - cos_dnu))
    if abs(A) < 1e-12:
        return None
    lo, hi = -400.0, 4 * math.pi ** 2   # psi < 0: hyperbolic, > 0: elliptic (one revolution max)
    psi = 0.0
    y = 0.0
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
    v1 = ((r2[0] - f * r1[0]) / g, (r2[1] - f * r1[1]) / g)
    v2 = ((gdot * r2[0] - r1[0]) / g, (gdot * r2[1] - r1[1]) / g)
    # Refuse paths that would dive too close to the Sun (perihelion < MIN_PERIHELION_AU).
    hz = r1[0] * v1[1] - r1[1] * v1[0]
    energy = (v1[0] ** 2 + v1[1] ** 2) / 2 - MU_SUN / r1n
    ecc = math.sqrt(max(0.0, 1 + 2 * energy * hz * hz / MU_SUN ** 2))
    if hz * hz / MU_SUN / (1 + ecc) < MIN_PERIHELION_AU:
        return None
    return v1, v2


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _norm(a):
    return math.hypot(a[0], a[1])


def flyby_dv(pid, vin, vout):
    """Fuel (km/s) for a flyby given incoming/outgoing speeds relative to the planet (km/s)."""
    _, _, _, _, mu, radius = PLANETS[pid]
    a, b = _norm(vin), _norm(vout)
    dv = abs(b - a)
    vavg = (a + b) / 2
    if a < 1e-9 or b < 1e-9:
        return dv                          # no relative speed: nothing to turn
    cosd = max(-1.0, min(1.0, (vin[0] * vout[0] + vin[1] * vout[1]) / (a * b)))
    turn = math.acos(cosd)
    max_turn = 2 * math.asin(1 / (1 + FLYBY_SAFETY * radius * vavg ** 2 / mu))
    if turn > max_turn:
        dv += 2 * vavg * math.sin((turn - max_turn) / 2)
    return dv


def evaluate(seq, days):
    """Cost breakdown of a trajectory, or None if impossible.

    seq:  planet ids, Earth first, target last, flybys in between
    days: arrival day at each planet (days[0] = launch)
    """
    if len(seq) != len(days) or len(seq) < 2:
        return None
    legs = []
    for i in range(len(seq) - 1):
        tof = days[i + 1] - days[i]
        if tof < MIN_LEG_DAYS:
            return None
        r1, _ = planet_state(seq[i], days[i])
        r2, _ = planet_state(seq[i + 1], days[i + 1])
        sol = lambert(r1, r2, tof)
        if sol is None:
            return None
        legs.append(sol)

    k = AU_PER_DAY_TO_KMS
    _, vp0 = planet_state(seq[0], days[0])
    launch = _norm(_sub(legs[0][0], vp0)) * k
    flybys = []
    for i in range(1, len(seq) - 1):
        _, vp = planet_state(seq[i], days[i])
        vin = tuple(c * k for c in _sub(legs[i - 1][1], vp))
        vout = tuple(c * k for c in _sub(legs[i][0], vp))
        if _norm(vin) < MIN_FLYBY_VINF:
            return None
        flybys.append(flyby_dv(seq[i], vin, vout))
    _, vpn = planet_state(seq[-1], days[-1])
    arrival = _norm(_sub(legs[-1][1], vpn)) * k
    years = (days[-1] - days[0]) / 365.25
    dv = launch + sum(flybys) + arrival
    return {
        "launch_kms": launch, "flyby_kms": flybys, "arrival_kms": arrival,
        "dv_kms": dv, "years": years,
        "cost": dv * 1000 + TIME_PENALTY_MPS_PER_YEAR * years,   # m/s-equivalent
    }


# ---- per-block problems -------------------------------------------------

def problem(prev_hash: str) -> dict:
    """This block's mission, chosen unpredictably from the previous block's hash."""
    h = int.from_bytes(hashlib.sha256(bytes.fromhex(prev_hash) + b"mission").digest(), "big")
    target = TARGETS[h % len(TARGETS)]
    start = WINDOW_START_MIN + (h >> 8) % WINDOW_START_SPREAD
    flyby_bodies = [1, 2, 3] + [p for p in (4, 5) if p < target]
    return {
        "target": target,
        "window_start": start,
        "window_end": start + WINDOW_DAYS,
        "max_tof_days": int(MAX_TOF_YEARS[target] * 365.25),
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
    a = (1 + PLANETS[target][2]) / 2
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
            ev = evaluate([EARTH, t], [launch, launch + tof])
            if ev and (best is None or ev["cost"] < best[0]):
                best = (ev["cost"], [EARTH, t], [launch, launch + tof])
    return {"cost": best[0], "seq": best[1], "days": best[2]}
