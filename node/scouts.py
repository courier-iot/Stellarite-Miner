"""Scout proofs: Nebulite escape missions that guide Pulsarite routes.

A Nebulite escape mission sends a probe out of the solar system aimed at one of
Pulsarite's stars. Past 550 AU the Sun's gravity focuses that star's light, so
the probe works as a telescope (the "solar gravitational lens") and images the
star's planets. A Pulsarite route whose survey stop has been scouted this way
doesn't need to stop there: the probe flies past at speed, saving the braking,
the survey years and a large share of its fuel.

A Pulsarite block cites a scout by carrying the Nebulite block itself (a "proof":
its header fields, trajectory and nonce). Every Pulsarite node re-checks it on
its own, with Nebulite's physics, and never contacts the Nebulite network:

  * the trajectory is a valid escape for that Nebulite block's mission, and the
    mission's target star is what the scout is credited with;
  * the block's hash meets its own (Nebulite) proof-of-work target;
  * that work is at least 1/SCOUT_MIN_WORK_DIVISOR of the citing Pulsarite
    block's work, so a forged scout costs real hashing;
  * each Nebulite block is cited at most once per Pulsarite chain.

Together with the cap on how much scouts can ease a Pulsarite target (config:
SCOUT_TIME_CAP), forging a scout always costs more hashing than it saves.
"""
import hashlib
import importlib.util
import json
import os
from functools import lru_cache

_HERE = os.path.dirname(os.path.abspath(__file__))
NEBULITE_DIR = next((d for d in (os.environ.get("NEBULITE_PHYSICS_DIR", ""), os.path.join(_HERE, "nebulite"),
                                 os.path.join(_HERE, "..", "nebulite"))
                     if d and os.path.exists(os.path.join(d, "trajectory.py"))), None)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(NEBULITE_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Nebulite's own physics and rules, loaded under separate names so they can't clash with Pulsarite's modules.
NT = _load("nebulite_trajectory", "trajectory.py") if NEBULITE_DIR else None
NC = _load("nebulite_config", "config.py") if NEBULITE_DIR else None

PROOF_KEYS = {"height", "prev_hash", "timestamp", "target", "tx_root", "trajectory", "nonce"}


class ScoutError(Exception):
    pass


def _sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def _trajectory_text(tr) -> str:
    """As nebulite/chain.trajectory_text."""
    esc = tr.get("escape")
    extra = "#" + ",".join(f"{k}={esc[k]}" for k in sorted(esc)) if esc else ""
    return (",".join(map(str, tr["seq"])) + "@" + ",".join(map(str, tr["days"])) + extra +
            f"${tr['cost']}${tr['baseline']}")


def nebulite_hash(proof) -> str:
    """The Nebulite block hash (as nebulite/chain.block_hash)."""
    prefix = (f"{NC.COIN_NAME}|{proof['height']}|{proof['prev_hash']}|{proof['timestamp']}|"
              f"{proof['target']}|{proof['tx_root']}|{_trajectory_text(proof['trajectory'])}|").encode()
    return _sha256d(prefix + proof["nonce"].to_bytes(8, "big")).hex()


def nebulite_effective_target(target_hex, cost, baseline) -> int:
    """As nebulite/chain.effective_target (including its 1.6x bonus cap)."""
    k = NC.TRAJECTORY_BONUS_EXPONENT
    cost = max(cost, -(-baseline * NC.BONUS_RATIO_CAP_DEN // NC.BONUS_RATIO_CAP_NUM))
    t = int(target_hex, 16) * baseline ** k // max(cost, 1) ** k
    return max(1, min(t, NC.MAX_TARGET))


def key(proof) -> str:
    return json.dumps(proof, sort_keys=True, separators=(",", ":"))


def verify(proof) -> dict:
    """Check a scout proof on its own merits. Returns {"hash", "star", "work", "star_name", ...};
    raises ScoutError. (Whether it carries enough work for a given Pulsarite block, and whether it
    was already cited, are checked by the chain.)"""
    if NT is None:
        raise ScoutError("this node can't check scouts: Nebulite's physics files are missing")
    if not isinstance(proof, dict) or set(proof) != PROOF_KEYS:
        raise ScoutError("a scout proof needs the Nebulite block's " + ", ".join(sorted(PROOF_KEYS)))
    return dict(_verify(key(proof)))


@lru_cache(maxsize=512)
def _verify(k):
    p = json.loads(k)
    try:
        ok_types = (isinstance(p["height"], int) and isinstance(p["timestamp"], int) and isinstance(p["nonce"], int)
                    and 0 <= p["nonce"] < 2 ** 64 and isinstance(p["prev_hash"], str) and len(p["prev_hash"]) == 64
                    and isinstance(p["target"], str) and len(p["target"]) == 64 and isinstance(p["tx_root"], str))
        bytes.fromhex(p["prev_hash"]); int(p["target"], 16); bytes.fromhex(p["tx_root"])
    except (TypeError, ValueError, KeyError):
        ok_types = False
    if not ok_types:
        raise ScoutError("malformed scout proof")
    tr = p["trajectory"]
    if (not isinstance(tr, dict) or set(tr) != {"seq", "days", "cost", "baseline", "escape"}
            or not all(isinstance(tr[x], int) and not isinstance(tr[x], bool) for x in ("cost", "baseline"))):
        raise ScoutError("a scout must be a Nebulite escape mission")
    prob = NT.problem(p["prev_hash"])
    if prob["type"] != "escape":
        raise ScoutError("that Nebulite block's mission wasn't an escape mission")
    err = NT.escape_check(prob, tr["seq"], tr["days"], tr["escape"])
    if err:
        raise ScoutError("scout trajectory breaks Nebulite's rules: " + err)
    ev = NT.escape_evaluate(prob, tr["seq"], tr["days"], tr["escape"])
    if ev is None:
        raise ScoutError("scout trajectory isn't possible within Nebulite's limits")
    if (abs(round(ev["cost"]) - tr["cost"]) > NC.COST_TOLERANCE_MPS
            or abs(round(NT.escape_baseline(p["prev_hash"])["cost"]) - tr["baseline"]) > NC.COST_TOLERANCE_MPS):
        raise ScoutError("scout's claimed cost or baseline doesn't match Nebulite's physics")
    h = nebulite_hash(p)
    eff = nebulite_effective_target(p["target"], tr["cost"], tr["baseline"])
    if int(h, 16) > eff:
        raise ScoutError("scout block doesn't meet its own proof-of-work target")
    star = prob["target_star"]
    return (("hash", h), ("star", star["id"]), ("star_name", star["name"]), ("effective_target", eff),
            ("work", (1 << 256) // (eff + 1)), ("vinf_kms", ev["vinf_kms"]), ("au_per_year", ev["au_per_year"]),
            ("years_to_550_au", ev["years"]), ("launch_day", tr["days"][0]))
