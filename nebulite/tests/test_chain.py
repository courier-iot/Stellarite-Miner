"""Run from the node/ folder:  python -m unittest discover tests"""
import math
import os
import sys
import tempfile
import time
import unittest

os.environ["NEBULITE_DIFFICULTY_BITS"] = "6"  # easy mining for tests
os.environ["NAME_POW_BITS"] = "8"   # quick name-claim proof of work for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as C  # noqa: E402
import chain as ch  # noqa: E402
import trajectory as T  # noqa: E402
from traj_opt import optimise, plan  # noqa: E402
from crypto_utils import (address_from_pubkey, is_valid_address, new_private_key,  # noqa: E402
                          public_key_hex, sign)


def trajectory_for(prev_hash, seq=None, days=None, escape=None):
    """A block trajectory with claimed costs; the baseline unless one is given."""
    if seq is None:
        b = T.baseline(prev_hash)
        seq, days, escape = b["seq"], b["days"], b.get("escape")
    sc = ch.score_trajectory(prev_hash, seq, days, escape)
    tr = {"seq": seq, "days": days, "cost": sc["cost"], "baseline": sc["baseline"]}
    if escape is not None:
        tr["escape"] = escape
    return tr


def mine(template, trajectory=None):
    """Mine a template; uses the direct baseline trajectory unless one is given."""
    template = dict(template)
    template["trajectory"] = trajectory or trajectory_for(template["prev_hash"])
    tr = template["trajectory"]
    prefix = ch.header_prefix(template)
    target = ch.effective_target(template["target"], tr["cost"], tr["baseline"])
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
        block = dict(t, nonce=0, trajectory=trajectory_for(t["prev_hash"]))
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

    def test_mission_rules_enforced(self):
        t = self.bc.build_template(self.alice.addr, now=self.clock())
        prob = T.problem(t["prev_hash"])
        b = T.baseline(t["prev_hash"])
        tgt, start = prob["target"], prob["window_start"]
        bad = [
            ([T.EARTH], [start]),                                     # no destination
            ([3, tgt], [start, start + 900]),                         # not launched from Earth
            ([T.EARTH, 0, tgt], [start, start + 100, start + 2000]),  # Mercury flyby not allowed
            ([T.EARTH, tgt], [start - 400, start + 1000]),            # before the launch window
            ([T.EARTH, tgt], [start, start + prob["max_tof_days"] + 1]),  # too long
            ([T.EARTH, tgt], [start, start + 5]),                     # leg too short
            (b["seq"], [float(d) for d in b["days"]]),                # days must be whole numbers
        ]
        for seq, days in bad:
            with self.assertRaises(ch.ValidationError, msg=str((seq, days))):
                ch.score_trajectory(t["prev_hash"], seq, days)

    def test_claimed_costs_are_checked(self):
        now = self.clock()
        t = self.bc.build_template(self.alice.addr, now=now)
        tr = trajectory_for(t["prev_hash"])
        for bad in (dict(tr, cost=tr["cost"] - 50), dict(tr, baseline=tr["baseline"] + 50)):
            with self.assertRaises(ch.ValidationError):
                self.bc.add_block(mine(t, bad), now=now)

    def test_trajectory_is_bound_into_the_hash(self):
        now = self.clock()
        block = mine(self.bc.build_template(self.alice.addr, now=now))
        tr = dict(block["trajectory"])
        tr["days"] = [d + 1 for d in tr["days"]]
        tr.update({k: v for k, v in trajectory_for(block["prev_hash"], tr["seq"], tr["days"]).items()
                   if k in ("cost", "baseline")})
        with self.assertRaises(ch.ValidationError):
            self.bc.add_block(dict(block, trajectory=tr), now=now)

    def test_cheaper_trajectories_get_easier_targets(self):
        t = self.bc.build_template(self.alice.addr, now=self.clock())
        prob = T.problem(t["prev_hash"])
        seq, days, _ = optimise(prob, seconds=3, max_flybys=1, seed=2)
        tr = trajectory_for(t["prev_hash"], seq, days)
        base = trajectory_for(t["prev_hash"])
        self.assertLess(tr["cost"], base["cost"])
        self.assertGreater(ch.effective_target(t["target"], tr["cost"], tr["baseline"]), int(t["target"], 16))
        self.bc.add_block(mine(t, tr), now=self.clock() - 1)

    def test_mission_types(self):
        import hashlib
        seen = {}
        for k in range(200):
            h = hashlib.sha256(str(k).encode()).hexdigest()
            p = T.problem(h)
            seen.setdefault(p["type"], p)
            if p["type"] == "escape":
                continue
            planet_hash = h
            mt = T.MISSION_TYPES[p["type"]]
            self.assertEqual(p["time_penalty_mps_per_year"], mt["time_penalty_mps_per_year"])
            self.assertEqual(p["max_tof_days"], int(T.MAX_TOF_YEARS[p["target"]] * 365.25 * mt["tof_share"]))
        self.assertEqual(set(seen), {"science", "cargo", "crewed", "escape"})
        # the same trajectory costs more when time is dear
        b0 = T.baseline(planet_hash)                      # any real trajectory will do
        seq, days = b0["seq"], b0["days"]
        costs = {k: T.evaluate(seq, days, v["time_penalty_mps_per_year"])["cost"] for k, v in T.MISSION_TYPES.items()}
        self.assertLess(costs["cargo"], costs["science"])
        self.assertLess(costs["science"], costs["crewed"])
        # crewed baselines respect the shorter limit
        crewed = next(h for h in (hashlib.sha256(str(k).encode()).hexdigest() for k in range(200))
                      if T.problem(h)["type"] == "crewed")
        b = T.baseline(crewed)
        self.assertLessEqual(b["days"][1] - b["days"][0], T.problem(crewed)["max_tof_days"])

    @staticmethod
    def asymptote(r, v):
        """Outbound asymptote direction of the heliocentric hyperbola through state (r, v)."""
        import numpy as np
        r, v = np.array(r), np.array(v)
        mu = T.MU_SUN
        h = np.cross(r, v)
        evec = np.cross(v, h) / mu - r / np.linalg.norm(r)
        e = np.linalg.norm(evec)
        nu_inf = math.acos(-1 / e)
        p_hat, q_hat = evec / e, np.cross(h / np.linalg.norm(h), evec / e)
        return math.cos(nu_inf) * p_hat + math.sin(nu_inf) * q_hat

    def test_escape_aims_exactly_at_the_star(self):
        import numpy as np
        for name in ("Alpha Centauri", "TRAPPIST-1", "Vega", "Barnard's Star"):
            s_hat = tuple(next(x for x in T.STAR_TARGETS["stars"] if x["name"] == name)["dir"])
            r = T.planet_state(4, 11000)[0]                         # from Jupiter
            for long_way in (False, True):
                out = T.escape_from_point(r, s_hat, 25 / T.AU_PER_DAY_TO_KMS, long_way)
                if out:
                    self.assertLess(np.linalg.norm(self.asymptote(r, out[0]) - s_hat), 1e-9)
                    self.assertAlmostEqual(math.sqrt(out[0][0] ** 2 + out[0][1] ** 2 + out[0][2] ** 2) ** 2
                                           - 2 * T.MU_SUN / math.dist(r, (0, 0, 0)),
                                           (25 / T.AU_PER_DAY_TO_KMS) ** 2, delta=1e-12)   # energy -> v_inf
                dive = T.sun_dive(r, s_hat, 30 / T.AU_PER_DAY_TO_KMS, 0.05, long_way)
                if dive:
                    v_need, fall, burn, to_goal = dive
                    self.assertGreater(fall, 0)
                    # the infall orbit reaches exactly 0.05 AU (its perihelion)
                    hv = np.cross(r, v_need)
                    evec = np.cross(v_need, hv) / T.MU_SUN - np.array(r) / math.dist(r, (0, 0, 0))
                    q = (hv @ hv / T.MU_SUN) / (1 + np.linalg.norm(evec))
                    self.assertAlmostEqual(q, 0.05, delta=1e-10)

    def test_escape_time_to_550_au(self):
        """The hyperbola timing agrees with a direct numerical integration of the orbit."""
        s_hat = tuple(next(x for x in T.STAR_TARGETS["stars"] if x["name"] == "TRAPPIST-1")["dir"])
        r = T.planet_state(4, 11000)[0]
        v, days = T.escape_from_point(r, s_hat, 25 / T.AU_PER_DAY_TO_KMS)
        st, t, h = list(r) + list(v), 0.0, 1.0

        def acc(x):
            d = math.dist(x[:3], (0, 0, 0)) ** 3
            return [x[3], x[4], x[5]] + [-T.MU_SUN * x[k] / d for k in range(3)]
        while math.dist(st[:3], (0, 0, 0)) < T.ESCAPE_GOAL_AU:
            k1 = acc(st); k2 = acc([a + h / 2 * b for a, b in zip(st, k1)])
            k3 = acc([a + h / 2 * b for a, b in zip(st, k2)]); k4 = acc([a + h * b for a, b in zip(st, k3)])
            st = [a + h / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(st, k1, k2, k3, k4)]
            t += h
            h = min(20.0, h * 1.01)
        self.assertAlmostEqual(t, days, delta=21)                    # within one integration step

    def test_escape_blocks_are_always_solvable(self):
        import hashlib
        n = 0
        for k in range(160):
            h = hashlib.sha256(f"esc{k}".encode()).hexdigest()
            p = T.problem(h)
            if p["type"] != "escape":
                continue
            n += 1
            b = T.baseline(h)
            sc = ch.score_trajectory(h, b["seq"], b["days"], b["escape"])      # the baseline itself is valid
            self.assertEqual(sc["cost"], round(b["cost"]))
            star = next(x for x in T.STAR_TARGETS["stars"] if x["id"] == p["target_star"]["id"])
            self.assertEqual(p["target_star"]["dir"], star["dir"])
        self.assertGreater(n, 20)                                         # about 1 block in 5

    def test_escape_rules(self):
        import hashlib
        h = next(x for x in (hashlib.sha256(f"esc{k}".encode()).hexdigest() for k in range(100))
                 if T.problem(x)["type"] == "escape")
        b = T.baseline(h)
        with self.assertRaises(ch.ValidationError):                       # escape needs its parameters
            ch.score_trajectory(h, b["seq"], b["days"])
        too_fast = dict(b["escape"], vinf_ms=b["escape"]["vinf_ms"] + 20_000)
        with self.assertRaises(ch.ValidationError):                       # beyond the fuel budget
            ch.score_trajectory(h, b["seq"], b["days"], too_fast)
        with self.assertRaises(ch.ValidationError):                       # a Sun dive straight from launch
            ch.score_trajectory(h, [T.EARTH, T.SUN], b["days"][:1], {"vinf_ms": 5000, "rp_mau": 50})
        tr = trajectory_for(h)
        self.assertIn("escape", tr)
        self.assertIn("#vinf_ms=", ch.trajectory_text(tr))               # escape choices are bound into the hash

    def test_bonus_is_capped(self):
        base = "00" + "f" * 62
        capped = ch.effective_target(base, 1000, 1600)                    # 1.6x better: the most that counts
        self.assertEqual(ch.effective_target(base, 100, 1600), capped)   # 16x better earns no more

    def test_calendar_dates(self):
        self.assertEqual(T.date_of(0), "2000-01-01")
        self.assertEqual(T.date_of(9132), "2025-01-01")
        self.assertEqual(T.date_of(-0.6), "1999-12-31")

    def test_missions_change_every_block(self):
        a = mine_next(self.bc, self.alice.addr, self.clock)
        b = mine_next(self.bc, self.alice.addr, self.clock)
        self.assertNotEqual(T.problem(a["prev_hash"]), T.problem(b["prev_hash"]))

    def test_lambert_matches_hohmann(self):
        import math
        a2 = 1.523679
        h = math.pi * math.sqrt(((1 + a2) / 2) ** 3 / T.MU_SUN)
        self.assertAlmostEqual(h, 259, delta=1)
        v1, _ = T.lambert((1, 0, 0), (-a2 * math.cos(1e-3), -a2 * math.sin(1e-3), 0), h * 0.999)
        vinf = (math.hypot(*v1) - math.sqrt(T.MU_SUN)) * T.AU_PER_DAY_TO_KMS
        self.assertAlmostEqual(vinf, 2.94, delta=0.03)


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

    def mine_via_api(self, addr, plan_seconds=0.5, name=None):
        q = f"&name={name}" if name else ""
        work = self.client.get(f"/mining/work?address={addr}{q}").get_json()
        p = plan(work["mission"], seconds=plan_seconds, max_flybys=1, seed=1, start=work["baseline"])
        seq, days, esc = p["seq"], p["days"], p.get("escape")
        scored = self.client.post("/mining/trajectory",
                                  json={"job_id": work["job_id"], "seq": seq, "days": days, "escape": esc}).get_json()
        prefix, target = bytes.fromhex(scored["prefix"]), int(scored["target"], 16)
        nonce = 0
        while int.from_bytes(ch.pow_hash(prefix, nonce), "big") > target:
            nonce += 1
        return self.client.post("/mining/submit",
                                json={"job_id": work["job_id"], "seq": seq, "days": days, "escape": esc, "nonce": nonce})

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
        b = old["baseline"]
        r = self.client.post("/mining/submit",
                             json={"job_id": old["job_id"], "seq": b["seq"], "days": b["days"], "nonce": 0})
        self.assertIn(r.status_code, (409, 410))

    def test_web_map(self):
        page = self.client.get("/map")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"map/data", page.data)          # relative, so it works behind /pulsarite/ or /nebulite/
        self.mine_via_api(self.alice.addr)
        d = self.client.get("/map/data").get_json()
        self.assertEqual(d["height"], 1)
        rows = d["missions"]
        self.assertEqual(len(rows), 1)
        self.assertGreater(len(rows[0]["points"]), 2)

    def test_mission_log(self):
        self.mine_via_api(self.alice.addr)
        rows = self.client.get("/missions").get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"][0], "Earth")
        self.assertGreaterEqual(rows[0]["improvement_pct"], 0)
        self.assertIn(rows[0]["mission_type"], T.MISSION_TYPES)
        self.assertRegex(rows[0]["arrival_date"], r"^20\d\d-\d\d-\d\d$")
        self.assertEqual(rows[0]["encounters"][0]["planet"], "Earth")

    def test_bad_trajectory_refused(self):
        work = self.client.get(f"/mining/work?address={self.alice.addr}").get_json()
        r = self.client.post("/mining/trajectory", json={"job_id": work["job_id"], "seq": [2], "days": [1]})
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


