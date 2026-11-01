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


def name_claim_pow_ok(tx: dict) -> bool:
    """A name claim's anti-spam proof of work: sha256d(claim without sig) has NAME_POW_BITS leading zeros."""
    return int.from_bytes(sha256d(tx_signing_bytes(tx)), "big") < (1 << (256 - C.NAME_POW_BITS))


def is_name_claim(tx) -> bool:
    return isinstance(tx, dict) and tx.get("type") == "name"


def check_tx_format(tx: dict):
    """Stateless checks: shape, amounts, signature (and proof of work for name claims)."""
    if is_name_claim(tx):
        if set(tx) != {"type", "from", "name", "nonce", "work", "sig"}:
            raise ValidationError("name claim has wrong fields")
        for k in ("nonce", "work"):
            if not isinstance(tx[k], int) or isinstance(tx[k], bool) or tx[k] < 0:
                raise ValidationError(f"bad {k}")
        check_name(tx["name"])
        if not isinstance(tx["from"], str) or not verify(tx["from"], tx_signing_bytes(tx), tx["sig"]):
            raise ValidationError("bad signature")
        if not name_claim_pow_ok(tx):
            raise ValidationError("name claim is missing its proof of work")
        return
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
    esc = tr.get("escape")
    extra = "#" + ",".join(f"{k}={esc[k]}" for k in sorted(esc)) if esc else ""
    return (",".join(map(str, tr["seq"])) + "@" + ",".join(map(str, tr["days"])) + extra +
            f"${tr['cost']}${tr['baseline']}")


def header_prefix(block: dict) -> bytes:
    return (
        f"{C.COIN_NAME}|{block['height']}|{block['prev_hash']}|{block['timestamp']}|"
        f"{block['target']}|{block['tx_root']}|{trajectory_text(block['trajectory'])}|"
    ).encode()


def score_trajectory(prev_hash: str, seq, days, escape=None) -> dict:
    """Check a trajectory against this block's mission and compute its cost.

    Returns {"cost", "baseline", "eval"} with costs rounded to whole numbers: m/s-equivalent
    for planet missions, days from launch to 550 AU for escape missions.
    Raises ValidationError if the trajectory breaks the mission rules or is impossible.
    """
    prob = T.problem(prev_hash)
    if T.is_escape(prob):
        err = T.escape_check(prob, seq, days, escape)
        if err:
            raise ValidationError(err)
        ev = T.escape_evaluate(prob, seq, days, escape)
        if ev is None:
            raise ValidationError("escape trajectory is not possible within the launch and fuel limits")
        # (heliopause missions score days to 120 AU; escapes toward a star, days to 550 AU)
        return {"cost": round(ev["cost"]), "baseline": round(T.escape_baseline(prev_hash)["cost"]), "eval": ev}
    if escape is not None:
        raise ValidationError("this block's mission isn't an escape mission")
    err = T.check(prob, seq, days)
    if err:
        raise ValidationError(err)
    ev = T.evaluate(seq, days, prob["time_penalty_mps_per_year"], prob)
    if ev is None:
        raise ValidationError("trajectory is not physically possible")
    return {"cost": round(ev["cost"]), "baseline": round(T.baseline(prev_hash)["cost"]), "eval": ev}


def verify_trajectory(prev_hash: str, tr) -> dict:
    """Validate a block's claimed trajectory and costs; returns the claimed costs."""
    if (not isinstance(tr, dict) or set(tr) - {"escape"} != {"seq", "days", "cost", "baseline"}
            or any(not isinstance(tr[k], int) or isinstance(tr[k], bool) for k in ("cost", "baseline"))):
        raise ValidationError("block needs a trajectory {seq, days, cost, baseline} (+ escape)")
    sc = score_trajectory(prev_hash, tr["seq"], tr["days"], tr.get("escape"))
    if abs(tr["cost"] - sc["cost"]) > C.COST_TOLERANCE_MPS:
        raise ValidationError("claimed trajectory cost doesn't match")
    if abs(tr["baseline"] - sc["baseline"]) > C.COST_TOLERANCE_MPS:
        raise ValidationError("claimed baseline doesn't match")
    return {"cost": tr["cost"], "baseline": tr["baseline"]}


