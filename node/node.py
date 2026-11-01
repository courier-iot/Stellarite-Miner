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
import stars
from chain import (Blockchain, ValidationError, block_hash, effective_target, header_prefix,
                   next_target, route_score, tx_sender, work)

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
    problem = stars.problem(template["prev_hash"])
    baseline = stars.baseline_route(problem)
    return jsonify({
        "job_id": job_id,
        "height": template["height"],
        "stars": [dict(stars.CATALOG[i]) for i in problem],
        "baseline_route": baseline,
        "baseline_years": stars.route_time(baseline) / 1000,
        "probe_speed_mly_per_year": stars.SPEED,
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
    score = route_score(template["prev_hash"], route)
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
    return jsonify({
        "prefix": header_prefix(block).hex(),
        "target": format(target, "064x"),
        "years": score["length"] / 1000,
        "baseline_years": score["baseline"] / 1000,
        "length_ly": stars.route_length(body.get("route")) / 1000,
        "improvement_pct": round(100 * (1 - score["length"] / score["baseline"]), 2),
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
    global chain, self_url
    ap = argparse.ArgumentParser(description=f"{C.COIN_NAME} node")
    env = os.environ   # every option can also come from the environment (handy for Docker)
    ap.add_argument("--host", default=env.get("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(env.get("PORT", 5000)))
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
    print(f"{C.COIN_NAME} node on {args.host}:{args.port}, height {chain.tip['height']}, "
          f"star catalog: {stars.CATALOG_SOURCE} ({len(stars.CATALOG)} stars, id {stars.CATALOG_ID})")
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
