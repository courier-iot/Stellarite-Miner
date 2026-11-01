"""Command-line wallet.

  python wallet.py new                       create a key, print your address
  python wallet.py address                   show your address
  python wallet.py balance [ADDRESS]         check a balance
  python wallet.py send ADDRESS AMOUNT       send coins (AMOUNT in whole coins, e.g. 1.5)

Options: --node http://host:5000   --wallet wallet.json
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal

import config as C
from crypto_utils import (address_from_pubkey, is_valid_address, new_private_key,
                          private_key_from_hex, private_key_to_hex, public_key_hex, sign)
from chain import tx_signing_bytes


def call(node, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(node.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def load(path):
    if not os.path.exists(path):
        sys.exit(f"No wallet at {path}. Run: python wallet.py new")
    with open(path) as f:
        return private_key_from_hex(json.load(f)["private_key"])


def to_units(amount: str) -> int:
    units = Decimal(amount) * C.UNITS_PER_COIN
    if units != units.to_integral_value() or units <= 0:
        sys.exit("Invalid amount")
    return int(units)


def main():
    ap = argparse.ArgumentParser(description=f"{C.COIN_NAME} wallet")
    ap.add_argument("--node", default=os.environ.get("NEBULITE_NODE", "http://127.0.0.1:5001"))
    ap.add_argument("--wallet", default="wallet.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new")
    sub.add_parser("address")
    b = sub.add_parser("balance"); b.add_argument("address", nargs="?")
    s = sub.add_parser("send"); s.add_argument("to"); s.add_argument("amount")
    s.add_argument("--fee", default=str(Decimal(C.MIN_FEE) / C.UNITS_PER_COIN))
    args = ap.parse_args()

    if args.cmd == "new":
        if os.path.exists(args.wallet):
            sys.exit(f"{args.wallet} already exists; refusing to overwrite it.")
        key = new_private_key()
        with open(args.wallet, "w") as f:
            json.dump({"private_key": private_key_to_hex(key)}, f)
        os.chmod(args.wallet, 0o600)
        print("Address:", address_from_pubkey(public_key_hex(key)))
        print(f"Private key saved to {args.wallet}. Back it up; losing it loses the coins.")
        return

    if args.cmd == "address":
        print(address_from_pubkey(public_key_hex(load(args.wallet))))
        return

    if args.cmd == "balance":
        addr = args.address or address_from_pubkey(public_key_hex(load(args.wallet)))
        r = call(args.node, f"/balance/{addr}")
        print(f"{addr}: {Decimal(r['balance']) / C.UNITS_PER_COIN} {C.TICKER}")
        return

    if args.cmd == "send":
        if not is_valid_address(args.to):
            sys.exit("Invalid recipient address")
        key = load(args.wallet)
        pub = public_key_hex(key)
        me = address_from_pubkey(pub)
        info = call(args.node, f"/balance/{me}")
        tx = {"from": pub, "to": args.to, "amount": to_units(args.amount),
              "fee": to_units(args.fee), "nonce": info["next_nonce"]}
        tx["sig"] = sign(key, tx_signing_bytes(tx))
        r = call(args.node, "/tx", tx)
        print(f"Sent. txid {r['txid']}" if r.get("ok") else f"Rejected: {r.get('error')}")


if __name__ == "__main__":
    main()
