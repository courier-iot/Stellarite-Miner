"""The blockchain: blocks, transactions, star-route proof-of-work, difficulty and state.

Model
-----
* Account-based ledger (balances + per-address nonce), simpler than UTXOs.
* Proof of useful work: every block carries a route through 24 stars picked
  from the previous block's hash (see stars.py), with a cruise speed for each
  leg. A probe flies it while the stars move, braking and surveying at 4 stops,
  within a fixed fuel budget. A block is valid when
      sha256d(header_prefix + nonce as 8 bytes big-endian) <= effective target
  where effective target = base target * (baseline time / route time)^12.
  Faster routes make the hash target exponentially easier, so miners spend
  effort optimising routes; the hash keeps blocks unpredictable and lets the
  difficulty adjust. The header prefix includes the route, so a miner only
  needs the prefix bytes and the effective target to search for nonces.
* Fork choice: the valid chain with the most cumulative work wins.
"""
import functools
import json
import os
import re
import statistics
import time

import config as C
import scouts as SC
import stars
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


def header_prefix(block: dict) -> bytes:
    route = ",".join(f"{s}:{v}" for s, v in block["route"])
    scouted = ""
    if block.get("scouts"):                     # commits to the cited Nebulite blocks
        scouted = "S:" + ",".join(SC.nebulite_hash(p) for p in block["scouts"]) + "|"
    return (
        f"{C.COIN_NAME}|{block['height']}|{block['prev_hash']}|{block['timestamp']}|"
        f"{block['target']}|{block['tx_root']}|{route}|{scouted}"
    ).encode()


