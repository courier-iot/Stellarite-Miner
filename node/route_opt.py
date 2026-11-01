"""Route optimiser: finds short open paths from the Sun through a set of stars.

This is the "useful work" half of mining. Greedy nearest-neighbour gives a
first route, then 2-opt (reverse a stretch) and Or-opt (move a short stretch)
improve it, with random kicks to escape local optima, until time runs out.
The Android app has a Kotlin port of the same method (RouteOptimizer.kt).
"""
import math
import random
import time


def _d(a, b):
    return math.dist(a, b)


def path_len(order, pts, sol=(0, 0, 0)):
    total, here = 0.0, sol
    for i in order:
        total += _d(here, pts[i])
        here = pts[i]
    return total


def _nearest_neighbour(pts, sol):
    left = set(range(len(pts)))
    here, order = sol, []
    while left:
        nxt = min(left, key=lambda i: _d(here, pts[i]))
        left.remove(nxt)
        order.append(nxt)
        here = pts[nxt]
    return order


def _two_opt(order, pts, sol):
    n = len(order)
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            a = sol if i == 0 else pts[order[i - 1]]
            for j in range(i + 1, n):
                b_in, b_out = pts[order[i]], pts[order[j]]
                after = pts[order[j + 1]] if j + 1 < n else None
                old = _d(a, b_in) + (_d(b_out, after) if after else 0)
                new = _d(a, b_out) + (_d(b_in, after) if after else 0)
                if new < old - 1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
    return order


def _or_opt(order, pts, sol):
    best = path_len(order, pts, sol)
    improved = True
    while improved:
        improved = False
        for seg in (1, 2, 3):
            for i in range(len(order) - seg + 1):
                chunk = order[i:i + seg]
                rest = order[:i] + order[i + seg:]
                for j in range(len(rest) + 1):
                    for c in (chunk, chunk[::-1]):
                        cand = rest[:j] + c + rest[j:]
                        L = path_len(cand, pts, sol)
                        if L < best - 1e-9:
                            order, best, improved = cand, L, True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
    return order


def optimise(pts, seconds=2.0, sol=(0, 0, 0), seed=None):
    """Return the order (indices into pts) of the best path found within `seconds`."""
    rng = random.Random(seed)
    deadline = time.time() + seconds
    order = _or_opt(_two_opt(_nearest_neighbour(pts, sol), pts, sol), pts, sol)
    best, best_len = order[:], path_len(order, pts, sol)
    while time.time() < deadline and len(pts) >= 8:
        # double-bridge kick, then re-optimise
        cand = best[:]
        a, b, c = sorted(rng.sample(range(1, len(cand)), 3))
        cand = cand[:a] + cand[c:] + cand[b:c] + cand[a:b]
        cand = _or_opt(_two_opt(cand, pts, sol), pts, sol)
        L = path_len(cand, pts, sol)
        if L < best_len - 1e-9:
            best, best_len = cand, L
    return best