def effective_target(base_target_hex: str, cost: int, baseline: int) -> int:
    """Base target scaled by (baseline / cost)^k: cheaper trajectories are easier to mine."""
    k = C.TRAJECTORY_BONUS_EXPONENT
    cost = max(cost, -(-baseline * C.BONUS_RATIO_CAP_DEN // C.BONUS_RATIO_CAP_NUM))   # cap: at most 1.6x better counts
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
        """Apply a transfer or a name claim, raising ValidationError if invalid here."""
        check_tx_format(tx)
        sender = tx_sender(tx)
        if tx["nonce"] != self.nonce(sender):
            raise ValidationError(f"bad nonce (expected {self.nonce(sender)})")
        if is_name_claim(tx):
            self.claim_name(sender, tx["name"])
            self.nonces[sender] = tx["nonce"] + 1
            return
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
            fees += tx.get("fee", 0)
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
        if is_name_claim(tx):
            owner = self.state.name_owner(tx["name"])
            if owner is not None and owner != sender:
                raise ValidationError(f"name {tx['name']} is taken")
            if any(is_name_claim(t) and t["name"] == tx["name"] and tx_sender(t) != sender
                   for t in self.mempool.values()):
                raise ValidationError(f"someone else's claim for {tx['name']} is already waiting to be mined")
        elif tx["amount"] + tx["fee"] > self.state.balance(sender):
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
            fees += tx.get("fee", 0)
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

    def _escape_row(self, b, tr, prob):
        ev = T.escape_evaluate(prob, tr["seq"], tr["days"], tr["escape"])
        enc = [{"planet": T.body_name(p), "date": T.date_of(d)} for p, d in zip(tr["seq"], tr["days"])]
        if ev["perihelion_day"] is not None:
            enc.append({"planet": "Sun", "date": T.date_of(ev["perihelion_day"]),
                        "perihelion_au": tr["escape"]["rp_mau"] / 1000})
        star = prob["target_star"]
        return {
            "height": b["height"], "miner": b["txs"][0]["to"], "timestamp": b["timestamp"],
            "miner_name": self.state.name_of.get(b["txs"][0]["to"]),
            "mission_type": prob["type"], "target_star": star["name"], "target_star_id": star["id"], "star_dir": star["dir"],
            "goal_au": prob["goal_au"],
            "path": [T.body_name(p) for p in tr["seq"]] + [f"{prob['goal_au']} AU"], "seq": tr["seq"], "days": tr["days"],
            "escape": tr["escape"],
            "dv_kms": round(ev["launch_kms"] + ev["burns_total_kms"], 3), "launch_kms": round(ev["launch_kms"], 3),
            "burns_kms": round(ev["burns_total_kms"], 3),
            "vinf_kms": round(ev["vinf_kms"], 3), "au_per_year": round(ev["au_per_year"], 3),
            "years": round(ev["years"], 2), "years_to_star": round(ev["years_to_star"]),
            "cost": tr["cost"], "baseline": tr["baseline"],
            "improvement_pct": round(100 * (1 - tr["cost"] / tr["baseline"]), 2),
            "launch_date": T.date_of(tr["days"][0]),
            "arrival_date": T.date_of(tr["days"][0] + ev["cost"]),      # passing 550 AU (120 AU for heliopause)
            "encounters": enc,
        }

    def mission_stats(self, limit=20):
        """The mission log: recent blocks' trajectories and how they beat the direct route."""
        out = []
        for b in reversed(self.blocks[1:][-limit:]):
            tr = b["trajectory"]
            prob = T.problem(b["prev_hash"])
            if T.is_escape(prob):
                out.append(self._escape_row(b, tr, prob))
                continue
            ev = T.evaluate(tr["seq"], tr["days"], prob["time_penalty_mps_per_year"], prob)
            row = {
                "height": b["height"], "miner": b["txs"][0]["to"], "timestamp": b["timestamp"],
                "miner_name": self.state.name_of.get(b["txs"][0]["to"]),
                "path": [T.body_name(p) for p in tr["seq"]], "seq": tr["seq"], "days": tr["days"],
                "dv_kms": round(ev["dv_kms"], 3), "years": round(ev["years"], 2),
                "cost": tr["cost"], "baseline": tr["baseline"],
                "improvement_pct": round(100 * (1 - tr["cost"] / tr["baseline"]), 2),
                "mission_type": prob["type"],
                "launch_date": T.date_of(tr["days"][0]), "arrival_date": T.date_of(tr["days"][-1]),
                "encounters": [{"planet": T.body_name(p), "date": T.date_of(d)} for p, d in zip(tr["seq"], tr["days"])],
            }
            if prob["type"] == "intercept":
                iso = prob["iso"]
                row.update(iso=iso, encounter_kms=round(ev["arrival_kms"], 3), iso_vinf_kms=round(iso["vinf_kms"], 3),
                           iso_q_au=round(iso["q_au"], 4), iso_perihelion_date=T.date_of(iso["t_peri"]),
                           iso_discovery_date=T.date_of(iso["discovery_day"]),
                           dv_kms=round(ev["launch_kms"] + sum(ev["flyby_kms"]), 3))
            out.append(row)
        return out
