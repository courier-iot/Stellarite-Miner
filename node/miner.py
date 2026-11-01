"""Reference CPU miner (Python). Does the same thing as the Android app.

  python miner.py --node http://127.0.0.1:5000 --address plsr...

Each round: fetch the block's 24 stars, optimise a route through them (useful
work), ask the node for the route's header and target, then search nonces.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from route_opt import optimise, optimise_plan, plan_cost, polish

REFRESH_SECONDS = 10   # fetch fresh work this often so we notice new blocks
ROUTE_SECONDS = 2      # time spent optimising each block's route


def call(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def search(prefix: bytes, target: int, start: int, deadline: float):
    """Try nonces from `start` until one meets the target or time runs out."""
    sha = hashlib.sha256
    nonce = start
    while True:
        for _ in range(20_000):
            h = sha(sha(prefix + nonce.to_bytes(8, "big")).digest()).digest()
            if int.from_bytes(h, "big") <= target:
                return nonce, nonce - start + 1
            nonce = (nonce + 1) % (1 << 63)
        if time.time() > deadline:
            return None, nonce - start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default="http://127.0.0.1:5000")
    ap.add_argument("--address", required=True)
    ap.add_argument("--blocks", type=int, default=0, help="stop after N blocks (0 = forever)")
    ap.add_argument("--route-seconds", type=float, default=ROUTE_SECONDS)
    args = ap.parse_args()
    node = args.node.rstrip("/")
    found = 0
    while not args.blocks or found < args.blocks:
        work = call(f"{node}/mining/work?address={args.address}")
        if "job_id" not in work:
            raise SystemExit(f"Node refused work: {work}")
        # Plan on star positions mid-mission, then polish against the exact moving-star timing.
        t_mid = work["launch_t"] + int(work["baseline_years"] * 500)
        pts = [(s["x"] + s["vx"] * t_mid // 1_000_000, s["y"] + s["vy"] * t_mid // 1_000_000,
                s["z"] + s["vz"] * t_mid // 1_000_000) for s in work["stars"]]
        order = optimise(pts, seconds=args.route_seconds * 0.6)
        route = [work["stars"][i]["id"] for i in order]
        # Exact polish of the order at the baseline's cruise speed, then tune speeds leg by leg
        # (spending the fuel budget where it saves the most time) and keep alternating.
        base_pct = work["baseline_route"][0][1]
        route = polish(route, lambda r: plan_cost([[s, base_pct] for s in r], work), args.route_seconds * 0.15)
        route = optimise_plan(route, work, args.route_seconds * 0.25)
        scored = call(f"{node}/mining/route", {"job_id": work["job_id"], "route": route})
        if "prefix" not in scored:
            print("Route refused:", scored.get("error"))
            continue
        prefix, target = bytes.fromhex(scored["prefix"]), int(scored["target"], 16)
        t0 = time.time()
        nonce, tried = search(prefix, target, int.from_bytes(os.urandom(8), "big") >> 2,
                              t0 + REFRESH_SECONDS)
        rate = tried / max(time.time() - t0, 1e-6)
        route_txt = (f"mission {scored['years']:,.0f} yr vs greedy {scored['baseline_years']:,.0f} yr "
                     f"({scored['improvement_pct']:+.1f}% faster, {scored['length_ly']:.0f} ly flown, "
                     f"{scored['fuel_used_pct']:.0f}% of fuel)")
        if nonce is None:
            print(f"height {work['height']}: {route_txt}, {rate/1000:.0f} kH/s, refreshing")
            continue
        r = call(f"{node}/mining/submit", {"job_id": work["job_id"], "route": route, "nonce": nonce})
        if r.get("ok"):
            found += 1
            print(f"Found block {r['height']}: {route_txt}, reward "
                  f"{work['reward'] / work['units_per_coin']}")
        else:
            print("Submit rejected:", r.get("error"))


if __name__ == "__main__":
    main()
