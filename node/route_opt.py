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

def probe_leg(d, u, c, stop, A):
    """One leg of d micro-ly from speed u cruising at c: (milli-years, end speed, delta-v). Same maths as stars.leg."""
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
    brake = u * u // (2 * A)
    if brake >= d:
        e = brake - d
        return u * 1000 // A + 2 * math.isqrt(e * 1_000_000 // A), 0, u + 2 * math.isqrt(A * e)
    if u > c:
        return (u - c) * 1000 // A + c * 1000 // A + (d - brake) * 1000 // c, 0, u
    up, down = (c * c - u * u) // (2 * A), c * c // (2 * A)
    if up + down <= d:
        return (c - u) * 1000 // A + c * 1000 // A + (d - up - down) * 1000 // c, 0, 2 * c - u
    p = math.isqrt((2 * A * d + u * u) // 2)
    return (p - u) * 1000 // A + p * 1000 // A, 0, 2 * p - u


def plan_eval(plan, work):
    """(mission time in milli-years, delta-v in micro-ly/yr) for a plan [[star id, cruise %c], ...],
    using the star data in a /mining/work reply. Same integer maths as stars.route_time / route_dv,
    so it matches the node's score exactly."""
    by_id = {s["id"]: s for s in work["stars"]}
    pct_speed = work["probe_speed_mly_per_year"] * 100        # 1% of c in micro-ly/yr
    A = work["probe_accel_mly_per_year2"] * 1000
    t0, iters = work["launch_t"], work["intercept_iterations"]
    stop_set = set(work.get("stops", ()))
    survey = work.get("survey_years", 0) * 1000
    per_planet = work.get("survey_years_per_planet", 0) * 1000

    def pos(s, t):
        return (s["x"] + s["vx"] * t // 1_000_000, s["y"] + s["vy"] * t // 1_000_000,
                s["z"] + s["vz"] * t // 1_000_000)

    here, t, u, total_dv = (0, 0, 0), t0, 0, 0
    for sid, pct in plan:
        s, stop, c = by_id[sid], sid in stop_set, pct * pct_speed
        arrive, speed, dv = t, u, 0
        for _ in range(iters):
            p = pos(s, arrive)
            d = math.isqrt(sum((p[k] - here[k]) ** 2 for k in range(3)) * 1_000_000)
            dt, speed, dv = probe_leg(d, u, c, stop, A)
            arrive = t + dt
        t = arrive + survey + per_planet * s.get("planets", 0) if stop else arrive
        here, u, total_dv = pos(s, t), speed, total_dv + dv
    return t - t0, total_dv


def mission_time(plan, work):
    """Mission time (milli-years) of a plan; see plan_eval."""
    return plan_eval(plan, work)[0]


def plan_cost(plan, work):
    """Mission time, or infinity if the plan needs more fuel than the probe carries."""
    t, dv = plan_eval(plan, work)
    return t if dv <= work["dv_budget_pct_c"] * work["probe_speed_mly_per_year"] * 100 else float("inf")


def tune_speeds(order, speeds, work, seconds):
    """Hill-climb the per-leg cruise speeds (1-10 % of c) for a fixed star order, within the fuel budget.

    Moves: change one leg's speed by +-1 or +-2, or shift one step of speed from one leg to another.
    """
    deadline = time.time() + seconds
    speeds = list(speeds)
    best = plan_cost([[s, v] for s, v in zip(order, speeds)], work)
    n = len(order)
    moves = [((i, d),) for i in range(n) for d in (1, -1, 2, -2)]
    moves += [((i, 1), (j, -1)) for i in range(n) for j in range(n) if i != j]
    improved = True
    while improved and time.time() < deadline:
        improved = False
        for move in moves:
            cand = list(speeds)
            for i, d in move:
                cand[i] += d
            if any(v < 1 or v > 10 for v in cand):
                continue
            c = plan_cost([[s, v] for s, v in zip(order, cand)], work)
            if c < best:
                speeds, best, improved = cand, c, True
            if time.time() > deadline:
                break
    return speeds, best


def optimise_plan(order, work, seconds):
    """Star order and per-leg speeds: start at the fastest uniform speed that fits the fuel,
    then alternate speed tuning and order polishing (speeds stay with their leg position)."""
    deadline = time.time() + seconds
    speeds = None
    for pct in range(10, 0, -1):
        if plan_cost([[s, pct] for s in order], work) < float("inf"):
            speeds = [pct] * len(order)
            break
    if speeds is None:
        return [[s, 1] for s in order]
    best = plan_cost([[s, v] for s, v in zip(order, speeds)], work)
    while time.time() < deadline:
        left = deadline - time.time()
        speeds, _ = tune_speeds(order, speeds, work, left / 2)
        sp = list(speeds)
        order = polish(order, lambda o: plan_cost([[s, v] for s, v in zip(o, sp)], work),
                       max(0.0, deadline - time.time()) / 2)
        c = plan_cost([[s, v] for s, v in zip(order, speeds)], work)
        if c >= best:
            break
        best = c
    return [[s, v] for s, v in zip(order, speeds)]


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
