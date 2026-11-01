"""Trajectory optimiser: searches flyby sequences and dates for cheap missions.

This is Nebulite's useful work. For each candidate flyby sequence it tries
random launch/encounter dates within the mission rules, then improves them with
a pattern search (nudge each date by shrinking steps while the cost drops).
Promising sequences get more attempts. The Android app has a Kotlin port
(TrajectoryOptimizer.kt); the node does the official scoring.
"""
import itertools
import random
import time

import trajectory as T


def sequences(prob, max_flybys=2):
    """Candidate planet sequences: Earth, flybys..., target."""
    out = []
    for k in range(0, min(max_flybys, prob["max_flybys"]) + 1):
        for fb in itertools.product(prob["flyby_bodies"], repeat=k):
            out.append([T.EARTH, *fb, prob["target"]])
    return out


def _cost(prob, seq, days):
    if T.check(prob, seq, days):
        return float("inf")
    ev = T.evaluate(seq, days, prob.get("time_penalty_mps_per_year", T.TIME_PENALTY_MPS_PER_YEAR), prob)
    return ev["cost"] if ev else float("inf")


def _random_days(prob, seq, rng):
    n = len(seq)
    launch = rng.randint(prob["window_start"], prob["window_end"])
    total = rng.uniform(0.3, 1.0) * prob["max_tof_days"]
    cuts = sorted(rng.random() for _ in range(n - 2))
    fr = [0.0] + cuts + [1.0]
    days = [launch + round(total * f) for f in fr]
    for i in range(1, n):                          # keep legs at least MIN_LEG_DAYS
        days[i] = max(days[i], days[i - 1] + T.MIN_LEG_DAYS)
    return days


def _pattern_search(prob, seq, days, cost, deadline):
    step = 256
    while step >= 1 and time.time() < deadline:
        improved = False
        for i in range(len(days)):
            for s in (step, -step):
                cand = days[:]
                cand[i] += s
                if i == 0:                         # moving launch shifts the whole mission
                    cand = [d + s for d in days]
                c = _cost(prob, seq, cand)
                if c < cost:
                    days, cost, improved = cand, c, True
        if not improved:
            step //= 2
    return days, cost


def optimise(prob, seconds=3.0, max_flybys=2, seed=None, start=None):
    """Return (seq, days, cost) of the best trajectory found within `seconds`. `start` (the block's
    baseline {"seq", "days"}) is refined first, so the result is never worse than it."""
    rng = random.Random(seed)
    deadline = time.time() + seconds
    seqs = sequences(prob, max_flybys)
    best_per = {}
    if start is not None:
        c0 = _cost(prob, list(start["seq"]), list(start["days"]))
        if c0 < float("inf"):
            d0, c0 = _pattern_search(prob, list(start["seq"]), list(start["days"]), c0, time.time() + seconds / 4)
            best_per[tuple(start["seq"])] = (d0, c0)
    rounds = 0
    while time.time() < deadline:
        # first two rounds try every sequence; afterwards focus on the best few
        pool = seqs if rounds < 2 else sorted(best_per, key=lambda k: best_per[k][1])[:6]
        for key in pool:
            if time.time() >= deadline:
                break
            seq = list(key)
            days = None
            for _ in range(20):                    # find a feasible start
                d = _random_days(prob, seq, rng)
                c = _cost(prob, seq, d)
                if c < float("inf"):
                    days = d
                    break
            if days is None:
                best_per.setdefault(tuple(seq), (None, float("inf")))
                continue
            days, c = _pattern_search(prob, seq, days, c, deadline)
            if c < best_per.get(tuple(seq), (None, float("inf")))[1]:
                best_per[tuple(seq)] = (days, c)
        rounds += 1
    key = min(best_per, key=lambda k: best_per[k][1])
    days, cost = best_per[key]
    return list(key), days, cost


# ---- escape missions --------------------------------------------------------

def escape_sequences(prob, max_flybys=2):
    """Earth, then up to max_flybys planets, optionally ending in a Sun dive."""
    out = [[T.EARTH]]
    for k in range(1, min(max_flybys, prob["max_flybys"]) + 1):
        for fb in itertools.product(prob["flyby_bodies"], repeat=k):
            out.append([T.EARTH, *fb])
            out.append([T.EARTH, *fb, T.SUN])
    return out


def _escape_vars(seq, days, esc):
    dive = seq[-1] == T.SUN and len(seq) > 2
    return days + [esc["vinf_ms"]] + ([esc["rp_mau"]] if dive else [])


