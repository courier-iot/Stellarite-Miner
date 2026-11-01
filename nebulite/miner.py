"""Reference CPU miner for Nebulite (Python). Does the same thing as the Android app.

  python miner.py --node http://127.0.0.1:5001 --address nblt...

Each round: fetch this block's mission, optimise a trajectory (useful work),
ask the node for that trajectory's header and target, then search nonces.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

import trajectory as T
from traj_opt import optimise

REFRESH_SECONDS = 15
PLAN_SECONDS = 4


def call(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def search(prefix: bytes, target: int, start: int, deadline: float):
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
    ap.add_argument("--node", default="http://127.0.0.1:5001")
    ap.add_argument("--address", required=True)
    ap.add_argument("--blocks", type=int, default=0, help="stop after N blocks (0 = forever)")
    ap.add_argument("--plan-seconds", type=float, default=PLAN_SECONDS)
    args = ap.parse_args()
    node = args.node.rstrip("/")
    found = 0
    while not args.blocks or found < args.blocks:
        work = call(f"{node}/mining/work?address={args.address}")
        if "job_id" not in work:
            raise SystemExit(f"Node refused work: {work}")
        seq, days, _ = optimise(work["mission"], seconds=args.plan_seconds)
        scored = call(f"{node}/mining/trajectory", {"job_id": work["job_id"], "seq": seq, "days": days})
        if "prefix" not in scored:
            print("Trajectory refused:", scored.get("error"))
            continue
        path = "-".join(T.PLANETS[p][1] for p in seq)
        desc = (f"{path}: {scored['dv_kms']:.2f} km/s, {scored['years']:.1f} yr "
                f"({scored['improvement_pct']:+.1f}% vs direct)")
        prefix, target = bytes.fromhex(scored["prefix"]), int(scored["target"], 16)
        t0 = time.time()
        nonce, tried = search(prefix, target, int.from_bytes(os.urandom(8), "big") >> 2,
                              t0 + REFRESH_SECONDS)
        if nonce is None:
            print(f"height {work['height']}: {desc}, {tried / (time.time() - t0) / 1000:.0f} kH/s, refreshing")
            continue
        r = call(f"{node}/mining/submit", {"job_id": work["job_id"], "seq": seq, "days": days, "nonce": nonce})
        if r.get("ok"):
            found += 1
            print(f"Found block {r['height']}: {desc}")
        else:
            print("Submit rejected:", r.get("error"))


if __name__ == "__main__":
    main()