class EphemerisTests(unittest.TestCase):
    """The planet model against real-world events."""

    @staticmethod
    def day(y, m, d):
        import datetime as dt
        return (dt.datetime(y, m, d) - dt.datetime(2000, 1, 1, 12)).total_seconds() / 86400

    def test_oppositions_to_the_hour(self):
        """Published opposition times (UT) for Mars, Jupiter and Saturn: VSOP87 lands within an hour.
        (The few minutes left are light-time and the J2000 vs of-date frame.)"""
        import math
        from datetime import datetime

        def gap(p, d):
            lon = lambda q: math.atan2(T.planet_state(q, d)[0][1], T.planet_state(q, d)[0][0])
            return (lon(p) - lon(2) + math.pi) % (2 * math.pi) - math.pi

        def hours(y, m, d, h, mi):
            return (datetime(y, m, d, h, mi) - datetime(2000, 1, 1, 12)).total_seconds() / 86400
        for p, when in [(3, (2018, 7, 27, 5, 7)), (3, (2022, 12, 8, 5, 41)), (4, (2023, 11, 3, 5, 3)),
                        (5, (2023, 8, 27, 8, 28))]:
            d0 = hours(*when)
            lo, hi = d0 - 3, d0 + 3                       # bisection on the longitude gap
            for _ in range(50):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if (gap(p, lo) < 0) == (gap(p, mid) < 0) else (lo, mid)
            self.assertLess(abs(lo - d0) * 24, 1.0, f"planet {p} opposition {when}")
        for p, date in [(6, (2023, 11, 13)), (7, (2023, 9, 19))]:   # Uranus, Neptune: right day
            d0 = self.day(*date)
            self.assertLess(min(abs(gap(p, d0 + k / 24)) for k in range(0, 24)), math.radians(0.01))

    def test_mars_2003_close_approach(self):
        """2003-08-27 09:51 UT, 0.372719 AU: the closest Mars has come in 60,000 years."""
        import math
        d0 = self.day(2003, 8, 27) + 9.85 / 24
        dist = min(math.dist(T.planet_state(3, d0 + k / 1440)[0], T.planet_state(2, d0 + k / 1440)[0])
                   for k in range(-30, 31))
        self.assertAlmostEqual(dist, 0.372719, delta=0.000002)

    def test_official_vsop87_vectors(self):
        """Spot checks from the VSOP87 authors' test file (vsop87.chk), to its 10 printed decimals."""
        cases = [(0, 2451545.0, (-0.1300934115, -0.4472876716, -0.0245983802)),
                 (0, 2415020.0, (-0.3897246931, -0.1502242199, 0.0236199373)),
                 (2, 2451545.0, (-0.1771354586, 0.9672416237, -3.9e-06)),
                 (4, 2378495.0, (-0.0180390004, 5.1317748839, -0.020044849)),
                 (5, 2415020.0, (-0.369597375, -10.0582398188, 0.1916854382)),
                 (7, 2451545.0, (16.8121116576, -24.9916630908, 0.1272190171)),
                 (7, 2268920.0, (11.1160686193, -28.0548309589, 0.3216732257))]
        for pid, jd, ref in cases:
            p, _ = T.planet_state(pid, jd - 2451545.0)
            for a, b in zip(p, ref):
                self.assertAlmostEqual(a, b, delta=1e-10)

    def test_voyager_flybys_were_nearly_free(self):
        for seq, dates in [([2, 4, 5], [(1977, 9, 5), (1979, 3, 5), (1980, 11, 12)]),
                           ([2, 4, 5, 6, 7], [(1977, 8, 20), (1979, 7, 9), (1981, 8, 26),
                                              (1986, 1, 24), (1989, 8, 25)])]:
            ev = T.evaluate(seq, [round(self.day(*d)) for d in dates])
            self.assertIsNotNone(ev)
            self.assertAlmostEqual(ev["launch_kms"], 10.2, delta=0.5)   # Voyager C3 ~102-106 km2/s2
            for fb in ev["flyby_kms"]:
                self.assertLess(fb, 0.5)


if __name__ == "__main__":
    unittest.main()
