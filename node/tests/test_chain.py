"""Run from the node/ folder:  python -m unittest discover tests"""
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import unittest

os.environ["PULSARITE_DIFFICULTY_BITS"] = "6"  # easy mining for tests
os.environ["NAME_POW_BITS"] = "8"   # quick name-claim proof of work for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as C  # noqa: E402
import chain as ch  # noqa: E402
import stars  # noqa: E402
import scouts as SC  # noqa: E402
from route_opt import optimise  # noqa: E402
from crypto_utils import (address_from_pubkey, is_valid_address, new_private_key,  # noqa: E402
                          public_key_hex, sign)



def work_for(prev_hash, scouted=()):
    """The planning data a node's /mining/work gives a miner (scouted stops are flown past)."""
    prob, st = stars.problem(prev_hash), stars.stops(prev_hash)
    return {"stars": [dict(stars.CATALOG[i]) for i in prob], "stops": [s for s in st if s not in scouted],
            "probe_speed_mly_per_year": stars.SPEED, "probe_accel_mly_per_year2": C.PROBE_ACCEL_MLY_PER_YEAR2,
            "survey_years": C.SURVEY_YEARS, "survey_years_per_planet": C.SURVEY_YEARS_PER_PLANET,
            "dv_budget_pct_c": C.DV_BUDGET_PCT_C, "launch_t": stars.LAUNCH_T,
            "intercept_iterations": stars.INTERCEPT_ITERATIONS}


def base_plan(prev_hash):
    """The greedy baseline plan for a block (always valid)."""
    return stars.baseline_route(stars.problem(prev_hash), stars.stops(prev_hash))


