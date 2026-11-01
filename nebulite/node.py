"""Nebulite full node: HTTP API, trajectory mining endpoints and simple peer-to-peer sync.

Run:  python node.py --port 5001 --data ./data [--peer http://other-node:5001]
"""
import argparse
import os
import json
import secrets
import threading
import time
import urllib.request
from collections import OrderedDict

from flask import Flask, jsonify, request

import config as C
import trajectory as T
from chain import (Blockchain, ValidationError, block_hash, effective_target, header_prefix,
                   next_target, score_trajectory, tx_sender, work)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024   # room for imported chains
lock = threading.RLock()
chain: Blockchain = None
peers = set()
self_url = None
jobs = OrderedDict()          # job_id -> block template
MAX_JOBS = 500


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# ---- networking helpers -------------------------------------------------

def http_json(url, payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if self_url:
        headers["X-Node-Url"] = self_url  # lets peers sync back from us
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def broadcast(path, payload):
    def send(peer):
        try:
            http_json(peer + path, payload)
        except Exception:
            pass
    for p in list(peers):
        threading.Thread(target=send, args=(p,), daemon=True).start()


def sync_from(peer):
    """Download a peer's chain and adopt it if it has more work."""
    try:
        info = http_json(peer + "/info")
        if int(info["total_work"]) <= chain.total_work():
            return False
        candidate = http_json(peer + "/chain", timeout=30)
    except Exception:
        return False
    with lock:
        adopted = chain.replace_chain(candidate)
        if adopted:
            jobs.clear()
    if adopted:
        print(f"[sync] adopted chain from {peer}, height {chain.tip['height']}")
    return adopted


def sync_loop():
    while True:
        for p in list(peers):
            sync_from(p)
        time.sleep(30)


# ---- general API --------------------------------------------------------

@app.get("/info")
def info():
    with lock:
        tip = chain.tip
        return jsonify({
            "coin": C.COIN_NAME, "ticker": C.TICKER,
            "height": tip["height"], "tip": tip["hash"],
            "target": next_target(chain.blocks),
            "difficulty": work(next_target(chain.blocks)),
            "total_work": str(chain.total_work()),
            "mempool": len(chain.mempool), "peers": sorted(peers),
            "target_block_seconds": C.TARGET_BLOCK_SECONDS,
            "units_per_coin": C.UNITS_PER_COIN,
            "name_pow_bits": C.NAME_POW_BITS,
            "useful_work": "spacecraft trajectories",
            "ephemeris": T.EPHEMERIS, "ephemeris_id": T.EPHEMERIS_ID,
            "star_catalog_id": T.STAR_TARGETS["catalog_id"],   # must equal the Pulsarite node's catalog_id
        })


@app.get("/chain")
def get_chain():
    with lock:
        return jsonify(chain.blocks)


@app.post("/chain/import")
def import_chain():
    """Adopt a whole chain (e.g. one mined in the app's solo mode) if it's valid and has more work.

    Same rule as syncing from a peer: the valid chain with the most cumulative work wins.
    """
    candidate = request.get_json(silent=True)
    if not isinstance(candidate, list) or not candidate:
        return err("send the chain as a JSON list of blocks")
    with lock:
        before = chain.tip["height"]
        adopted = chain.replace_chain(candidate)
        if adopted:
            jobs.clear()
        height = chain.tip["height"]
    if not adopted:
        return jsonify({"ok": True, "adopted": False, "height": height,
                        "reason": "not adopted: the chain is invalid, starts from a different genesis "
                                  "block, or doesn't have more total work than this node's chain"})
    print(f"[import] adopted imported chain: height {before} -> {height}")
    broadcast("/blocks", chain.tip)
    return jsonify({"ok": True, "adopted": True, "height": height})


@app.get("/blocks/<int:height>")
def get_block(height):
    with lock:
        if 0 <= height < len(chain.blocks):
            return jsonify(chain.blocks[height])
    return err("no such block", 404)


@app.get("/balance/<address>")
def balance(address):
    with lock:
        pending = [t["nonce"] for t in chain.mempool.values()
                   if tx_sender(t) == address]
        nonce = chain.state.nonce(address)
        next_nonce = max([nonce] + [n + 1 for n in pending])
        return jsonify({"address": address, "name": chain.state.name_of.get(address),
                        "units_per_coin": C.UNITS_PER_COIN, "balance": chain.state.balance(address),
                        "balance_coins": chain.state.balance(address) / C.UNITS_PER_COIN,
                        "nonce": nonce, "next_nonce": next_nonce})


@app.get("/name/<name>")
def lookup_name(name):
    """Resolve a username to its address (so coins can be sent to a name)."""
    name = name.strip().upper()
    with lock:
        addr = chain.state.name_owner(name)
    if addr is None:
        return err(f"no one has claimed the name {name} on this network", 404)
    return jsonify({"name": name, "address": addr})


@app.get("/names")
def list_names():
    with lock:
        return jsonify(dict(sorted(chain.state.names.items())))


@app.post("/tx")
def submit_tx():
    tx = request.get_json(silent=True)
    try:
        with lock:
            tid = chain.add_transaction(tx)
    except (ValidationError, KeyError, TypeError) as e:
        return err(str(e))
    broadcast("/tx", tx)
    return jsonify({"ok": True, "txid": tid})


@app.post("/blocks")
def receive_block():
    """A peer announces a newly mined block."""
    block = request.get_json(silent=True)
    sender = request.headers.get("X-Node-Url")
    with lock:
        try:
            chain.add_block(block)
            jobs.clear()
            accepted = True
        except (ValidationError, KeyError, TypeError):
            accepted = False
    if accepted:
        broadcast("/blocks", block)
        return jsonify({"ok": True})
    if sender:
        threading.Thread(target=sync_from, args=(sender,), daemon=True).start()
    return err("block not accepted")


@app.get("/peers")
def get_peers():
    return jsonify(sorted(peers))


@app.post("/peers")
def add_peer():
    url = (request.get_json(silent=True) or {}).get("url", "").rstrip("/")
    if not url.startswith(("http://", "https://")) or url == self_url:
        return err("bad peer url")
    peers.add(url)
    threading.Thread(target=sync_from, args=(url,), daemon=True).start()
    return jsonify({"ok": True, "peers": sorted(peers)})


# ---- mining API (used by the Android app and miner.py) ------------------
#
# 1. GET  /mining/work?address=...        -> this block's mission and the planets' orbits
# 2. POST /mining/trajectory {job_id, seq, days}
#                                          -> header prefix + effective target for that trajectory
#    (optimise first: cheaper trajectories get an easier target)
# 3. search nonces: sha256d(prefix + 8-byte big-endian nonce) <= target
# 4. POST /mining/submit {job_id, seq, days, nonce}

@app.get("/mining/work")
def mining_work():
    address = request.args.get("address", "")
    name = request.args.get("name", "").strip().upper() or None
    try:
        with lock:
            template = chain.build_template(address, name=name)
            job_id = secrets.token_hex(8)
            jobs[job_id] = template
            while len(jobs) > MAX_JOBS:
                jobs.popitem(last=False)
    except ValidationError as e:
        return err(str(e))
    prob = T.problem(template["prev_hash"])
    base = T.baseline(template["prev_hash"])
    return jsonify({
        "job_id": job_id,
        "height": template["height"],
        "mission": prob,
        "mission_about": T.ESCAPE_ABOUT if prob["type"] == "escape" else T.MISSION_TYPES[prob["type"]]["about"],
        "baseline": {"seq": base["seq"], "days": base["days"], "cost": round(base["cost"]),
                     **({"escape": base["escape"]} if prob["type"] == "escape" else {})},
        "planets": T.planets_json(),
        "physics": T.physics_json(),
        "base_target": template["target"],
        "bonus_exponent": C.TRAJECTORY_BONUS_EXPONENT,
        "reward": template["txs"][0]["amount"],
        "units_per_coin": C.UNITS_PER_COIN,
    })


def _job_block(job_id, seq, days, escape=None):
    template = jobs.get(job_id)
    if template is None:
        raise LookupError("unknown or expired job")
    sc = score_trajectory(template["prev_hash"], seq, days, escape)
    tr = {"seq": list(seq), "days": list(days), "cost": sc["cost"], "baseline": sc["baseline"]}
    if escape is not None:
        tr["escape"] = dict(escape)
    return template, dict(template, trajectory=tr), sc


@app.post("/mining/trajectory")
def mining_trajectory():
    body = request.get_json(silent=True) or {}
    with lock:
        try:
            _, block, sc = _job_block(body.get("job_id"), body.get("seq"), body.get("days"), body.get("escape"))
        except LookupError as e:
            return err(str(e), 410)
        except ValidationError as e:
            return err(str(e))
    ev = sc["eval"]
    target = effective_target(block["target"], sc["cost"], sc["baseline"])
    if "vinf_kms" in ev:                         # escape mission
        days = body.get("days")
        return jsonify({
            "prefix": header_prefix(block).hex(), "target": format(target, "064x"),
            "cost": sc["cost"], "baseline": sc["baseline"],
            "improvement_pct": round(100 * (1 - sc["cost"] / sc["baseline"]), 2),
            "dv_kms": round(ev["launch_kms"] + ev["burns_total_kms"], 3), "years": round(ev["years"], 2),
            "launch_kms": round(ev["launch_kms"], 3), "burns_kms": round(ev["burns_total_kms"], 3),
            "vinf_kms": round(ev["vinf_kms"], 3), "au_per_year": round(ev["au_per_year"], 3),
            "years_to_star": round(ev["years_to_star"]),
            "launch_date": T.date_of(days[0]), "arrival_date": T.date_of(days[0] + ev["cost"]),
        })
    return jsonify({
        "prefix": header_prefix(block).hex(),
        "target": format(target, "064x"),
        "cost": sc["cost"], "baseline": sc["baseline"],
        "improvement_pct": round(100 * (1 - sc["cost"] / sc["baseline"]), 2),
        "dv_kms": round(ev["dv_kms"], 3), "years": round(ev["years"], 2),
        "launch_kms": round(ev["launch_kms"], 3), "arrival_kms": round(ev["arrival_kms"], 3),
        "flyby_kms": [round(x, 3) for x in ev["flyby_kms"]],
        "launch_date": T.date_of(body.get("days")[0]), "arrival_date": T.date_of(body.get("days")[-1]),
    })


@app.post("/mining/submit")
def mining_submit():
    body = request.get_json(silent=True) or {}
    with lock:
        try:
            template, block, _ = _job_block(body.get("job_id"), body.get("seq"), body.get("days"), body.get("escape"))
        except LookupError as e:
            return err(str(e), 410)
        except ValidationError as e:
            return err(str(e))
        if template["prev_hash"] != chain.tip["hash"]:
            return err("stale job: chain moved on", 409)
        try:
            block["nonce"] = int(body.get("nonce"))
            block["hash"] = block_hash(block)
            chain.add_block(block)
        except (ValidationError, ValueError, TypeError, OverflowError) as e:
            return err(str(e))
        jobs.clear()
    print(f"[mined] block {block['height']} {block['hash'][:16]}… -> {block['txs'][0]['to']}")
    broadcast("/blocks", block)
    return jsonify({"ok": True, "height": block["height"], "hash": block["hash"]})


# ---- the mission log ----------------------------------------------------

@app.get("/planets")
def planets():
    """Planet orbital elements and physics constants (for maps and miners)."""
    return jsonify({"planets": T.planets_json(), "physics": T.physics_json()})




_MAP_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map.html")
_map_cache = {}


@app.get("/map")
def map_page():
    """A 3D map of the network's useful work, for any browser."""
    with open(_MAP_HTML, encoding="utf-8") as f:
        return app.response_class(f.read(), mimetype="text/html")


@app.get("/map/data")
def map_data():
    """Everything the web map draws: planet orbits and recent missions' paths (AU)."""
    limit = max(1, min(request.args.get("limit", 8, type=int), 30))
    with lock:
        key = (chain.tip["hash"], limit)
        if key not in _map_cache:
            rows = chain.mission_stats(limit)
            ref = rows[0]["days"][0] if rows else T.WINDOW_START_MIN
            blocks = {b["height"]: b for b in chain.blocks[-limit - 1:]}
            for r in rows:
                if r["mission_type"] == "escape":
                    prob = T.problem(blocks[r["height"]]["prev_hash"])
                    r["points"] = T.escape_path(prob, r["seq"], r["days"], r["escape"])
                    r["star_dir"] = prob["target_star"]["dir"]
                    for enc, p, d in zip(r["encounters"], r["seq"], r["days"]):
                        enc["p"] = list(T.planet_state(p, d)[0])
                    if r["encounters"][-1]["planet"] == "Sun":     # perihelion point: the path's closest approach
                        r["encounters"][-1]["p"] = min(r["points"], key=lambda q: q[0] ** 2 + q[1] ** 2 + q[2] ** 2)
                    continue
                r["points"] = T.sample_path(r["seq"], r["days"])
                for enc, p, d in zip(r["encounters"], r["seq"], r["days"]):
                    enc["p"] = list(T.planet_state(p, d)[0])
            _map_cache.clear()
            _map_cache[key] = {
                "coin": C.COIN_NAME, "ticker": C.TICKER, "height": len(chain.blocks) - 1,
                "orbits": [{"name": T.PLANETS[i][0], "points": T.orbit_points(i, ref)} for i in range(len(T.PLANETS))],
                "missions": rows,
            }
        return jsonify(_map_cache[key])


@app.get("/missions")
def missions():
    """Recent blocks' trajectories: the mission plans the network has produced."""
    limit = max(1, min(request.args.get("limit", 20, type=int), 200))
    with lock:
        return jsonify(chain.mission_stats(limit))


def lan_addresses():
    """This computer's local-network IPv4 addresses (what a phone on the same Wi-Fi should use)."""
    import socket
    found = []
    try:  # the address the OS would use to reach the internet (no packets are sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ip.startswith("127.")]


def main():
    global chain, self_url
    ap = argparse.ArgumentParser(description=f"{C.COIN_NAME} node")
    env = os.environ   # every option can also come from the environment (handy for Docker)
    ap.add_argument("--host", default=env.get("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(env.get("PORT", 5001)))
    ap.add_argument("--data", default=env.get("DATA_DIR", "./data"), help="where chain.json is stored")
    ap.add_argument("--peer", action="append",
                    default=[p for p in env.get("PEERS", "").split(",") if p.strip()],
                    help="peer node URL (repeatable; env PEERS is comma-separated)")
    ap.add_argument("--public-url", default=env.get("PUBLIC_URL"), help="URL other nodes use to reach this one")
    args = ap.parse_args()

    chain = Blockchain(args.data)
    self_url = args.public_url
    for p in args.peer:
        peers.add(p.rstrip("/"))
        if self_url:
            try:
                http_json(p.rstrip("/") + "/peers", {"url": self_url})
            except Exception:
                pass
    threading.Thread(target=sync_loop, daemon=True).start()
    print(f"{C.COIN_NAME} node on {args.host}:{args.port}, height {chain.tip['height']}")
    ips = lan_addresses()
    if ips:
        print("Phones on the same Wi-Fi: set NODE_URI to " +
              " or ".join(f"http://{ip}:{args.port}" for ip in ips) + "  (or tap [FIND NODE] in the app)")
        print("If the phone can't connect, allow Python through your firewall on private networks.")
    try:
        from waitress import serve   # production-grade server when installed (pip install waitress)
        print("Serving with waitress")
        serve(app, host=args.host, port=args.port, threads=16)
    except ImportError:
        app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
