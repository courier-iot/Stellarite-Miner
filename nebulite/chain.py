"""Nebulite blockchain: blocks, transactions, trajectory proof-of-work, difficulty and state.

Model
-----
* Account-based ledger (balances + per-address nonce), simpler than UTXOs.
* Proof of useful work: every block carries a spacecraft trajectory for a
  mission (Earth to an outer planet, flybys allowed) picked from the previous
  block's hash (see trajectory.py). A block is valid when
      sha256d(header_prefix + nonce as 8 bytes big-endian) <= effective target
  where effective target = base target * (baseline cost / trajectory cost)^12.
  Cheaper trajectories (less fuel, less travel time) make the hash target
  exponentially easier. Costs are claimed in the block and re-checked by every
  node within COST_TOLERANCE_MPS, so floating-point differences between
  computers can't split the chain.
* Fork choice: the valid chain with the most cumulative work wins.
"""
import json
import os
import re
import statistics
import time

import config as C
import trajectory as T
from crypto_utils import (address_from_pubkey, canonical, is_valid_address,
                          sha256d, verify)

MAX_FUTURE_DRIFT = 2 * 60 * 60  # reject blocks timestamped >2h ahead
NAME_RE = re.compile(r"^[A-Z0-9_]{3,16}$")   # usernames: 3-16 of A-Z, 0-9, _


def check_name(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValidationError("names are 3-16 characters: A-Z, 0-9 and _")


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


def trajectory_text(tr) -> str:
    if not tr:
        return ""
    return (",".join(map(str, tr["seq"])) + "@" + ",".join(map(str, tr["days"])) +
            f"${tr['cost']}${tr['baseline']}")


def header_prefix(block: dict) -> bytes:
    return (
        f"{C.COIN_NAME}|{block['height']}|{block['prev_hash']}|{block['timestamp']}|"
        f"{block['target']}|{block['tx_root']}|{trajectory_text(block['trajectory'])}|"
    ).encode()


def score_trajectory(prev_hash: str, seq, days) -> dict:
    """Check a trajectory against this block's mission and compute its cost.

    Returns {"cost", "baseline", "eval"} with costs rounded to whole m/s.
    Raises ValidationError if the trajectory breaks the mission rules or is impossible.
    """
    prob = T.problem(prev_hash)
    err = T.check(prob, seq, days)
    if err:
        raise ValidationError(err)
    ev = T.evaluate(seq, days)
    if ev is None:
        raise ValidationError("trajectory is not physically possible")
    return {"cost": round(ev["cost"]), "baseline": round(T.baseline(prev_hash)["cost"]), "eval": ev}


def verify_trajectory(prev_hash: str, tr) -> dict:
    """Validate a block's claimed trajectory and costs; returns the claimed costs."""
    if (not isinstance(tr, dict) or set(tr) != {"seq", "days", "cost", "baseline"}
            or any(not isinstance(tr[k], int) or isinstance(tr[k], bool) for k in ("cost", "baseline"))):
        raise ValidationError("block needs a trajectory {seq, days, cost, baseline}")
    sc = score_trajectory(prev_hash, tr["seq"], tr["days"])
    if abs(tr["cost"] - sc["cost"]) > C.COST_TOLERANCE_MPS:
        raise ValidationError("claimed trajectory cost doesn't match")
    if abs(tr["baseline"] - sc["baseline"]) > C.COST_TOLERANCE_MPS:
        raise ValidationError("claimed baseline doesn't match")
    return {"cost": tr["cost"], "baseline": tr["baseline"]}


def effective_target(base_target_hex: str, cost: int, baseline: int) -> int:
    """Base target scaled by (baseline / cost)^k: cheaper trajectories are easier to mine."""
    k = C.TRAJECTORY_BONUS_EXPONENT
    t = int(base_target_hex, 16) * baseline ** k // max(cost, 1) ** k
    return max(1, min(t, C.MAX_TARGET))


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
        "trajectory": None,
        "nonce": 0,
    }
    block["tx_root"] = tx_root(block["txs"])
    block["hash"] = block_hash(block)
    return block


