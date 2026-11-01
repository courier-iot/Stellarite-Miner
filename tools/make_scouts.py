"""Mine Nebulite escape blocks that can be cited as Pulsarite scouts (for tests and demos).

    python tools/make_scouts.py '[3, 49]' 16 2     # escapes toward stars 3 or 49, difficulty 16 bits, 2 blocks

Runs Nebulite's own chain code, exactly as a Nebulite node would, and prints the blocks as
scout proofs (JSON). Each uses its mission's textbook baseline trajectory.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nebulite"))
import chain as ch  # noqa: E402
import config as C  # noqa: E402
import trajectory as T  # noqa: E402


def main():
    wanted, bits, n = set(json.loads(sys.argv[1])), int(sys.argv[2]), int(sys.argv[3])
    tag = sys.argv[4] if len(sys.argv) > 4 else "scout"
    out, k = [], 0
    while len(out) < n and k < 5000:
        h = hashlib.sha256(f"{tag}{k}".encode()).hexdigest()
        k += 1
        p = T.problem(h)
        if p["type"] != "escape" or (wanted and p["target_star"]["id"] not in wanted):
            continue
        b = T.escape_baseline(h)
        sc = ch.score_trajectory(h, b["seq"], b["days"], b["escape"])
        tr = {"seq": b["seq"], "days": b["days"], "cost": sc["cost"], "baseline": sc["baseline"], "escape": b["escape"]}
        coinbase = {"coinbase": True, "to": "nblt-scout-test", "amount": ch.block_reward(7), "height": 7}
        blk = {"height": 7, "prev_hash": h, "timestamp": C.GENESIS_TIMESTAMP + 3600, "txs": [coinbase],
               "target": format(C.MAX_TARGET >> bits, "064x"), "trajectory": tr, "nonce": 0}
        blk["tx_root"] = ch.tx_root(blk["txs"])
        eff = ch.effective_target(blk["target"], tr["cost"], tr["baseline"])
        prefix = ch.header_prefix(blk)
        while int.from_bytes(ch.pow_hash(prefix, blk["nonce"]), "big") > eff:
            blk["nonce"] += 1
        out.append({key: blk[key] for key in ("height", "prev_hash", "timestamp", "target", "tx_root", "trajectory", "nonce")})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
