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
from crypto_utils import (address_from_pubkey, is_valid_address, new_private_key,  # noqa: E402
                          public_key_hex, sign)


def mine(template):
    prefix, target = ch.header_prefix(template), int(template["target"], 16)
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
        block = dict(t, nonce=0)
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

    def mine_via_api(self, addr):
        work = self.client.get(f"/mining/work?address={addr}").get_json()
        prefix, target = bytes.fromhex(work["prefix"]), int(work["target"], 16)
        nonce = 0
        while int.from_bytes(ch.pow_hash(prefix, nonce), "big") > target:
            nonce += 1
        return self.client.post("/mining/submit", json={"job_id": work["job_id"], "nonce": nonce})

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
        r = self.client.post("/mining/submit", json={"job_id": old["job_id"], "nonce": 0})
        self.assertIn(r.status_code, (409, 410))

    def test_bad_address_refused(self):
        r = self.client.get("/mining/work?address=nope")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