class State:
    """Balances, nonces and usernames after applying a chain of blocks.

    Usernames are claimed in the coinbase of a mined block: the first address to
    mine a block with a name owns it. An address can switch to a new free name,
    which releases its old one.
    """

    def __init__(self):
        self.balances = {}
        self.nonces = {}
        self.names = {}        # NAME -> address
        self.name_of = {}      # address -> NAME

    def copy(self):
        s = State()
        s.balances = dict(self.balances)
        s.nonces = dict(self.nonces)
        s.names = dict(self.names)
        s.name_of = dict(self.name_of)
        return s

    def name_owner(self, name):
        return self.names.get(name)

    def claim_name(self, address, name):
        check_name(name)
        owner = self.names.get(name)
        if owner is not None and owner != address:
            raise ValidationError(f"name {name} is taken")
        old = self.name_of.get(address)
        if old and old != name:
            del self.names[old]
        self.names[name] = address
        self.name_of[address] = name

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
        if set(cb) - {"name"} != {"coinbase", "to", "amount", "height"} or cb["coinbase"] is not True:
            raise ValidationError("bad coinbase fields")
        if cb["height"] != block["height"]:
            raise ValidationError("coinbase height mismatch")
        if not is_valid_address(cb["to"]):
            raise ValidationError("bad coinbase address")
        if cb["amount"] != block_reward(block["height"]) + fees:
            raise ValidationError("wrong coinbase amount")
        self.balances[cb["to"]] = self.balance(cb["to"]) + cb["amount"]
        if "name" in cb:
            self.claim_name(cb["to"], cb["name"])


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
    keys = {"height", "prev_hash", "timestamp", "target", "tx_root", "txs", "trajectory", "nonce", "hash"}
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
    score = verify_trajectory(block["prev_hash"], block["trajectory"])
    h = block_hash(block)
    if block["hash"] != h:
        raise ValidationError("hash mismatch")
    if int(h, 16) > effective_target(block["target"], score["cost"], score["baseline"]):
        raise ValidationError("insufficient proof of work for this trajectory")
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
            # The rules changed (or the file is damaged): keep the old file and start a new chain.
            moved = self._path + f".old-{int(time.time())}"
            os.replace(self._path, moved)
            print(f"Saved chain doesn't match this version's rules; moved it to {moved} and started fresh.")

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
    def build_template(self, miner_address, now=None, name=None):
        """A block ready to mine except for its nonce. `name` claims a username in the coinbase."""
        if not is_valid_address(miner_address):
            raise ValidationError("bad miner address")
        if name:
            check_name(name)
            owner = self.state.name_owner(name)
            if owner is not None and owner != miner_address:
                raise ValidationError(f"name {name} is taken by another address: pick a different username")
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
        if name:
            coinbase["name"] = name
        block = {
            "height": height,
            "prev_hash": self.tip["hash"],
            "timestamp": max(now, median_time_past(self.blocks) + 1),
            "target": next_target(self.blocks),
            "txs": [coinbase] + chosen,
            "trajectory": None,
            "nonce": 0,
        }
        block["tx_root"] = tx_root(block["txs"])
        block["hash"] = ""
        return block

    def mission_stats(self, limit=20):
        """The mission log: recent blocks' trajectories and how they beat the direct route."""
        out = []
        for b in reversed(self.blocks[1:][-limit:]):
            tr = b["trajectory"]
            ev = T.evaluate(tr["seq"], tr["days"])
            out.append({
                "height": b["height"], "miner": b["txs"][0]["to"], "timestamp": b["timestamp"],
                "miner_name": self.state.name_of.get(b["txs"][0]["to"]),
                "path": [T.PLANETS[p][0] for p in tr["seq"]], "seq": tr["seq"], "days": tr["days"],
                "dv_kms": round(ev["dv_kms"], 3), "years": round(ev["years"], 2),
                "cost": tr["cost"], "baseline": tr["baseline"],
                "improvement_pct": round(100 * (1 - tr["cost"] / tr["baseline"]), 2),
            })
        return out