def mine(template, route=None):
    """Mine a template; uses the greedy baseline route unless one is given."""
    template = dict(template)
    template["route"] = route or base_plan(template["prev_hash"])
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

    def name_claim(self, name, nonce, work=None):
        t = {"type": "name", "from": self.pub, "name": name, "nonce": nonce, "work": 0}
        if work is None:
            while not ch.name_claim_pow_ok(t):
                t["work"] += 1
        else:
            t["work"] = work
        t["sig"] = sign(self.key, ch.tx_signing_bytes(t))
        return t

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
        block = dict(t, nonce=0, route=base_plan(t["prev_hash"]))
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
        outsider = next(i for i in range(len(stars.CATALOG)) if i not in problem)
        for bad in (problem[:-1], problem[:-1] + problem[:1], problem[:-1] + [outsider]):
            with self.assertRaises(ch.ValidationError):
                ch.route_score(t["prev_hash"], [[s, 5] for s in bad])
        for bad in (problem, [[s, 0] for s in problem], [[s, 11] for s in problem], [[s, True] for s in problem]):
            with self.assertRaises(ch.ValidationError):            # plain ids, or speeds outside 1-10% of c
                ch.route_score(t["prev_hash"], bad)

    def test_fuel_budget(self):
        t = self.bc.build_template(self.alice.addr, now=self.clock())
        problem = stars.problem(t["prev_hash"])
        with self.assertRaises(ch.ValidationError) as e:          # full speed everywhere needs ~0.9c of delta-v
            ch.route_score(t["prev_hash"], [[s, 10] for s in problem])
        self.assertIn("fuel", str(e.exception))
        plan = base_plan(t["prev_hash"])
        sc = ch.route_score(t["prev_hash"], plan)
        self.assertLessEqual(sc["dv"], stars.DV_BUDGET)
        faster = [[s, plan[0][1] + 1] for s, _ in plan]           # the baseline is the fastest uniform speed that fits
        self.assertGreater(stars.route_dv(faster, stars.stops(t["prev_hash"])), stars.DV_BUDGET)

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
        from route_opt import optimise_plan
        order = [problem[i] for i in optimise(pts, seconds=0.5, seed=3)]
        best = optimise_plan(order, work_for(t["prev_hash"]), 0.5)        # order + speeds within the fuel budget
        sc_base = ch.route_score(t["prev_hash"], base_plan(t["prev_hash"]))
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
        t_arr, p, u, dv = stars.intercept(stars.SOL, stars.LAUNCH_T, sid)
        self.assertEqual(p, stars.pos(sid, t_arr))
        self.assertEqual((u, dv), (stars.V, stars.V))      # a long flyby leg ends at cruise speed
        d = stars.distance_uly(stars.SOL, p)               # 10 years to 0.1c over 0.5 ly, then cruise
        self.assertAlmostEqual(t_arr - stars.LAUNCH_T, 10_000 + (d - 500_000) * 1000 // stars.V, delta=2)

    def test_probe_kinematics(self):
        LY = 1_000_000                                     # micro-light-years per light-year
        V, A = stars.V, stars.A
        self.assertEqual(stars.leg(10 * LY, 0, V, True), (110_000, 0, 2 * V))     # 10 up + 90 cruise + 10 down
        self.assertEqual(stars.leg(10 * LY, V, V, False), (100_000, V, 0))        # pure cruise: no fuel
        self.assertEqual(stars.leg(10 * LY, 0, V, False), (105_000, V, V))        # launch ramp costs 5 years
        self.assertEqual(stars.leg(10 * LY, V, V // 2, False)[1:], (V // 2, V // 2))   # slowing down burns fuel too
        half = stars.leg(10 * LY, 0, V // 2, True)                               # at 5% of c: 5 up, 195 cruise, 5 down
        self.assertEqual(half, (205_000, 0, V))
        t, u, _ = stars.leg(LY // 10, 0, V, True)                                # short hop: never reaches 0.1c
        self.assertAlmostEqual(t, 2000 * math.sqrt(10), delta=2)
        self.assertEqual(u, 0)
        t, _, _ = stars.leg(LY // 10, V, V, True)                                # too fast to stop: overshoot and return
        self.assertAlmostEqual(t, 10_000 + 2000 * math.sqrt(40), delta=2)
        t, u, dv = stars.leg(LY // 8, 0, V, False)                               # partial acceleration
        self.assertEqual(u, math.isqrt(2 * A * (LY // 8)))
        self.assertEqual((t, dv), (u * 1000 // A, u))
        for d in range(0, 3 * LY, LY // 50):                                     # longer legs never take less time...
            for u0 in (0, V // 3, V):
                for c in (V // 10, V // 2, V):
                    for stop in (False, True):
                        if stop and u0 * u0 // (2 * A) >= d:                     # ...unless too fast to stop (overshoot)
                            continue
                        self.assertLessEqual(stars.leg(d, u0, c, stop)[0], stars.leg(d + LY // 50, u0, c, stop)[0])

    def test_survey_stops(self):
        h = "cd" * 32
        st = stars.stops(h)
        self.assertEqual(len(st), stars.SURVEY_STOPS)
        self.assertEqual(st, stars.stops(h))
        self.assertTrue(set(st) <= set(stars.problem(h)))
        plan = stars.baseline_route(stars.problem(h), st)
        self.assertGreater(stars.route_time(plan, st), stars.route_time(plan))   # braking and surveying cost time
        for sid, arrive, _, u, _, depart in stars.route_legs(plan, st):
            if sid in st:
                self.assertEqual(u, 0)
                self.assertEqual(depart - arrive, stars.survey_t(sid))           # 5 years + 2 per known planet
            else:
                self.assertEqual(depart, arrive)

    def test_planet_systems(self):
        trappist = next(s["id"] for s in stars.CATALOG if s["name"] == "TRAPPIST-1")
        sirius = next(s["id"] for s in stars.CATALOG if s["name"] == "Sirius")
        self.assertEqual(stars.CATALOG[trappist]["planets"], 7)
        self.assertEqual(stars.survey_t(trappist), 19_000)            # 5 years + 7 planets x 2
        self.assertEqual(stars.survey_t(sirius), 5_000)
        # stops favour planet hosts: over many blocks, hosts are stops far more often than their share
        hosts = hits = picks = in_problems = 0
        for k in range(300):
            h = hashlib.sha256(str(k).encode()).hexdigest()
            prob, st = stars.problem(h), stars.stops(h)
            in_problems += sum(stars.CATALOG[s]["planets"] > 0 for s in prob) / len(prob)
            hits += sum(stars.CATALOG[s]["planets"] > 0 for s in st)
            picks += len(st)
        self.assertGreater(hits / picks, 1.4 * in_problems / 300)

    def test_miner_timing_matches_node(self):
        from route_opt import plan_eval, optimise_plan
        for h in ("ab" * 32, "12" * 32, "f0" * 32):
            prob, st = stars.problem(h), stars.stops(h)
            work = {"stars": [dict(stars.CATALOG[i]) for i in prob], "stops": st,
                    "probe_speed_mly_per_year": stars.SPEED,
                    "probe_accel_mly_per_year2": C.PROBE_ACCEL_MLY_PER_YEAR2,
                    "survey_years": C.SURVEY_YEARS, "dv_budget_pct_c": C.DV_BUDGET_PCT_C,
                    "survey_years_per_planet": C.SURVEY_YEARS_PER_PLANET,
                    "launch_t": stars.LAUNCH_T, "intercept_iterations": stars.INTERCEPT_ITERATIONS}
            base = stars.baseline_route(prob, st)
            tuned = optimise_plan([s for s, _ in base], work, 0.3)
            for plan in (base, base[::-1], [[s, 1 + s % 10] for s in prob], tuned):
                self.assertEqual(plan_eval(plan, work), (stars.route_time(plan, st), stars.route_dv(plan, st)))
            self.assertLess(stars.route_time(tuned, st), stars.route_time(base, st))
            self.assertLessEqual(stars.route_dv(tuned, st), stars.DV_BUDGET)

    def test_name_claim_without_coins(self):
        carol = Wallet()                          # no coins at all
        self.bc.add_transaction(carol.name_claim("CAROL", 0))
        mine_next(self.bc, self.alice.addr, self.clock)   # anyone's block includes it
        self.assertEqual(self.bc.state.name_owner("CAROL"), carol.addr)
        self.assertEqual(self.bc.state.balance(carol.addr), 0)
        # replay of the same claim is refused (nonce used)
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(carol.name_claim("CAROL", 0))
        # someone else can't claim it
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(self.bob.name_claim("CAROL", 0))

    def test_name_claim_needs_proof_of_work_and_signature(self):
        dave = Wallet()
        bad_work = next(w for w in range(10_000) if not ch.name_claim_pow_ok(
            {"type": "name", "from": dave.pub, "name": "DAVE", "nonce": 0, "work": w}))
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(dave.name_claim("DAVE", 0, work=bad_work))
        forged = dict(dave.name_claim("DAVE", 0), name="DAVID")    # signature no longer matches
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(forged)
        with self.assertRaises(ch.ValidationError):
            self.bc.add_transaction(dave.name_claim("x", 0))        # bad name format

    def test_competing_name_claims(self):
        e1, e2 = Wallet(), Wallet()
        self.bc.add_transaction(e1.name_claim("ECHO", 0))
        with self.assertRaises(ch.ValidationError):                 # second claim waits behind the first
            self.bc.add_transaction(e2.name_claim("ECHO", 0))
        mine_next(self.bc, self.alice.addr, self.clock)
        self.assertEqual(self.bc.state.name_owner("ECHO"), e1.addr)
        # names claimed by transaction survive re-validation from genesis
        other = ch.Blockchain()
        self.assertTrue(other.replace_chain(self.bc.blocks))
        self.assertEqual(other.state.name_owner("ECHO"), e1.addr)

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
        order = [work["stars"][i]["id"] for i in optimise(pts, seconds=optimise_seconds, seed=1)]
        from route_opt import optimise_plan
        route = optimise_plan(order, work, optimise_seconds)
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
        route = old["baseline_route"]
        r = self.client.post("/mining/submit", json={"job_id": old["job_id"], "route": route, "nonce": 0})
        self.assertIn(r.status_code, (409, 410))

    def test_web_map(self):
        page = self.client.get("/map")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"map/data", page.data)          # relative, so it works behind /pulsarite/ or /nebulite/
        self.mine_via_api(self.alice.addr)
        d = self.client.get("/map/data").get_json()
        self.assertEqual(d["height"], 1)
        rows = d["routes"]
        self.assertEqual(len(rows), 1)
        self.assertGreater(len(rows[0]["points"]), 2)

    def test_route_map(self):
        self.mine_via_api(self.alice.addr)
        rows = self.client.get("/routes").get_json()
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["improvement_pct"], 0)
        self.assertEqual(len(rows[0]["route"]), stars.STARS_PER_PROBLEM)

    def test_bad_route_refused(self):
        work = self.client.get(f"/mining/work?address={self.alice.addr}").get_json()
        r = self.client.post("/mining/route", json={"job_id": work["job_id"], "route": [[0, 5], [1, 5], [2, 5]]})
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


class ScoutTests(unittest.TestCase):
    """Nebulite escape missions cited as scouts by Pulsarite blocks."""

    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bc = ch.Blockchain(cls.tmp.name)
        cls.clock = Clock()
        cls.t = cls.bc.build_template(Wallet().addr, now=cls.clock())
        cls.stops = stars.stops(cls.t["prev_hash"])
        tool = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "make_scouts.py")
        run = lambda stars_, bits, n, tag: json.loads(subprocess.run(
            [sys.executable, tool, json.dumps(stars_), str(bits), str(n), tag],
            capture_output=True, text=True, check=True).stdout)
        cls.proofs = run(cls.stops, 16, 2, "scoutA")           # real Nebulite escape blocks toward our stops
        cls.weak = run(cls.stops, 1, 1, "scoutB")[0]           # far too little work
        cls.other = run([s for s in range(len(stars.CATALOG)) if s not in cls.stops], 16, 1, "scoutC")[0]

    def test_verify(self):
        v = SC.verify(self.proofs[0])
        self.assertIn(v["star"], self.stops)
        self.assertEqual(v["hash"], SC.nebulite_hash(self.proofs[0]))
        bad = json.loads(json.dumps(self.proofs[0])); bad["nonce"] += 1
        with self.assertRaises(SC.ScoutError):                 # tampering breaks the proof of work
            SC.verify(bad)
        bad = json.loads(json.dumps(self.proofs[0])); bad["trajectory"]["escape"]["vinf_ms"] += 50
        with self.assertRaises(SC.ScoutError):                 # ... or the physics
            SC.verify(bad)

    def test_heliopause_run_is_not_a_scout(self):
        import subprocess
        tool = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "make_scouts.py")
        out = subprocess.run([sys.executable, tool, "[]", "8", "1", "helio"], capture_output=True, text=True, check=True,
                             env=dict(os.environ, MISSION_TYPE="heliopause")).stdout
        proof = json.loads(out)[0]
        self.assertIn("escape", proof["trajectory"])           # same shape as an escape block ...
        with self.assertRaises(SC.ScoutError):                 # ... but it isn't aimed at a star
            SC.verify(proof)

    def plan_for(self, scouted):
        from route_opt import optimise, optimise_plan
        prob = stars.problem(self.t["prev_hash"])
        order = [prob[i] for i in optimise([stars.pos(i) for i in prob], seconds=0.4, seed=5)]
        return optimise_plan(order, work_for(self.t["prev_hash"], scouted), 0.6)

    def test_scouted_stop_is_flown_past(self):
        v = SC.verify(self.proofs[0])
        plan = self.plan_for([v["star"]])
        sc = ch.route_score(self.t["prev_hash"], plan, [v["star"]])
        self.assertNotIn(v["star"], sc["stops"])
        unscouted = stars.route_time(plan, self.stops)
        self.assertLess(sc["mission_time"], unscouted)          # no braking or survey at the scouted star
        self.assertGreaterEqual(sc["length"], unscouted * C.SCOUT_TIME_CAP_DEN / C.SCOUT_TIME_CAP_NUM - 1)

    def test_block_with_scout_is_accepted_and_scout_cannot_be_reused(self):
        v = SC.verify(self.proofs[0])
        tmp = tempfile.TemporaryDirectory()
        bc = ch.Blockchain(tmp.name)
        t = bc.build_template(Wallet().addr, now=self.clock(), scouts=[self.proofs[0]])
        t["route"] = self.plan_for([v["star"]])
        sc = ch.route_score(t["prev_hash"], t["route"], [v["star"]])
        prefix = ch.header_prefix(t)
        target = ch.effective_target(t["target"], sc["length"], sc["baseline"])
        nonce = 0
        while int.from_bytes(ch.pow_hash(prefix, nonce), "big") > target:
            nonce += 1
        block = dict(t, nonce=nonce)
        block["hash"] = ch.block_hash(block)
        bc.add_block(block, now=self.clock())
        self.assertIn(v["hash"], bc.state.used_scouts)
        # the scout's Nebulite miner is paid on Pulsarite, at the same wallet's plsr address
        self.assertEqual(v["reward_to"], "plsr" + v["miner"][4:])
        self.assertTrue(is_valid_address(v["reward_to"]))
        share = ch.block_reward(block["height"]) * C.SCOUT_REWARD_PCT // 100
        self.assertEqual(bc.state.balance(v["reward_to"]), share)
        self.assertEqual(bc.state.balance(block["txs"][0]["to"]), ch.block_reward(block["height"]))   # miner keeps all
        row = bc.route_stats(1)[0]
        self.assertEqual(row["scouted_ids"], [v["star"]])
        # the header commits to the scouts: dropping them changes the hash
        self.assertNotEqual(ch.block_hash(dict(block, scouts=[])), block["hash"])
        # citing the same Nebulite block again is refused
        with self.assertRaises(ch.ValidationError):
            ch.check_scouts(dict(block, prev_hash=block["prev_hash"]), bc.state)

    def test_scout_reward_must_be_exact(self):
        v = SC.verify(self.proofs[0])
        tmp = tempfile.TemporaryDirectory()
        bc = ch.Blockchain(tmp.name)
        t = bc.build_template(Wallet().addr, now=self.clock(), scouts=[self.proofs[0]])
        t["route"] = self.plan_for([v["star"]])
        for bad in ([], [{"to": t["txs"][0]["to"], "amount": t["txs"][0]["scout_rewards"][0]["amount"]}],
                    [{"to": v["reward_to"], "amount": t["txs"][0]["scout_rewards"][0]["amount"] * 2}]):
            b = json.loads(json.dumps(t))
            b["txs"][0]["scout_rewards"] = bad
            b["tx_root"] = ch.tx_root(b["txs"])
            sc = ch.route_score(b["prev_hash"], b["route"], [v["star"]])
            prefix, target = ch.header_prefix(b), ch.effective_target(b["target"], sc["length"], sc["baseline"])
            nonce = 0
            while int.from_bytes(ch.pow_hash(prefix, nonce), "big") > target:
                nonce += 1
            b["nonce"] = nonce
            b["hash"] = ch.block_hash(b)
            with self.assertRaises(ch.ValidationError):
                bc.add_block(b, now=self.clock())
        # a proof whose coinbase was swapped for someone else's is refused
        forged = json.loads(json.dumps(self.proofs[0]))
        other = "nblt" + Wallet().addr[4:]                      # someone else's (valid) Nebulite address
        self.assertNotEqual(other, forged["coinbase"]["to"])
        forged["coinbase"]["to"] = other
        with self.assertRaises(SC.ScoutError):
            SC.verify(forged)

    def test_scout_rules(self):
        st = ch.State()
        base = dict(self.t)
        # work rule: a scout needs at least 1/3 of the work the citing block needs
        block_target = int(base["target"], 16)
        self.assertFalse(ch.scout_work_ok(SC.verify(self.weak), block_target))
        self.assertTrue(ch.scout_work_ok(SC.verify(self.proofs[0]), block_target))
        with self.assertRaises(ch.ValidationError):            # aimed at a star that isn't one of our stops
            ch.check_scouts(dict(base, scouts=[self.other]), st)
        with self.assertRaises(ch.ValidationError):            # at most SCOUT_MAX_PER_BLOCK, and not empty
            ch.check_scouts(dict(base, scouts=[]), st)
        if SC.verify(self.proofs[0])["star"] == SC.verify(self.proofs[1])["star"]:
            with self.assertRaises(ch.ValidationError):        # one scout per survey star
                ch.check_scouts(dict(base, scouts=self.proofs), st)
        self.assertEqual(len(ch.check_scouts(dict(base, scouts=[self.proofs[0]]), st)), 1)

    def test_work_with_scouts_via_api(self):
        import node
        tmp = tempfile.TemporaryDirectory()
        node.chain = ch.Blockchain(tmp.name)
        node.jobs.clear()
        saved = node.fetch_scouts
        node.fetch_scouts = lambda prev_hash: self.proofs + [self.weak, self.other]   # as if from a Nebulite node
        try:
            client = node.app.test_client()
            work = client.get(f"/mining/work?address={Wallet().addr}").get_json()
            self.assertGreaterEqual(len(work["scouted"]), 1)
            for s in work["scouted"]:
                self.assertNotIn(s, work["stops"])
                self.assertIn(s, work["survey_stops"])
            from route_opt import optimise, optimise_plan
            pts = [(s["x"], s["y"], s["z"]) for s in work["stars"]]
            order = [work["stars"][i]["id"] for i in optimise(pts, seconds=0.3, seed=1)]
            route = optimise_plan(order, work, 0.5)
            scored = client.post("/mining/route", json={"job_id": work["job_id"], "route": route}).get_json()
            prefix, target = bytes.fromhex(scored["prefix"]), int(scored["target"], 16)
            nonce = 0
            while int.from_bytes(ch.pow_hash(prefix, nonce), "big") > target:
                nonce += 1
            r = client.post("/mining/submit", json={"job_id": work["job_id"], "route": route, "nonce": nonce}).get_json()
            self.assertTrue(r["ok"], r)
            self.assertEqual(node.chain.route_stats(1)[0]["scouted_ids"], work["scouted"])
        finally:
            node.fetch_scouts = saved


if __name__ == "__main__":
    unittest.main()