def _escape_split(seq, x):
    dive = seq[-1] == T.SUN and len(seq) > 2
    n = len(seq) - (1 if dive else 0)
    esc = {"vinf_ms": x[n]}
    if dive:
        esc["rp_mau"] = x[n + 1]
    return x[:n], esc


def escape_cost(prob, seq, days, esc):
    """Days from launch to 550 AU, or infinity if the trajectory breaks a rule or a limit."""
    if T.escape_check(prob, seq, days, esc):
        return float("inf")
    ev = T.escape_evaluate(prob, seq, days, esc)
    return ev["cost"] if ev else float("inf")


def _escape_start(prob, seq, rng):
    dive = seq[-1] == T.SUN and len(seq) > 2
    n = len(seq) - (1 if dive else 0)
    launch = rng.randint(prob["window_start"], prob["window_end"])
    days = [launch]
    for p in seq[1:n]:                          # rough leg times: half to one and a half Hohmann transfers
        days.append(days[-1] + max(T.MIN_LEG_DAYS, round(T.hohmann_days(p) * rng.uniform(0.4, 1.5))))
    esc = {"vinf_ms": rng.randint(1000, 4000)}
    if dive:
        esc["rp_mau"] = rng.randint(50, 300)
    return days, esc


def _refine(prob, seq, x, c, deadline):
    """Pattern search on one sequence's variables (days, escape speed, perihelion)."""
    step = 256
    while step >= 1 and time.time() < deadline:
        improved = False
        for i in range(len(x)):
            for s in (step, -step):
                cand = x[:]
                cand[i] += s
                days, esc = _escape_split(seq, cand)
                if i == 0:                         # moving launch shifts the whole mission
                    days = [d + s for d in x[:len(days)]]
                cc = escape_cost(prob, seq, days, esc)
                if cc < c:
                    x, c, improved = _escape_vars(seq, days, esc), cc, True
        if not improved:
            step //= 2
    return x, c


def optimise_escape(prob, seconds=3.0, max_flybys=2, seed=None, start=None):
    """Return (seq, days, escape, cost) of the fastest escape found within `seconds`.
    Pattern search over encounter days, escape speed and (for dives) perihelion distance:
    the speed climbs until the launch or fuel limit stops it. `start` (the block's baseline
    plan, {"seq", "days", "escape"}) is refined first, so the result is never worse than it."""
    rng = random.Random(seed)
    deadline = time.time() + seconds
    seqs = escape_sequences(prob, max_flybys)
    best_per = {}
    rounds = 0
    if start and start.get("seq"):
        seq = list(start["seq"])
        c0 = escape_cost(prob, seq, start["days"], start["escape"])
        if c0 < float("inf"):
            x, c = _refine(prob, seq, _escape_vars(seq, start["days"], start["escape"]), c0,
                           time.time() + seconds * 0.3)
            best_per[tuple(seq)] = (x, c)
    while time.time() < deadline:
        pool = seqs if rounds < 2 else sorted(best_per, key=lambda k: best_per[k][1])[:6]
        for key in pool:
            if time.time() >= deadline:
                break
            seq = list(key)
            x, c = None, float("inf")
            for _ in range(200):
                days, esc = _escape_start(prob, seq, rng)
                c = escape_cost(prob, seq, days, esc)
                if c < float("inf"):
                    x = _escape_vars(seq, days, esc)
                    break
            if x is None:
                best_per.setdefault(tuple(seq), (None, float("inf")))
                continue
            x, c = _refine(prob, seq, x, c, deadline)
            if c < best_per.get(tuple(seq), (None, float("inf")))[1]:
                best_per[tuple(seq)] = (x, c)
        rounds += 1
    key = min(best_per, key=lambda k: best_per[k][1])
    x, cost = best_per[key]
    if x is None:
        return None
    days, esc = _escape_split(list(key), x)
    return list(key), days, esc, cost


def plan(prob, seconds=3.0, max_flybys=2, seed=None, start=None):
    """Plan this block's mission, whatever its type: {"seq", "days"} plus "escape" for escape missions.
    `start` is the baseline plan from /mining/work (used by escape missions)."""
    if prob["type"] in ("escape", "heliopause"):
        r = optimise_escape(prob, seconds, max_flybys, seed, start)
        return None if r is None else {"seq": r[0], "days": r[1], "escape": r[2], "cost": r[3]}
    seq, days, cost = optimise(prob, seconds, max_flybys, seed, start)
    return {"seq": seq, "days": days, "cost": cost}
