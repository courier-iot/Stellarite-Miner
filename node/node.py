"""Pulsarite full node: HTTP API, star-route mining endpoints and simple peer-to-peer sync.

Run:  python node.py --port 5000 --data ./data [--peer http://other-node:5000]
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
import scouts
import stars
from chain import (Blockchain, ValidationError, block_hash, effective_target, header_prefix,
                   next_target, route_score, scout_work_ok, tx_sender, work)

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
            "catalog_id": stars.CATALOG_ID,
            "stars_per_block": stars.STARS_PER_PROBLEM,
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
# 1. GET  /mining/work?address=...   -> the stars this block must route through
# 2. POST /mining/route {job_id, route} -> header prefix + effective target for that route
#    (optimise the route first: shorter routes get an easier target)
# 3. search nonces: sha256d(prefix + 8-byte big-endian nonce) <= target
# 4. POST /mining/submit {job_id, route, nonce}

NEBULITE_URL = None              # set by --nebulite / NEBULITE_URL: where to find scouts
_scout_cache = {"key": None, "at": 0.0, "proofs": []}
_weak_scouts = {}                 # tip hash -> scouts that lacked work for a miner's route (not offered again)


def fetch_scouts(prev_hash):
    """Candidate scout proofs for this block's survey stops from the configured Nebulite node.
    A convenience only: every proof is re-verified, and blocks never depend on this call."""
    if not NEBULITE_URL:
        return []
    stops = stars.stops(prev_hash)
    key = (prev_hash, tuple(stops))
    if _scout_cache["key"] == key and time.time() - _scout_cache["at"] < 60:
        return _scout_cache["proofs"]
    try:
        url = NEBULITE_URL.rstrip("/") + "/scouts?stars=" + ",".join(map(str, stops))
        with urllib.request.urlopen(url, timeout=5) as r:
            proofs = [row["proof"] for row in json.loads(r.read())]
    except Exception as e:
        print(f"[scouts] couldn't reach the Nebulite node at {NEBULITE_URL}: {e}")
        proofs = []
    _scout_cache.update(key=key, at=time.time(), proofs=proofs)
    return proofs


@app.get("/mining/work")
def mining_work():
    address = request.args.get("address", "")
    name = request.args.get("name", "").strip().upper() or None
    candidates = fetch_scouts(chain.tip["hash"])
    try:
        with lock:
            weak = _weak_scouts.get(chain.tip["hash"], set())
            usable = (chain.usable_scouts(chain.tip["hash"], next_target(chain.blocks), candidates, weak)
                      if candidates else [])
            template = chain.build_template(address, name=name, scouts=usable)
            job_id = secrets.token_hex(8)
            jobs[job_id] = template
            while len(jobs) > MAX_JOBS:
                jobs.popitem(last=False)
    except ValidationError as e:
        return err(str(e))
    problem = stars.problem(template["prev_hash"])
    stop_ids = stars.stops(template["prev_hash"])
    baseline = stars.baseline_route(problem, stop_ids)
    cited = [scouts.verify(p) for p in template.get("scouts", [])]
    scouted = [c["star"] for c in cited]
    return jsonify({
        "job_id": job_id,
        "height": template["height"],
        "stars": [dict(stars.CATALOG[i]) for i in problem],
        "stops": [s for s in stop_ids if s not in scouted],      # scouted stops are flown past
        "survey_stops": stop_ids,
        "scouted": scouted,
        "scouts": [{"star": c["star"], "star_name": c["star_name"], "nebulite_block": c["hash"],
                    "vinf_kms": round(c["vinf_kms"], 1), "au_per_year": round(c["au_per_year"], 2)} for c in cited],
        "baseline_route": baseline,
        "baseline_years": stars.route_time(baseline, stop_ids) / 1000,
        "survey_years": C.SURVEY_YEARS,
        "survey_years_per_planet": C.SURVEY_YEARS_PER_PLANET,
        "dv_budget_pct_c": C.DV_BUDGET_PCT_C,
        "probe_speed_mly_per_year": stars.SPEED,
        "probe_accel_mly_per_year2": C.PROBE_ACCEL_MLY_PER_YEAR2,
        "launch_t": stars.LAUNCH_T,
        "intercept_iterations": stars.INTERCEPT_ITERATIONS,
        "base_target": template["target"],
        "bonus_exponent": C.ROUTE_BONUS_EXPONENT,
        "reward": template["txs"][0]["amount"],
        "units_per_coin": C.UNITS_PER_COIN,
    })


def _job_block(job_id, route):
    template = jobs.get(job_id)
    if template is None:
        raise LookupError("unknown or expired job")
    scouted = [scouts.verify(p)["star"] for p in template.get("scouts", [])]
    score = route_score(template["prev_hash"], route, scouted)
    block = dict(template, route=list(route))
    return template, block, score


@app.post("/mining/route")
def mining_route():
    body = request.get_json(silent=True) or {}
    with lock:
        try:
            _, block, score = _job_block(body.get("job_id"), body.get("route"))
        except LookupError as e:
            return err(str(e), 410)
        except ValidationError as e:
            return err(str(e))
    target = effective_target(block["target"], score["length"], score["baseline"])
    weak = [v for v in (scouts.verify(p) for p in block.get("scouts", [])) if not scout_work_ok(v, target)]
    if weak:
        _weak_scouts.setdefault(block["prev_hash"], set()).update(v["hash"] for v in weak)
        names = ", ".join(v["star_name"] for v in weak)
        return err(f"the Nebulite scout of {names} doesn't carry enough work for this route; "
                   "fetch new work (it won't be offered again for this block)", 409)
    return jsonify({
        "prefix": header_prefix(block).hex(),
        "target": format(target, "064x"),
        "years": score["mission_time"] / 1000,
        "scored_years": score["length"] / 1000,      # what the hash target uses (scout benefit capped)
        "baseline_years": score["baseline"] / 1000,
        "length_ly": stars.route_length(body.get("route"), score["stops"]) / 1000,
        "fuel_used_pct": round(100 * score["dv"] / stars.DV_BUDGET, 1),
        "improvement_pct": round(100 * (1 - score["mission_time"] / score["baseline"]), 2),
        "scouted": len(block.get("scouts", [])),
    })


@app.post("/mining/submit")
def mining_submit():
    body = request.get_json(silent=True) or {}
    with lock:
        try:
            template, block, _ = _job_block(body.get("job_id"), body.get("route"))
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


# ---- the route map ------------------------------------------------------



_MAP_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map.html")
_map_cache = {}


@app.get("/map")
def map_page():
    """A 3D map of the network's useful work, for any browser."""
    with open(_MAP_HTML, encoding="utf-8") as f:
        return app.response_class(f.read(), mimetype="text/html")


