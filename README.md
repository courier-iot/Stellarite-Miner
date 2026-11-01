# Stellarite Miner

**Pulsarite (PLSR)** is a small cryptocurrency built from scratch for learning, where mining does useful work: every block maps a short route between real nearby stars. **Stellarite Miner** is a cyberpunk-styled Android app that mines it, and can also mine Bitcoin and other SHA-256d coins through mining pools.

- **`node/`**: Python full node with blocks, signed transactions, SHA-256d proof-of-work, automatic difficulty adjustment, peer sync, a mining API, a CLI wallet, and a reference CPU miner.
- **`android/`**: Kotlin app ("Stellarite Miner") with the Neon Pulsar theme. It mines Pulsarite through your node, or Bitcoin, Bitcoin Cash and other SHA-256d coins through any Stratum v1 pool, and keeps a ledger of everything you've mined.
- **`.github/workflows/build.yml`**: runs the node tests and builds the APK on every push. Tag a release (`v1.0`) and the APK is attached to it.

> This is a teaching coin. The code is readable and tested, but it has not been audited. Don't treat PLSR as something with real monetary value.

## How it works

Pulsarite uses **proof of useful work**. Every block must carry a route that starts at the Sun and visits 24 nearby stars, chosen unpredictably from the previous block's hash. Shorter routes make the block's hash target exponentially easier to hit, so miners compete on finding good routes, and the network builds up a map of efficient paths between stars as it goes.

```
 phone (Stellarite Miner)                    your computer (node.py)
 ────────────────────────                    ───────────────────────
 GET /mining/work?address=plsr…     ───►     picks this block's 24 stars
                                    ◄───     { stars + positions, baseline }
 optimise a route through the stars
 POST /mining/route {route}         ───►     scores it: target × (baseline/length)^12
                                    ◄───     { header prefix, easier target }
 hash: sha256d(prefix + nonce) <= target ?
   (keep shortening the route every 10 s)
 POST /mining/submit {route, nonce} ───►     re-checks route + hash, adds block,
                                              pays reward, adds route to the map
```

| Setting | Default | Where |
|---|---|---|
| Block reward | 50 PLSR, halving every 100,000 blocks | `node/config.py` |
| Target block time | 30 seconds | `node/config.py` |
| Difficulty retarget | every 10 blocks, max 4× change | `node/config.py` |
| Starting difficulty | 2²⁰ hashes per block (~1M) at a baseline route | `PULSARITE_DIFFICULTY_BITS` env var |
| Stars per block | 24 | `node/stars.py` |
| Route bonus | target × (baseline ÷ route length)¹² | `ROUTE_BONUS_EXPONENT` in `node/config.py` |
| Star catalog | ~50 nearby systems built in, or your own `stars.json` | `node/stars.py`, `node/tools/build_catalog.py` |
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
3. Pick **PLSR** under TARGET_COIN, enter the node URL and your address, tap **[PING]** to test the link, then **ENGAGE RIG**.

The app mines as a foreground service with a visible notification and a Stop button. It pauses automatically when:
- the phone is hot (thermal status severe),
- the battery is below 20% and unplugged,
- "Only mine while charging" is on (the default) and the phone is unplugged.

It uses half the CPU cores by default; you can change that with the CORES slider.

## Useful work: star routes

**The problem.** Each block's 24 stars are picked from the previous block's hash, so nobody can work on a block's route before that block exists. The route is an open path: it starts at the Sun and visits every star once. Distances are computed in whole milli-light-years so every node gets the exact same answer.

**The score.** Every node computes a greedy "nearest star next" route as the baseline. If your route is 10% shorter, your hash target is (1/0.9)¹² ≈ 3.5× easier. In testing, the optimiser beats the baseline by about 11% on average (up to ~20%), making blocks around 6× easier to find. A miner who only hashes, without optimising, is at a real disadvantage.

**Why keep hashing at all?** Route quality alone can't set a steady block time, and the best route for a block would quickly become a known answer that every miner submits. The hash keeps blocks unpredictable and lets difficulty adjust; the route bonus makes optimisation the thing that wins.

**On the phone.** The rig optimises each new block's route for about 2.5 seconds (2-opt and Or-opt with random restarts), starts hashing, then keeps refining the route every 10 seconds. The RIG screen shows the live route, e.g. `ROUTE 24★ · 218.6 LY · 11.8% SHORTER THAN GREEDY`, and the ledger records routes mapped and your best route.

**The map.** `GET /routes` lists recent blocks' routes by star name with their lengths and improvement, and `GET /stars` shows the catalog in use.

**Using real star data.** The built-in catalog has ~50 well-known nearby systems with approximate positions. For a serious network, build a catalog from the HYG database (positions from the Hipparcos and Gaia surveys):

