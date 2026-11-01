"""Run from the node/ folder:  python -m unittest discover tests"""
import os
import sys
import tempfile
import time
import unittest

os.environ["PULSARITE_DIFFICULTY_BITS"] = "6"  # easy mining for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as C  # noqa: E402
import chain as ch  # noqa: E402
import stars  # noqa: E402
from route_opt import optimise  # noqa: E402
from crypto_utils import (address_from_pubkey, is_valid_address, new_private_key,  # noqa: E402
                          public_key_hex, sign)


def mine(template, route=None):
    """Mine a template; uses the greedy baseline route unless one is given."""
    template = dict(template)
    template["route"] = route or stars.baseline_route(stars.problem(template["prev_hash"]))
    sc = ch.route_score(template["prev_hash"], template["route"])
    prefix = ch.header_prefix(template)
    target = ch.effective_target(template["target"], sc["length"], sc["baseline"])
    nonce = 0
    while int.from_bytes(ch.pow_hash(prefix, nonce), "big") > target:
        nonce += 1
    block = dict(template, nonce=nonce)
    block["hash"] = ch.block_hash(block)
    return block


class Wallet:
    def __init__(self):
        self.key = new_private_key()
        self.pub = public_key_hex(self.key)
        self.addr = address_from_pubkey(self.pub)

    def tx(self, to, amount, nonce, fee=C.MIN_FEE):
        t = {"from": self.pub, "to": to, "amount": amount, "fee": fee, "nonce": nonce}
        t["sig"] = sign(self.key, ch.tx_signing_bytes(t))
        return t


class Clock:
    """Deterministic timestamps 30s apart."""
    def __init__(self, step=C.TARGET_BLOCK_SECONDS):
        self.t, self.step = int(time.time()) - 3600, step

    def __call__(self):
        self.t += self.step
        return self.t