@app.get("/map/data")
def map_data():
    """Everything the web map draws: stars at launch, recent routes through their intercept points."""
    limit = max(1, min(request.args.get("limit", 12, type=int), 50))
    with lock:
        key = (chain.tip["hash"], limit)
        if key not in _map_cache:
            rows = chain.route_stats(limit)
            for r, b in zip(rows, reversed(chain.blocks[1:][-limit:])):
                legs = stars.route_legs(b["route"], stars.stops(b["prev_hash"]))
                r["points"] = [[0, 0, 0]] + [[c / 1000 for c in stars.pos(l[0], l[1])] for l in legs]
                r["arrive_years"] = [l[1] / 1000 + 2000 for l in legs]
            _map_cache.clear()
            _map_cache[key] = {
                "coin": C.COIN_NAME, "ticker": C.TICKER, "height": len(chain.blocks) - 1,
                "launch_year": C.LAUNCH_YEAR,
                "stars": [{"id": s["id"], "name": s["name"], "planets": s["planets"],
                           "p": [c / 1000 for c in stars.pos(s["id"], stars.LAUNCH_T)]} for s in stars.CATALOG],
                "routes": rows,
            }
        return jsonify(_map_cache[key])


@app.get("/routes")
def routes():
    """Recent blocks' star routes: the map the network is building."""
    limit = max(1, min(request.args.get("limit", 20, type=int), 200))
    with lock:
        return jsonify(chain.route_stats(limit))


@app.get("/stars")
def star_catalog():
    return jsonify({"source": stars.CATALOG_SOURCE, "catalog_id": stars.CATALOG_ID,
                    "count": len(stars.CATALOG), "stars": stars.CATALOG,
                    "probe_speed_mly_per_year": stars.SPEED, "launch_t": stars.LAUNCH_T,
                    "probe_accel_mly_per_year2": C.PROBE_ACCEL_MLY_PER_YEAR2,
                    "survey_stops": stars.SURVEY_STOPS, "survey_years": C.SURVEY_YEARS,
                    "survey_years_per_planet": C.SURVEY_YEARS_PER_PLANET,
                    "dv_budget_pct_c": C.DV_BUDGET_PCT_C,
                    "intercept_iterations": stars.INTERCEPT_ITERATIONS})


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
    global chain, self_url, NEBULITE_URL
    ap = argparse.ArgumentParser(description=f"{C.COIN_NAME} node")
    env = os.environ   # every option can also come from the environment (handy for Docker)
    ap.add_argument("--host", default=env.get("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(env.get("PORT", 5000)))
    ap.add_argument("--data", default=env.get("DATA_DIR", "./data"), help="where chain.json is stored")
    ap.add_argument("--peer", action="append",
                    default=[p for p in env.get("PEERS", "").split(",") if p.strip()],
                    help="peer node URL (repeatable; env PEERS is comma-separated)")
    ap.add_argument("--public-url", default=env.get("PUBLIC_URL"), help="URL other nodes use to reach this one")
    ap.add_argument("--nebulite", default=env.get("NEBULITE_URL"),
                    help="a Nebulite node to fetch scouts from (its escape missions guide routes); optional")
    args = ap.parse_args()

    chain = Blockchain(args.data)
    NEBULITE_URL = args.nebulite
    self_url = args.public_url
    for p in args.peer:
        peers.add(p.rstrip("/"))
        if self_url:
            try:
                http_json(p.rstrip("/") + "/peers", {"url": self_url})
            except Exception:
                pass
    threading.Thread(target=sync_loop, daemon=True).start()
    print(f"{C.COIN_NAME} node on {args.host}:{args.port}, height {chain.tip['height']}, "
          f"star catalog: {stars.CATALOG_SOURCE} ({len(stars.CATALOG)} stars, id {stars.CATALOG_ID})")
    if NEBULITE_URL:
        print(f"Scouts: Nebulite escape missions from {NEBULITE_URL} can guide routes"
              + ("" if scouts.NT else " (but Nebulite's physics files are missing, so none can be checked)"))
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
