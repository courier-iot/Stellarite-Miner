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


# ---- moving stars: exact mission-time scoring ---------------------------

def probe_leg(d, u, stop, V, A):
    """One leg of d micro-ly from speed u: (milli-years, end speed). Same maths as stars.leg."""
    if not stop:
        ramp = (V * V - u * u) // (2 * A)
        if d >= ramp:
            return (V - u) * 1000 // A + (d - ramp) * 1000 // V, V
        w = math.isqrt(u * u + 2 * A * d)
        return (w - u) * 1000 // A, w
    brake = u * u // (2 * A)
    if brake >= d:
        return u * 1000 // A + 2 * math.isqrt((brake - d) * 1_000_000 // A), 0
    up, down = (V * V - u * u) // (2 * A), V * V // (2 * A)
    if up + down <= d:
        return (V - u) * 1000 // A + V * 1000 // A + (d - up - down) * 1000 // V, 0
    p = math.isqrt((2 * A * d + u * u) // 2)
    return (p - u) * 1000 // A + p * 1000 // A, 0


def mission_time(route_ids, work):
    """Mission time (milli-years) for star ids, using the star data in a /mining/work reply.

    Same integer maths as stars.route_time (acceleration, braking at survey stops,
    moving stars), so it matches the node's score exactly.
    """
    by_id = {s["id"]: s for s in work["stars"]}
    V = work["probe_speed_mly_per_year"] * 1000
    A = work["probe_accel_mly_per_year2"] * 1000
    t0, iters = work["launch_t"], work["intercept_iterations"]
    stop_set = set(work.get("stops", ()))

    def pos(s, t):
        return (s["x"] + s["vx"] * t // 1_000_000, s["y"] + s["vy"] * t // 1_000_000,
                s["z"] + s["vz"] * t // 1_000_000)

    here, t, u = (0, 0, 0), t0, 0
    for sid in route_ids:
        s, stop = by_id[sid], sid in stop_set
        arrive, speed = t, u
        for _ in range(iters):
            p = pos(s, arrive)
            d = math.isqrt(sum((p[k] - here[k]) ** 2 for k in range(3)) * 1_000_000)
            dt, speed = probe_leg(d, u, stop, V, A)
            arrive = t + dt
        t, here, u = arrive, pos(s, arrive), speed
    return t - t0


def polish(order, cost, seconds):
    """2-opt and Or-opt using an exact (slow) cost function, until no gain or time runs out."""
    deadline = time.time() + seconds
    best = cost(order)
    improved = True
    while improved and time.time() < deadline:
        improved = False
        n = len(order)
        for i in range(n - 1):
            for j in range(i + 1, n):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                c = cost(cand)
                if c < best:
                    order, best, improved = cand, c, True
            if time.time() > deadline:
                break
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                cand = order[:i] + order[i + 1:]
                cand.insert(j, order[i])
                c = cost(cand)
                if c < best:
                    order, best, improved = cand, c, True
            if time.time() > deadline:
                break
    return order
