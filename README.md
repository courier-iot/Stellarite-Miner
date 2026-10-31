# Stellarite Miner

**Pulsarite (PLSR)** is a small proof-of-work cryptocurrency built from scratch for learning. **Stellarite Miner** is the Android app that mines it.

- **`node/`**: Python full node with blocks, signed transactions, SHA-256d proof-of-work, automatic difficulty adjustment, peer sync, a mining API, a CLI wallet, and a reference CPU miner.
- **`android/`**: Kotlin app ("Stellarite Miner") that fetches work from your node and mines on the phone's CPU.
- **`.github/workflows/build.yml`**: runs the node tests and builds the APK on every push. Tag a release (`v1.0`) and the APK is attached to it.

> This is a teaching coin. The code is readable and tested, but it has not been audited. Don't treat PLSR as something with real monetary value.

## How it works

```
 phone (Stellarite Miner)                 your computer (node.py)
 ────────────────────                 ───────────────────────
 GET /mining/work?address=plsr… ───►   builds a block template
                                ◄───  { prefix, target, job_id }
 try nonces:
   sha256(sha256(prefix + nonce)) <= target ?
 POST /mining/submit {job_id, nonce} ►  validates, adds block,
                                         pays reward, tells peers
```

| Setting | Default | Where |
|---|---|---|
| Block reward | 50 PLSR, halving every 100,000 blocks | `node/config.py` |
| Target block time | 30 seconds | `node/config.py` |
| Difficulty retarget | every 10 blocks, max 4× change | `node/config.py` |
| Starting difficulty | 2²⁰ hashes per block (~1M) | `PULSARITE_DIFFICULTY_BITS` env var |
| Smallest unit | 1 PLSR = 100,000,000 units | `node/config.py` |
| Ledger model | account balances + per-address nonce | `node/chain.py` |
| Fork choice | most cumulative work wins | `node/chain.py` |

## Quick start

### 1. Run a node (Python 3.10+)

```bash
cd node
pip install -r requirements.txt
python node.py --port 5000 --data ./data
```

The node listens on all interfaces so phones on your Wi-Fi can reach it. Find your computer's LAN IP (e.g. `192.168.1.10`); the phone will use `http://192.168.1.10:5000`.

### 2. Make a wallet

```bash
python wallet.py new          # prints your address: plsr…
```

`wallet.json` holds your private key. Back it up and never commit it (`.gitignore` already excludes it).

### 3. Mine from the phone

1. Get the APK: push this repo to GitHub, open the **Actions** tab, and download `stellarite-miner-apk` from the latest run. Or open `android/` in Android Studio and press Run.
2. Install it. Android will ask you to allow installs from that source; the app isn't on Google Play, which doesn't allow on-device mining apps.
3. Enter the node URL and your address, tap **Test connection**, then **Start mining**.

The app mines as a foreground service with a visible notification and a Stop button. It pauses automatically when:
- the phone is hot (thermal status severe),
- the battery is below 20% and unplugged,
- "Only mine while charging" is on (the default) and the phone is unplugged.

It uses half the CPU cores by default; you can change that with the slider.

### 4. Check balances and send coins

```bash
python wallet.py balance
python wallet.py send plsr<recipient-address> 12.5
```

You can also mine from a computer with `python miner.py --address plsr…`.

## Running more than one node

```bash
# second machine (or a second port)
python node.py --port 5001 --data ./data2 \
  --peer http://192.168.1.10:5000 --public-url http://192.168.1.11:5001
```

Nodes forward new blocks and transactions to each other and re-sync every 30 seconds, adopting whichever valid chain has the most work.

## Make it your own

1. **Name and economics:** edit `node/config.py` (`COIN_NAME`, `TICKER`, `ADDRESS_PREFIX`, reward, block time, genesis message).
2. **App:** match those in `android/app/src/main/java/com/example/stellariteminer/Coin.kt` and rename the app in `res/values/strings.xml`. To change the package name, update `namespace` and `applicationId` in `android/app/build.gradle.kts` and move the source folder.
3. **Start fresh:** changing `config.py` changes the genesis block, so delete `node/data/` on every node.
4. **Sign releases properly:** CI signs the APK with Android's debug key so it installs out of the box. Before sharing it widely, create your own keystore and set it as the release `signingConfig`.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/info` | height, tip hash, current target, peers |
| GET | `/chain`, `/blocks/<height>` | block data |
| GET | `/balance/<address>` | balance and next nonce |
| POST | `/tx` | submit a signed transaction |
| GET | `/mining/work?address=…` | get a job (`prefix`, `target`, `job_id`) |
| POST | `/mining/submit` | `{ "job_id", "nonce" }` |
| GET/POST | `/peers` | list / add peers |
| POST | `/blocks` | peers announce new blocks |

## Tests

```bash
cd node && python -m unittest discover tests -v
```

The tests cover rewards, transfers, fees, replay and overspend protection, tampered signatures, invalid proof-of-work, inflated coinbases, difficulty adjustment, chain reorganisation, persistence, and the full HTTP mining flow.

## Known limitations (good next steps)

- Transactions are listed in a block rather than committed in a Merkle tree, so light clients can't verify inclusion.
- Peers sync by downloading the whole chain, which is fine for thousands of blocks but not millions.
- No HTTPS or authentication on the node; keep it on your home network or put it behind a reverse proxy.
- SHA-256 is simple but favours ASICs and GPUs. If you open the network to strangers, phones won't be competitive.

## License

MIT
