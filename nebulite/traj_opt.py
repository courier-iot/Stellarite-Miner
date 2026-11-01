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
    ev = T.evaluate(seq, days, prob.get("time_penalty_mps_per_year", T.TIME_PENALTY_MPS_PER_YEAR))
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


def optimise(prob, seconds=3.0, max_flybys=2, seed=None):
    """Return (seq, days, cost) of the best trajectory found within `seconds`."""
    rng = random.Random(seed)
    deadline = time.time() + seconds
    seqs = sequences(prob, max_flybys)
    best_per = {}
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
