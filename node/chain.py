"""The blockchain: blocks, transactions, proof-of-work, difficulty and state.

Model
-----
* Account-based ledger (balances + per-address nonce), simpler than UTXOs.
* Proof-of-work: sha256d(header_prefix + nonce as 8 bytes big-endian) <= target.
  The header prefix is everything except the nonce, so a miner (like the
  Android app) only needs the prefix bytes and the target to search for nonces.
* Fork choice: the valid chain with the most cumulative work wins.
"""
import json
import os
import statistics
import time

import config as C
from crypto_utils import (address_from_pubkey, canonical, is_valid_address,
                          sha256d, verify)

MAX_FUTURE_DRIFT = 2 * 60 * 60  # reject blocks timestamped >2h ahead


class ValidationError(Exception):
    pass


# ---- transactions -------------------------------------------------------

def tx_signing_bytes(tx: dict) -> bytes:
    return canonical({k: v for k, v in tx.items() if k != "sig"})


def txid(tx: dict) -> str:
    return sha256d(canonical(tx)).hex()


def tx_sender(tx: dict) -> str:
    return address_from_pubkey(tx["from"])


def check_tx_format(tx: dict):
    """Stateless checks: shape, amounts, signature."""
    required = {"from", "to", "amount", "fee", "nonce", "sig"}
    if not isinstance(tx, dict) or set(tx) != required:
        raise ValidationError("transaction has wrong fields")
    for k in ("amount", "fee", "nonce"):
        if not isinstance(tx[k], int) or isinstance(tx[k], bool) or tx[k] < 0:
            raise ValidationError(f"bad {k}")
    if tx["amount"] <= 0:
        raise ValidationError("amount must be positive")
    if tx["fee"] < C.MIN_FEE:
        raise ValidationError(f"fee below minimum {C.MIN_FEE}")
    if not is_valid_address(tx["to"]):
        raise ValidationError("bad recipient address")
    if not isinstance(tx["from"], str) or not verify(tx["from"], tx_signing_bytes(tx), tx["sig"]):
        raise ValidationError("bad signature")