```bash
python tools/build_catalog.py hygdata_v41.csv --max-ly 50 -o stars.json
```

Every node must use the same catalog (`GET /info` shows a `catalog_id` to compare), and changing it starts a new chain, so delete each node's `data/` folder. With a larger catalog you can raise `STARS_PER_PROBLEM` for harder, more useful routing problems.

**Be honest about the value.** Today these routes are a demonstration: real mission planning has to account for travel time, fuel and star motion, not just straight-line distance. The point is the framework. The network turns mining effort into solved routing problems that anyone can check, and the problem can be swapped for something richer later.

## Mining other coins (Bitcoin and friends)

The coin chips at the top of the RIG screen switch between:

| Chip | Coin | Connects to |
|---|---|---|
| PLSR | Pulsarite | your own node (`http://…:5000`) |
| BTC | Bitcoin | a Stratum v1 pool |
| BCH | Bitcoin Cash | a Stratum v1 pool |
| SHA | any other SHA-256d coin | a Stratum v1 pool |

For pools, enter:
- **POOL_URI**: `stratum+tcp://host:port` (or `stratum+ssl://` for TLS), from your pool's "getting started" page.
- **WORKER**: usually `yourPayoutAddress.workerName`; check the pool's docs.
- **POOL_PASS**: usually `x`. Many pools let you request a share difficulty here, such as `d=0.01`. Phones need a low difficulty to find shares at all.

Settings are saved separately for each coin.

**Be realistic about Bitcoin.** Bitcoin's network runs on industrial ASIC machines that are many millions of times faster than a phone. A phone (roughly 1–10 MH/s) will submit shares to a pool and show up on its dashboard, but the payout will round to zero and most pools never reach their minimum payout for a phone. Treat it as a way to see real pool mining work, not as income.

Only SHA-256d coins are supported. Coins built for CPU mining, like Monero (RandomX), would need a separate hashing engine; that's a good next step if you want a phone to earn something.

## The ledger

The **LEDGER** tab records every mining session on the phone: which coin, how long, how many hashes, and how many blocks or shares were accepted or rejected. Lifetime totals are shown per coin.

- For **Pulsarite**, it also shows coins earned, since the app knows each block's reward.
- For **pools**, earnings are decided and paid by the pool, so the ledger shows shares; check your pool's dashboard for balances.

The ledger is saved on the phone every 30 seconds while mining and when you stop. **[WIPE LEDGER]** clears it (it never affects coins you've earned).

## Theme

The app uses the Neon Pulsar look: pure black, neon crimson (#DC143C), amber highlights, HUD corner brackets, pulsing rings and faint scanlines. The GitHub build downloads the Orbitron and Share Tech Mono fonts (SIL Open Font License) into `android/app/src/main/assets/fonts/`. Builds without them use the phone's built-in fonts. Colors live in `Theme.kt` and `res/values/colors.xml`.

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
| GET | `/mining/work?address=…` | get a job: this block's stars, baseline route, base target |
| POST | `/mining/route` | `{ "job_id", "route" }` → header prefix and the route's target |
| POST | `/mining/submit` | `{ "job_id", "route", "nonce" }` |
| GET | `/routes?limit=20` | the route map: recent blocks' routes, lengths, improvement |
| GET | `/stars` | the star catalog in use |
| GET/POST | `/peers` | list / add peers |
| POST | `/blocks` | peers announce new blocks |

## Tests

```bash
cd node && python -m unittest discover tests -v
```

The tests cover rewards, transfers, fees, replay and overspend protection, tampered signatures, invalid proof-of-work, inflated coinbases, difficulty adjustment, chain reorganisation, persistence, star-route validation (routes must cover the block's stars, are bound into the hash, and shorter routes get easier targets), the route map, and the full HTTP mining flow.

The app's pool-mining code was checked against a real Bitcoin block (block 125552's header hashes correctly) and against a test Stratum pool that independently verified every submitted share.

## Coming next: Nebulite

**Nebulite (NBLT)** will be a separate coin with its own chain and node, using planet-hopping spacecraft trajectories (gravity assists) as its useful work. It will appear as its own chip in the app.

## Known limitations (good next steps)

- Transactions are listed in a block rather than committed in a Merkle tree, so light clients can't verify inclusion.
- Peers sync by downloading the whole chain, which is fine for thousands of blocks but not millions.
- No HTTPS or authentication on the node; keep it on your home network or put it behind a reverse proxy.
- SHA-256 is simple but favours ASICs and GPUs. If you open the network to strangers, phones won't be competitive.
- Pool mining keeps each job's timestamp fixed rather than rolling it, which is fine at phone speeds.

## License

MIT