def mine_next(bc, addr, clock):
    now = clock()
    block = mine(bc.build_template(addr, now=now))
    bc.add_block(block, now=now)
    return block


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.bc = ch.Blockchain()
        self.alice, self.bob = Wallet(), Wallet()
        self.clock = Clock()

    def test_addresses(self):
        self.assertTrue(is_valid_address(self.alice.addr))
        bad = self.alice.addr[:-1] + ("0" if self.alice.addr[-1] != "0" else "1")
        self.assertFalse(is_valid_address(bad))

    def test_mining_pays_reward(self):
        mine_next(self.bc, self.alice.addr, self.clock)
        self.assertEqual(self.bc.state.balance(self.alice.addr), C.BLOCK_REWARD)

    def test_transfer_and_fees(self):
        mine_next(self.bc, self.alice.addr, self.clock)
        self.bc.add_transaction(self.alice.tx(self.bob.addr, 10 * C.UNITS_PER_COIN, 0))
        mine_next(self.bc, self.bob.addr, self.clock)
        self.assertEqual(self.bc.state.balance(self.alice.addr),
                         C.BLOCK_REWARD - 10 * C.UNITS_PER_COIN - C.MIN_FEE)
        self.assertEqual(self.bc.state.balance(self.bob.addr),
                         10 * C.UNITS_PER_COIN + C.BLOCK_REWARD + C.MIN_FEE)
        self.assertEqual(self.bc.mempool, {})

    def test_replay_rejected(self):
        mine_next(self.bc, self.alice.addr, self.clock)
        tx = self.alice.tx(self.bob.addr, C.UNITS_PER_COIN, 0)
        self.bc.add_transaction(tx)
        mine_next(self.bc, self.bob.addr, self.clock)
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(tx)

    def test_overspend_rejected(self):
        mine_next(self.bc, self.alice.addr, self.clock)
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(self.alice.tx(self.bob.addr, C.BLOCK_REWARD, 0))

    def test_tampered_signature_rejected(self):
        mine_next(self.bc, self.alice.addr, self.clock)
        tx = self.alice.tx(self.bob.addr, C.UNITS_PER_COIN, 0)
        tx["to"] = Wallet().addr
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(tx)

    def test_bad_pow_rejected(self):
        now = self.clock()
        t = self.bc.build_template(self.alice.addr, now=now)
        t["target"] = format(1, "064x")  # claim an impossible target
        block = dict(t, nonce=0, route=stars.baseline_route(stars.problem(t["prev_hash"])))
        block["hash"] = ch.block_hash(block)
        with self.assertRaises(ch.ValidationError):
            self.bc.add_block(block, now=now)

    def test_inflated_coinbase_rejected(self):
        now = self.clock()
        t = self.bc.build_template(self.alice.addr, now=now)
        t["txs"][0]["amount"] += 1
        t["tx_root"] = ch.tx_root(t["txs"])
        with self.assertRaises(ch.ValidationError):
            self.bc.add_block(mine(t), now=now)

    def test_difficulty_rises_when_blocks_are_fast(self):
        fast = Clock(step=5)
        for _ in range(C.RETARGET_INTERVAL - 1):
            mine_next(self.bc, self.alice.addr, fast)
        before = int(self.bc.tip["target"], 16)
        after = int(ch.next_target(self.bc.blocks), 16)
        self.assertLess(after, before)  # smaller target = harder

    def test_most_work_wins(self):
        other = ch.Blockchain()
        other_clock = Clock()
        mine_next(self.bc, self.alice.addr, self.clock)
        for _ in range(3):
            mine_next(other, self.bob.addr, other_clock)
        self.assertTrue(self.bc.replace_chain(other.blocks))
        self.assertEqual(self.bc.tip["hash"], other.tip["hash"])
        self.assertEqual(self.bc.state.balance(self.alice.addr), 0)
        self.assertFalse(self.bc.replace_chain(other.blocks[:2]))

    def test_route_must_cover_the_blocks_stars(self):
        now = self.clock()
        t = self.bc.build_template(self.alice.addr, now=now)
        problem = stars.problem(t["prev_hash"])
        for bad in (problem[:-1], problem[:-1] + problem[:1],
                    problem[:-1] + [next(i for i in range(len(stars.CATALOG)) if i not in problem)]):
            with self.assertRaises(ch.ValidationError):
                ch.route_score(t["prev_hash"], bad)

    def test_route_is_bound_into_the_hash(self):
        now = self.clock()
        block = mine(self.bc.build_template(self.alice.addr, now=now))
        swapped = block["route"][:]
        swapped[0], swapped[1] = swapped[1], swapped[0]
        with self.assertRaises(ch.ValidationError):
            self.bc.add_block(dict(block, route=swapped), now=now)

    def test_shorter_routes_get_easier_targets(self):
        t = self.bc.build_template(self.alice.addr, now=self.clock())
        problem = stars.problem(t["prev_hash"])
        pts = [stars.pos(i) for i in problem]
        best = [problem[i] for i in optimise(pts, seconds=0.5, seed=3)]
        sc_base = ch.route_score(t["prev_hash"], stars.baseline_route(problem))
        sc_best = ch.route_score(t["prev_hash"], best)
        self.assertLess(sc_best["length"], sc_base["length"])
        easy = ch.effective_target(t["target"], sc_best["length"], sc_best["baseline"])
        self.assertGreater(easy, int(t["target"], 16))
        self.assertEqual(ch.effective_target(t["target"], sc_base["length"], sc_base["baseline"]),
                         int(t["target"], 16))
        self.bc.add_block(mine(t, best), now=self.clock() - 1)  # an optimised route is accepted

    def test_problems_change_every_block(self):
        a = mine_next(self.bc, self.alice.addr, self.clock)
        b = mine_next(self.bc, self.alice.addr, self.clock)
        self.assertNotEqual(sorted(a["route"]), sorted(b["route"]))
        self.assertEqual(len(a["route"]), stars.STARS_PER_PROBLEM)

    def test_usernames(self):
        now = self.clock()
        self.bc.add_block(mine(self.bc.build_template(self.alice.addr, now=now, name="NOVA_7")), now=now)
        self.assertEqual(self.bc.state.name_owner("NOVA_7"), self.alice.addr)
        # someone else can't take it, either through the template or by forging a block
        with self.assertRaises(ch.ValidationError):
            self.bc.build_template(self.bob.addr, now=self.clock(), name="NOVA_7")
        now = self.clock()
        t = self.bc.build_template(self.bob.addr, now=now)
        t["txs"][0]["name"] = "NOVA_7"
        t["tx_root"] = ch.tx_root(t["txs"])
        with self.assertRaises(ch.ValidationError):
            self.bc.add_block(mine(t), now=now)
        # bad formats are refused
        for bad in ("no", "lowercase", "WAY_TOO_LONG_A_NAME", "BAD-CHAR"):
            with self.assertRaises(ch.ValidationError):
                self.bc.build_template(self.bob.addr, now=self.clock(), name=bad)
        # switching names releases the old one
        now = self.clock()
        self.bc.add_block(mine(self.bc.build_template(self.alice.addr, now=now, name="ORBIT")), now=now)
        self.assertIsNone(self.bc.state.name_owner("NOVA_7"))
        self.assertEqual(self.bc.state.name_of[self.alice.addr], "ORBIT")
        # names survive a reload / re-validation from genesis
        other = ch.Blockchain()
        self.assertTrue(other.replace_chain(self.bc.blocks))
        self.assertEqual(other.state.name_owner("ORBIT"), self.alice.addr)

    def test_stars_move(self):
        barnard = next(s["id"] for s in stars.CATALOG if s["name"] == "Barnard's Star")
        now, later = stars.pos(barnard, 0), stars.pos(barnard, 1000 * 1000)   # J2000 vs J3000
        moved = stars.distance(now, later) / 1000
        self.assertAlmostEqual(moved, 0.47, delta=0.05)   # ~140 km/s for 1000 years ≈ 0.47 ly

    def test_intercept_aims_where_the_star_will_be(self):
        sid = next(s["id"] for s in stars.CATALOG if s["name"] == "Kapteyn's Star")
        t_arr, p = stars.intercept(stars.SOL, stars.LAUNCH_T, sid)
        flight = (t_arr - stars.LAUNCH_T) * stars.SPEED / 1000       # mly the probe flew
        self.assertAlmostEqual(flight, stars.distance(stars.SOL, p), delta=stars.SPEED / 500)
        self.assertEqual(p, stars.pos(sid, t_arr))

    def test_miner_timing_matches_node(self):
        from route_opt import mission_time
        prob = stars.problem("ab" * 32)
        work = {"stars": [dict(stars.CATALOG[i]) for i in prob], "probe_speed_mly_per_year": stars.SPEED,
                "launch_t": stars.LAUNCH_T, "intercept_iterations": stars.INTERCEPT_ITERATIONS}
        route = stars.baseline_route(prob)[::-1]
        self.assertEqual(mission_time(route, work), stars.route_time(route))

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            bc = ch.Blockchain(d)
            mine_next(bc, self.alice.addr, Clock())
            reloaded = ch.Blockchain(d)
            self.assertEqual(reloaded.tip, bc.tip)
            self.assertEqual(reloaded.state.balance(self.alice.addr), C.BLOCK_REWARD)