def route_score(prev_hash: str, route, scouted=()) -> dict:
    """Check a route plan against the block's star problem and fuel budget, and score it.

    A plan is [[star id, cruise speed in % of c], ...]. Raises ValidationError if it
    doesn't visit exactly the problem's stars, or needs more fuel than the probe carries.
    """
    problem = stars.problem(prev_hash)
    if (not stars.check_plan(route) or len(route) != len(problem)
            or sorted(s for s, _ in route) != problem):
        raise ValidationError("route must visit each of the block's stars exactly once, "
                              "as [star id, cruise speed 1-10] pairs")
    all_stops = stars.stops(prev_hash)
    stop_ids = [s for s in all_stops if s not in set(scouted)]    # scouted stops are flown past
    dv = stars.route_dv(route, stop_ids)
    if dv > stars.DV_BUDGET:
        raise ValidationError(f"route needs {dv / stars.PCT:.1f}% of c of speed change; "
                              f"the probe's fuel allows {C.DV_BUDGET_PCT_C}%")
    # "length" and "baseline" are mission times in milli-years (lower is better)
    length = stars.route_time(route, stop_ids)
    mission_time = length
    if len(stop_ids) < len(all_stops):
        # scouts may shorten the scored time by at most SCOUT_TIME_CAP compared with the same plan unscouted
        unscouted = stars.route_time(route, all_stops)
        length = max(length, -(-unscouted * C.SCOUT_TIME_CAP_DEN // C.SCOUT_TIME_CAP_NUM))
    baseline = _baseline_time(prev_hash)
    return {"length": length, "baseline": baseline, "dv": dv, "mission_time": mission_time, "stops": stop_ids}


@functools.lru_cache(maxsize=256)
def _baseline_time(prev_hash):
    stop_ids = stars.stops(prev_hash)
    return stars.route_time(stars.baseline_route(stars.problem(prev_hash), stop_ids), stop_ids)


def effective_target(base_target_hex: str, length: int, baseline: int) -> int:
    """Base target scaled by (baseline / time)^k: faster routes are easier to mine."""
    k = C.ROUTE_BONUS_EXPONENT
    t = int(base_target_hex, 16) * baseline ** k // max(length, 1) ** k
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
        "route": [],
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
        self.used_scouts = set()   # Nebulite block hashes already cited as scouts

    def copy(self):
        s = State()
        s.balances = dict(self.balances)
        s.nonces = dict(self.nonces)
        s.names = dict(self.names)
        s.name_of = dict(self.name_of)
        s.used_scouts = set(self.used_scouts)
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
        if set(cb) - {"name", "scout_rewards"} != {"coinbase", "to", "amount", "height"} or cb["coinbase"] is not True:
            raise ValidationError("bad coinbase fields")
        if cb["height"] != block["height"]:
            raise ValidationError("coinbase height mismatch")
        if not is_valid_address(cb["to"]):
            raise ValidationError("bad coinbase address")
        if cb["amount"] != block_reward(block["height"]) + fees:
            raise ValidationError("wrong coinbase amount")
        self.balances[cb["to"]] = self.balance(cb["to"]) + cb["amount"]
        for r in cb.get("scout_rewards", []):          # checked against the block's scouts in validate_block
            self.balances[r["to"]] = self.balance(r["to"]) + r["amount"]
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
    keys = {"height", "prev_hash", "timestamp", "target", "tx_root", "txs", "route", "nonce", "hash"}
    if not isinstance(block, dict) or set(block) - {"scouts"} != keys:
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
    scouted = check_scouts(block, state)
    want = scout_rewards(block["height"], scouted)
    if block["txs"][0].get("scout_rewards", []) != want or (not want and "scout_rewards" in block["txs"][0]):
        raise ValidationError("coinbase must pay each cited scout's miner exactly its share")
    score = route_score(block["prev_hash"], block["route"], [s["star"] for s in scouted])
    h = block_hash(block)
    if block["hash"] != h:
        raise ValidationError("hash mismatch")
    eff = effective_target(block["target"], score["length"], score["baseline"])
    if int(h, 16) > eff:
        raise ValidationError("insufficient proof of work for this route")
    for s_ in scouted:
        if not scout_work_ok(s_, eff):
            raise ValidationError(f"the scout of {s_['star_name']} doesn't carry enough proof of work for this block")
    new_state = state.copy()
    new_state.apply_block_txs(block)
    new_state.used_scouts |= {s["hash"] for s in scouted}
    return new_state


def check_scouts(block: dict, state: State) -> list:
    """Verify a block's cited scouts (see scouts.py); returns their details. Raises ValidationError."""
    proofs = block.get("scouts")
    if proofs is None:
        return []
    if not isinstance(proofs, list) or not 1 <= len(proofs) <= C.SCOUT_MAX_PER_BLOCK:
        raise ValidationError(f"scouts must be a list of 1 to {C.SCOUT_MAX_PER_BLOCK} proofs")
    stops = set(stars.stops(block["prev_hash"]))
    out = []
    for p in proofs:
        try:
            v = SC.verify(p)
        except SC.ScoutError as e:
            raise ValidationError(str(e))
        if v["star"] not in stops:
            raise ValidationError(f"scout of {v['star_name']} isn't for one of this block's survey stops")
        if v["hash"] in state.used_scouts or any(o["hash"] == v["hash"] for o in out):
            raise ValidationError("that Nebulite scout was already cited")
        if any(o["star"] == v["star"] for o in out):
            raise ValidationError("one scout per survey star")
        out.append(v)
    return out


def scout_rewards(height: int, scouted: list) -> list:
    """What the coinbase pays the cited scouts' miners: SCOUT_REWARD_PCT of the block reward each,
    in the order the scouts are cited, to each Nebulite miner's Pulsarite address."""
    return [{"to": s["reward_to"], "amount": block_reward(height) * C.SCOUT_REWARD_PCT // 100} for s in scouted]


def scout_work_ok(scout: dict, block_effective_target: int) -> bool:
    """A scout must carry at least 1/SCOUT_MIN_WORK_DIVISOR of the work the citing block needs."""
    return scout["effective_target"] <= block_effective_target * C.SCOUT_MIN_WORK_DIVISOR


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
    def build_template(self, miner_address, now=None, name=None, scouts=None):
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
            "route": [],
            "nonce": 0,
        }
        if scouts:
            block["scouts"] = list(scouts)
            coinbase["scout_rewards"] = scout_rewards(height, [SC.verify(p) for p in scouts])
        block["tx_root"] = tx_root(block["txs"])
        block["hash"] = ""
        return block

    def usable_scouts(self, prev_hash, target, candidates, exclude=()):
        """From candidate proofs (e.g. fetched from a Nebulite node), the best valid, uncited scout for each
        of this block's survey stops: the one with the most work."""
        stops = set(stars.stops(prev_hash))
        best = {}
        for p in candidates:
            try:
                v = SC.verify(p)
            except SC.ScoutError:
                continue
            # the work rule depends on the miner's route; offer scouts that a good route (up to 2x faster
            # than the baseline, a target 4096x easier) could use, and let /mining/route check
            if (v["star"] in stops and v["hash"] not in self.state.used_scouts and v["hash"] not in exclude
                    and v["effective_target"] <= int(target, 16) * C.SCOUT_MIN_WORK_DIVISOR * 4096
                    and (v["star"] not in best or v["work"] > best[v["star"]][1]["work"])):
                best[v["star"]] = (p, v)
        return [best[k][0] for k in sorted(best)][:C.SCOUT_MAX_PER_BLOCK]

    def route_stats(self, limit=20):
        """The route map: recent blocks' routes and how much they beat the baseline."""
        out = []
        for b in reversed(self.blocks[1:][-limit:]):
            cited = [SC.verify(p) for p in b.get("scouts", [])]
            sc = route_score(b["prev_hash"], b["route"], [c["star"] for c in cited])
            out.append({
                "height": b["height"], "miner": b["txs"][0]["to"], "timestamp": b["timestamp"],
                "miner_name": self.state.name_of.get(b["txs"][0]["to"]),
                "route": [stars.CATALOG[s]["name"] for s, _ in b["route"]],
                "route_ids": [s for s, _ in b["route"]], "speeds_pct_c": [v for _, v in b["route"]],
                "fuel_used_pct": round(100 * sc["dv"] / stars.DV_BUDGET, 1),
                "mass_ratio": round(stars.mass_ratio(sc["dv"]), 1),
                "years": sc["mission_time"] / 1000, "baseline_years": sc["baseline"] / 1000,
                "length_ly": stars.route_length(b["route"], sc["stops"]) / 1000,
                "stops": [stars.CATALOG[s]["name"] for s in sc["stops"]],
                "stop_ids": sc["stops"],
                "scouted": [c["star_name"] for c in cited], "scouted_ids": [c["star"] for c in cited],
                "scouts": [{"star": c["star_name"], "nebulite_block": c["hash"], "vinf_kms": round(c["vinf_kms"], 1),
                            "au_per_year": round(c["au_per_year"], 2), "rewarded": c["reward_to"],
                            "reward": block_reward(b["height"]) * C.SCOUT_REWARD_PCT // 100 / C.UNITS_PER_COIN}
                           for c in cited],
                "improvement_pct": round(100 * (1 - sc["mission_time"] / sc["baseline"]), 2),
            })
        return out
