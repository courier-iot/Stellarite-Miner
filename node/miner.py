"""Reference CPU miner (Python). Does the same thing as the Android app.

  python miner.py --node http://127.0.0.1:5000 --address plsr...
"""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

REFRESH_SECONDS = 10  # fetch fresh work this often so we notice new blocks


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
            nonce = (nonce + 1) % (1 << 64)
        if time.time() > deadline:
            return None, nonce - start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default="http://127.0.0.1:5000")
    ap.add_argument("--address", required=True)
    ap.add_argument("--blocks", type=int, default=0, help="stop after N blocks (0 = forever)")
    args = ap.parse_args()
    node = args.node.rstrip("/")
    found = 0
    while not args.blocks or found < args.blocks:
        work = call(f"{node}/mining/work?address={args.address}")
        if "job_id" not in work:
            raise SystemExit(f"Node refused work: {work}")
        prefix, target = bytes.fromhex(work["prefix"]), int(work["target"], 16)
        t0 = time.time()
        nonce, tried = search(prefix, target, int.from_bytes(os.urandom(8), "big") >> 1,
                              t0 + REFRESH_SECONDS)
        rate = tried / max(time.time() - t0, 1e-6)
        if nonce is None:
            print(f"height {work['height']}: {rate/1000:.0f} kH/s, refreshing work")
            continue
        r = call(f"{node}/mining/submit", {"job_id": work["job_id"], "nonce": nonce})
        if r.get("ok"):
            found += 1
            print(f"Found block {r['height']} ({rate/1000:.0f} kH/s) reward "
                  f"{work['reward'] / work['units_per_coin']}")
        else:
            print("Submit rejected:", r.get("error"))


if __name__ == "__main__":
    main()