def block_reward(height: int) -> int:
    return C.BLOCK_REWARD >> (height // C.HALVING_INTERVAL)


# ---- blocks -------------------------------------------------------------

def tx_root(txs) -> str:
    return sha256d(b"".join(bytes.fromhex(txid(t)) for t in txs)).hex()


def header_prefix(block: dict) -> bytes:
    return (
        f"{C.COIN_NAME}|{block['height']}|{block['prev_hash']}|{block['timestamp']}|"
        f"{block['target']}|{block['tx_root']}|"
    ).encode()


def pow_hash(prefix: bytes, nonce: int) -> bytes:
    return sha256d(prefix + nonce.to_bytes(8, "big"))


def block_hash(block: dict) -> str:
    return pow_hash(header_prefix(block), block["nonce"]).hex()


def work(target_hex: str) -> int:
    return (1 << 256) // (int(target_hex, 16) + 1)


def make_genesis() -> dict:
    coinbase = {"coinbase": True, "to": "genesis", "amount": 0,
                "height": 0, "memo": C.GENESIS_MESSAGE}
    block = {
        "height": 0,
        "prev_hash": "0" * 64,
        "timestamp": C.GENESIS_TIMESTAMP,
        "target": format(C.GENESIS_TARGET, "064x"),
        "txs": [coinbase],
        "nonce": 0,
    }
    block["tx_root"] = tx_root(block["txs"])
    block["hash"] = block_hash(block)
    return block


class State:
    """Balances and nonces after applying a chain of blocks."""

    def __init__(self):
        self.balances = {}
        self.nonces = {}

    def copy(self):
        s = State()
        s.balances = dict(self.balances)
        s.nonces = dict(self.nonces)
        return s

    def balance(self, addr):
        return self.balances.get(addr, 0)

    def nonce(self, addr):
        return self.nonces.get(addr, 0)

    def apply_tx(self, tx):
        """Apply a regular transaction, raising ValidationError if invalid here."""
        check_tx_format(tx)
        sender = tx_sender(tx)
        if tx["nonce"] != self.nonce(sender):
            raise ValidationError(f"bad nonce (expected {self.nonce(sender)})")
        cost = tx["amount"] + tx["fee"]
        if self.balance(sender) < cost:
            raise ValidationError("insufficient balance")
        self.balances[sender] = self.balance(sender) - cost
        self.balances[tx["to"]] = self.balance(tx["to"]) + tx["amount"]
        self.nonces[sender] = tx["nonce"] + 1

    def apply_block_txs(self, block):
        txs = block["txs"]
        if not txs or not txs[0].get("coinbase"):
            raise ValidationError("first transaction must be coinbase")
        fees = 0
        for tx in txs[1:]:
            if tx.get("coinbase"):
                raise ValidationError("extra coinbase")
            self.apply_tx(tx)
            fees += tx["fee"]
        cb = txs[0]
        if block["height"] == 0:
            return
        if set(cb) != {"coinbase", "to", "amount", "height"} or cb["coinbase"] is not True:
            raise ValidationError("bad coinbase fields")
        if cb["height"] != block["height"]:
            raise ValidationError("coinbase height mismatch")
        if not is_valid_address(cb["to"]):
            raise ValidationError("bad coinbase address")
        if cb["amount"] != block_reward(block["height"]) + fees:
            raise ValidationError("wrong coinbase amount")
        self.balances[cb["to"]] = self.balance(cb["to"]) + cb["amount"]


def next_target(blocks: list) -> str:
    """Difficulty for the block after blocks[-1]."""
    tip = blocks[-1]
    height = tip["height"] + 1
    if height % C.RETARGET_INTERVAL != 0:
        return tip["target"]
    first = blocks[max(1, height - C.RETARGET_INTERVAL)]  # skip genesis timestamp
    intervals = tip["height"] - first["height"]
    if intervals <= 0:
        return tip["target"]
    expected = intervals * C.TARGET_BLOCK_SECONDS
    actual = tip["timestamp"] - first["timestamp"]
    actual = max(expected // C.MAX_RETARGET_FACTOR, min(actual, expected * C.MAX_RETARGET_FACTOR))
    new = int(tip["target"], 16) * actual // expected
    return format(max(1, min(new, C.MAX_TARGET)), "064x")


def median_time_past(blocks: list) -> int:
    return int(statistics.median(b["timestamp"] for b in blocks[-11:]))


def validate_block(block: dict, blocks: list, state: State, now=None) -> State:
    """Check block against chain `blocks`; return the new state if valid."""
    now = int(now if now is not None else time.time())
    tip = blocks[-1]
    keys = {"height", "prev_hash", "timestamp", "target", "tx_root", "txs", "nonce", "hash"}
    if not isinstance(block, dict) or set(block) != keys:
        raise ValidationError("block has wrong fields")
    if block["height"] != tip["height"] + 1:
        raise ValidationError("wrong height")
    if block["prev_hash"] != tip["hash"]:
        raise ValidationError("does not extend tip")
    if not isinstance(block["nonce"], int) or not 0 <= block["nonce"] < 2**64:
        raise ValidationError("bad nonce")
    if not isinstance(block["timestamp"], int):
        raise ValidationError("bad timestamp")
    if block["timestamp"] <= median_time_past(blocks):
        raise ValidationError("timestamp too old")
    if block["timestamp"] > now + MAX_FUTURE_DRIFT:
        raise ValidationError("timestamp too far in future")
    if block["target"] != next_target(blocks):
        raise ValidationError("wrong difficulty target")
    if not isinstance(block["txs"], list) or len(block["txs"]) > C.MAX_TXS_PER_BLOCK + 1:
        raise ValidationError("bad transaction list")
    if block["tx_root"] != tx_root(block["txs"]):
        raise ValidationError("tx_root mismatch")
    h = block_hash(block)
    if block["hash"] != h:
        raise ValidationError("hash mismatch")
    if int(h, 16) > int(block["target"], 16):
        raise ValidationError("insufficient proof of work")
    new_state = state.copy()
    new_state.apply_block_txs(block)
    return new_state


class Blockchain:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self.blocks = [make_genesis()]
        self.state = State()
        self.mempool = {}  # txid -> tx
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            self._load()

    # -- persistence --
    @property
    def _path(self):
        return os.path.join(self.data_dir, "chain.json")

    def _load(self):
        if not os.path.exists(self._path):
            return
        with open(self._path) as f:
            saved = json.load(f)
        if not self.replace_chain(saved, require_more_work=False):
            raise RuntimeError("saved chain is invalid; delete it to start fresh")

    def save(self):
        if not self.data_dir:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.blocks, f)
        os.replace(tmp, self._path)

    # -- queries --
    @property
    def tip(self):
        return self.blocks[-1]

    def total_work(self, blocks=None):
        return sum(work(b["target"]) for b in (blocks or self.blocks))

    # -- mutations --
    def add_block(self, block, now=None):
        self.state = validate_block(block, self.blocks, self.state, now)
        self.blocks.append(block)
        for tx in block["txs"][1:]:
            self.mempool.pop(txid(tx), None)
        self._prune_mempool()
        self.save()

    def replace_chain(self, candidate, require_more_work=True):
        """Adopt `candidate` if it is valid and has more work. Returns True if adopted."""
        if not isinstance(candidate, list) or not candidate or candidate[0] != make_genesis():
            return False
        if require_more_work and self.total_work(candidate) <= self.total_work():
            return False
        blocks, state = [candidate[0]], State()
        try:
            for b in candidate[1:]:
                state = validate_block(b, blocks, state)
                blocks.append(b)
        except (ValidationError, KeyError, TypeError, ValueError):
            return False
        old_txs = [tx for b in self.blocks[1:] for tx in b["txs"][1:]]
        self.blocks, self.state = blocks, state
        for tx in old_txs:  # return orphaned transactions to the mempool
            self.mempool.setdefault(txid(tx), tx)
        self._prune_mempool()
        self.save()
        return True

    def add_transaction(self, tx):
        check_tx_format(tx)
        sender = tx_sender(tx)
        if tx["nonce"] < self.state.nonce(sender):
            raise ValidationError("nonce already used")
        if tx["amount"] + tx["fee"] > self.state.balance(sender):
            raise ValidationError("insufficient balance")
        tid = txid(tx)
        self.mempool[tid] = tx
        return tid

    def _prune_mempool(self):
        for tid, tx in list(self.mempool.items()):
            try:
                check_tx_format(tx)
                if tx["nonce"] < self.state.nonce(tx_sender(tx)):
                    raise ValidationError("stale")
            except ValidationError:
                del self.mempool[tid]

    # -- mining --
    def build_template(self, miner_address, now=None):
        """A block ready to mine except for its nonce."""
        if not is_valid_address(miner_address):
            raise ValidationError("bad miner address")
        now = int(now if now is not None else time.time())
        state = self.state.copy()
        chosen, fees = [], 0
        ordered = sorted(self.mempool.values(),
                         key=lambda t: (tx_sender(t), t["nonce"]))
        for tx in ordered:
            if len(chosen) >= C.MAX_TXS_PER_BLOCK:
                break
            try:
                state.apply_tx(tx)
            except ValidationError:
                continue
            chosen.append(tx)
            fees += tx["fee"]
        height = self.tip["height"] + 1
        coinbase = {"coinbase": True, "to": miner_address,
                    "amount": block_reward(height) + fees, "height": height}
        block = {
            "height": height,
            "prev_hash": self.tip["hash"],
            "timestamp": max(now, median_time_past(self.blocks) + 1),
            "target": next_target(self.blocks),
            "txs": [coinbase] + chosen,
            "nonce": 0,
        }
        block["tx_root"] = tx_root(block["txs"])
        block["hash"] = ""
        return block