class ApiTests(unittest.TestCase):
    def setUp(self):
        import node
        node.chain = ch.Blockchain()
        node.jobs.clear()
        node.peers.clear()
        self.client = node.app.test_client()
        self.alice, self.bob = Wallet(), Wallet()

    def mine_via_api(self, addr, optimise_seconds=0.2, name=None):
        q = f"&name={name}" if name else ""
        work = self.client.get(f"/mining/work?address={addr}{q}").get_json()
        pts = [(s["x"], s["y"], s["z"]) for s in work["stars"]]
        route = [work["stars"][i]["id"] for i in optimise(pts, seconds=optimise_seconds, seed=1)]
        scored = self.client.post("/mining/route", json={"job_id": work["job_id"], "route": route}).get_json()
        prefix, target = bytes.fromhex(scored["prefix"]), int(scored["target"], 16)
        nonce = 0
        while int.from_bytes(ch.pow_hash(prefix, nonce), "big") > target:
            nonce += 1
        return self.client.post("/mining/submit",
                                json={"job_id": work["job_id"], "route": route, "nonce": nonce})

    def test_full_flow(self):
        r = self.mine_via_api(self.alice.addr)
        self.assertTrue(r.get_json()["ok"])
        bal = self.client.get(f"/balance/{self.alice.addr}").get_json()
        self.assertEqual(bal["balance"], C.BLOCK_REWARD)
        r = self.client.post("/tx", json=self.alice.tx(self.bob.addr, 5 * C.UNITS_PER_COIN,
                                                       bal["next_nonce"]))
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(self.client.get(f"/balance/{self.alice.addr}")
                         .get_json()["next_nonce"], 1)
        self.mine_via_api(self.alice.addr)
        bal = self.client.get(f"/balance/{self.bob.addr}").get_json()
        self.assertEqual(bal["balance"], 5 * C.UNITS_PER_COIN)
        self.assertEqual(self.client.get("/info").get_json()["height"], 2)

    def test_stale_job_rejected(self):
        old = self.client.get(f"/mining/work?address={self.alice.addr}").get_json()
        self.mine_via_api(self.alice.addr)
        route = stars.baseline_route([st["id"] for st in old["stars"]])
        r = self.client.post("/mining/submit", json={"job_id": old["job_id"], "route": route, "nonce": 0})
        self.assertIn(r.status_code, (409, 410))

    def test_route_map(self):
        self.mine_via_api(self.alice.addr)
        rows = self.client.get("/routes").get_json()
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["improvement_pct"], 0)
        self.assertEqual(len(rows[0]["route"]), stars.STARS_PER_PROBLEM)

    def test_bad_route_refused(self):
        work = self.client.get(f"/mining/work?address={self.alice.addr}").get_json()
        r = self.client.post("/mining/route", json={"job_id": work["job_id"], "route": [0, 1, 2]})
        self.assertEqual(r.status_code, 400)

    def test_chain_import(self):
        import node
        other = ch.Blockchain()
        clock = Clock()
        for _ in range(2):
            mine_next(other, self.bob.addr, clock)
        r = self.client.post("/chain/import", json=other.blocks).get_json()
        self.assertTrue(r["adopted"])
        self.assertEqual(node.chain.tip["hash"], other.tip["hash"])
        # a shorter chain is refused
        r = self.client.post("/chain/import", json=other.blocks[:2]).get_json()
        self.assertFalse(r["adopted"])
        # a tampered chain is refused
        bad = [dict(b) for b in other.blocks] + [dict(other.blocks[-1], height=3)]
        self.assertFalse(self.client.post("/chain/import", json=bad).get_json()["adopted"])
        self.assertEqual(self.client.post("/chain/import", json={"no": 1}).status_code, 400)

    def test_name_endpoints(self):
        work = self.client.get(f"/mining/work?address={self.alice.addr}&name=nova_7").get_json()
        self.assertIn("job_id", work)
        self.assertEqual(self.client.get("/name/NOVA_7").status_code, 404)   # not claimed until mined
        self.assertTrue(self.mine_via_api(self.alice.addr, name="NOVA_7").get_json()["ok"])
        self.assertEqual(self.client.get("/name/nova_7").get_json()["address"], self.alice.addr)
        self.assertEqual(self.client.get(f"/balance/{self.alice.addr}").get_json()["name"], "NOVA_7")
        r = self.client.get(f"/mining/work?address={self.bob.addr}&name=NOVA_7")
        self.assertEqual(r.status_code, 400)
        self.assertIn("taken", r.get_json()["error"])

    def test_bad_address_refused(self):
        r = self.client.get("/mining/work?address=nope")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
