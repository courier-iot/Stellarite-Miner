#!/usr/bin/env bash
# Starts the Pulsarite node on this computer (Mac/Linux). Run: ./start-pulsarite.sh
# First run: sets up Python packages in node/.venv and creates your wallet.
set -e
cd "$(dirname "$0")/node"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
if ! command -v $PY >/dev/null 2>&1; then
  echo "Python 3 isn't installed. Get it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "First run: setting up Python packages (one minute)..."
  $PY -m venv .venv
fi
source .venv/bin/activate
pip install -q --disable-pip-version-check -r requirements.txt

if [ ! -f wallet.json ]; then
  echo
  echo "Creating your Pulsarite wallet (back up node/wallet.json: it holds your coins' key)"
  python wallet.py new
fi
echo
echo "Your Pulsarite address (paste into the app's WALLET_ADDR):"
python wallet.py address
echo
python node.py --port 5000
