# Stellarite Miner

Two small cryptocurrencies built from scratch for learning, where mining does useful space work, plus a cyberpunk-styled Android app that mines them:

- **Pulsarite (PLSR)**: every block maps a short route between real nearby stars.
- **Nebulite (NBLT)**: every block plans a spacecraft trajectory to an outer planet, using gravity-assist flybys to save fuel and travel time.

**Stellarite Miner** mines both, and can also mine Bitcoin and other SHA-256d coins through mining pools. See [ROADMAP.md](ROADMAP.md) for what's next, including star movement and travel time.

- **`node/`**: the Pulsarite full node (Python): blocks, signed transactions, star-route proof of work, automatic difficulty adjustment, peer sync, a mining API, a CLI wallet, and a reference miner.
- **`nebulite/`**: the Nebulite full node, a separate coin with its own chain, addresses (`nblt…`) and port (5001), using trajectory proof of work.
- **`android/`**: Kotlin app ("Stellarite Miner") with the Neon Pulsar theme. It mines Pulsarite through your node, or Bitcoin, Bitcoin Cash and other SHA-256d coins through any Stratum v1 pool, and keeps a ledger of everything you've mined.
- **`.github/workflows/build.yml`**: runs both nodes' tests and builds the APK on every push. Tag a release (`v1.0`) and the APK is attached to it.

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
| PLSR | Pulsarite | your Pulsarite node (`http://…:5000`) |
| NBLT | Nebulite | your Nebulite node (`http://…:5001`) |
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

Nebulite's node has the same transaction, balance, chain and peer endpoints, plus `GET /mining/work`, `POST /mining/trajectory` (`{job_id, seq, days}`), `POST /mining/submit` (`{job_id, seq, days, nonce}`), `GET /missions` and `GET /planets` (orbital elements and physics constants).
| GET/POST | `/peers` | list / add peers |
| POST | `/blocks` | peers announce new blocks |

## Tests

```bash
cd node && python -m unittest discover tests -v
```

The tests cover rewards, transfers, fees, replay and overspend protection, tampered signatures, invalid proof-of-work, inflated coinbases, difficulty adjustment, chain reorganisation, persistence, star-route validation (routes must cover the block's stars, are bound into the hash, and shorter routes get easier targets), the route map, and the full HTTP mining flow.

The app's pool-mining code was checked against a real Bitcoin block (block 125552's header hashes correctly) and against a test Stratum pool that independently verified every submitted share.

## Nebulite: spacecraft trajectories

Nebulite is a separate coin with its own chain, wallet addresses (`nblt…`), node and default port (5001). Run it alongside Pulsarite or on its own:

```bash
cd nebulite
pip install -r requirements.txt
python node.py --port 5001 --data ./data
python wallet.py new                 # prints your nblt… address
python miner.py --address nblt…      # optional: mine from the computer
```

In the app, pick the **NBLT** chip, enter `http://<your computer's IP>:5001` and your `nblt…` address.

**The problem.** Each block's mission comes from the previous block's hash: get a spacecraft from Earth to Jupiter, Saturn, Uranus or Neptune, launching inside a 4-year window somewhere in 2025–2039, within a maximum flight time (8 to 30 years, depending on the target). Miners choose which planets to fly past on the way (Venus, Earth, Mars, and Jupiter or Saturn when they're on the way) and the date of each encounter.

**The cost** is what a mission planner cares about, in m/s of rocket effort:
- departure speed from Earth (what the launcher must supply)
- fuel burned at each flyby: making up speed differences, or turning harder than the planet's gravity allows at a safe distance (1.1 planet radii)
- arrival speed at the target (what must be shed to stop)
- travel time: each year of flight counts as 250 m/s

Planets follow **real orbits**: JPL's approximate Keplerian elements with their slow drift over time, giving elliptical, tilted orbits in 3D (valid 1800–2050). Checked against reality, the model puts Mars-through-Neptune oppositions within a day of the real dates and Mars' 2003 close approach within 0.0003 AU. Flown on their actual dates, Voyager 1 and 2 need almost no fuel at their flybys, just as in reality.

Each leg between planets is solved with Lambert's problem, the standard tool for "leave here on day A, arrive there on day B". The solver was checked against step-by-step orbit integration (agreement to 1e-11) and textbook Hohmann transfers. It refuses paths that dive inside Mercury's orbit, and flybys slower than 1 km/s, which aren't real gravity assists.

**The score.** Every node computes the best *direct* transfer on a coarse grid as the baseline. A trajectory 15% cheaper than that makes the hash target (1/0.85)¹² ≈ 7× easier. In testing, the optimisers found Jupiter-assisted routes to Saturn and Uranus 14–20% cheaper than going direct, the same strategy the Voyager and Cassini missions used. Jupiter missions gain less (2–5%), because there's little to fly past on the way.

**Fair checking.** Costs involve floating-point maths, which can differ in the last digit between computers. Blocks therefore carry their claimed cost, and nodes accept it within 1 m/s of their own result, so rounding can never split the network. (The phone's Kotlin physics matches the node's Python to 0.000005 m/s across 3,600 test trajectories.)

**On the phone.** The rig plans each new mission for about 3 seconds, searching every flyby sequence with up to 2 flybys, then keeps refining every 10 seconds while it hashes. The HUD shows the live plan, e.g. `MISSION E-J-S · 11.53 KM/S · 8.6 YR · 20.7% CHEAPER THAN DIRECT`, and the ledger records missions planned and your best mission.

**The mission log.** `GET /missions` lists recent blocks' trajectories: planet path, encounter days, Δv, years and improvement.

**Limits today.** There are no deep-space engine burns or multi-loop transfers, arrival is scored as arrival speed rather than orbit insertion, and the orbital elements are fitted for 1800–2050, so very late arrivals lose some accuracy. ROADMAP.md covers each of these.

## The MAP tab

A rotating 3D map of the useful work. Drag to rotate, pinch to zoom (star names appear as you zoom in), double-tap to reset.

- **PLSR, star map:** every catalog star around the Sun with distance rings at 10, 20, 30 and 40 light-years. Recently mined routes are drawn in crimson, and the route your rig is optimising right now is drawn in amber, with its stars highlighted.
- **NBLT, orbit map:** the planets' real orbits, with distances compressed so Mercury and Neptune both fit on screen. Recently mined missions are in crimson, and your rig's live mission plan is in amber, with each encounter labelled (e.g. `FLYBY JUPITER 2041`).

Previews rendered from live node data: [star map](docs/map-preview-stars.png), [orbit map](docs/map-preview-orbits.png).

The map loads from the selected coin's node (`/stars` + `/routes`, or `/planets` + `/missions`). Tap **[REFRESH]** after changing nodes. It isn't available for pool coins.

## Known limitations (good next steps)

- Transactions are listed in a block rather than committed in a Merkle tree, so light clients can't verify inclusion.
- Peers sync by downloading the whole chain, which is fine for thousands of blocks but not millions.
- No HTTPS or authentication on the node; keep it on your home network or put it behind a reverse proxy.
- SHA-256 is simple but favours ASICs and GPUs. If you open the network to strangers, phones won't be competitive.
- Pool mining keeps each job's timestamp fixed rather than rolling it, which is fine at phone speeds.

## License

MIT
