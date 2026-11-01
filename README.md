# Stellarite Miner

Two small cryptocurrencies built from scratch for learning, where mining does useful space work, plus a cyberpunk-styled Android app that mines them:

- **Pulsarite (PLSR)**: every block plans a probe's route past real nearby stars, which move while it travels.
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
                                    ◄───     { stars + positions, stops, fuel, baseline }
 plan the stars' order + each leg's speed
 POST /mining/route {route}         ───►     checks fuel, scores it: target × (baseline/time)^12
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

### 1. Get the app

Push this repo to GitHub, open the **Actions** tab, and download `stellarite-miner-apk` from the latest run (or open `android/` in Android Studio and press Run). Install it; Android will ask you to allow installs from that source. The app isn't on Google Play, which doesn't allow on-device mining apps.

### 2. Run the setup

The first time you open the app, setup walks you through:

1. **Username:** 3–16 characters (A–Z, 0–9, _). It goes on-chain: either your first mined block claims it, or tap **[CLAIM NOW]** on the RIG tab to register it straight away without mining or coins. Nobody else can use it on that network. People can send you coins by name, and the route map and mission log show who mined what.
2. **Wallet:** create one, or import a key from `wallet.py`. Setup shows your key and won't continue until you type its last 4 characters, to make sure you saved it. One key gives you both a `plsr…` and an `nblt…` address. Your username belongs to your address, so restoring the key restores the name.
3. **Where the blockchain runs:** solo on the phone, your computer, or a cloud server (see below).

You can run setup again from the LEDGER tab.

### 3. Choose where the blockchain runs

| Option | Best for | How |
|---|---|---|
| **Solo mode** | Trying it out, no computer at all | Tick **SOLO MODE** on the RIG tab, then **ENGAGE RIG** |
| **Your computer** | Mining at home | Double-click `start-nebulite.bat` / `start-pulsarite.bat` (Windows) or run `./start-nebulite.sh` (Mac/Linux), then tap **[FIND NODE]** in the app |
| **Cloud server** | Mining anywhere, inviting friends | Follow [DEPLOY.md](DEPLOY.md), then set NODE_URI to `https://your-domain/nebulite` |

**Solo mode** runs the coin's blockchain inside the app: same rules, same blocks, stored on the phone. It's a network of one, so it's for learning and testing. When you're ready, set NODE_URI to a computer or cloud node and tap **[PUSH CHAIN TO NODE]**. The node adopts your chain if it's valid and longer than its own, and your coins come with it. (A brand-new node always accepts it; a node that has been mining on its own keeps whichever chain has more work, so push early.) Solo chains hold mined blocks only: to send coins to someone, push to a node first.

**Start scripts** set up Python packages on first run, create a wallet if there isn't one, show your address, and start the node. They print the exact address to use in the app. You need Python 3 (on Windows, tick "Add python.exe to PATH" while installing it).

The app mines as a foreground service with a visible notification and a Stop button. It pauses automatically when:
- the phone is hot (thermal status severe),
- the battery is below 20% and unplugged,
- "Only mine while charging" is on (the default) and the phone is unplugged.

It uses half the CPU cores by default; you can change that with the CORES slider. The RIG tab shows your balance under the wallet address, from the solo chain or from the node, and your username in the top corner.

### Claiming your username

Under your balance, the RIG tab shows whether your username is on that coin's chain yet. If it isn't, tap **[CLAIM NOW]**: the phone does a few seconds of proof of work (up to about half a minute on older phones; it stops spam, since claims are free), signs the claim and sends it to the node. The name is yours once the next block is mined, by anyone. If your address already has a different name on-chain, the button says **[SWITCH]**, and switching frees the old name. Claiming needs a node; in solo mode your blocks claim it instead. From a computer: `python wallet.py claim NAME`.

### Sending coins

Tap **[SEND]** under your wallet address, then enter a username (e.g. `ORBIT`) or an address, an amount and a fee (0.00001 minimum). The app signs the transaction on the phone, so your key never leaves it, and the node includes it in the next block. Sending needs a node; solo chains hold mined blocks only.

### Running a node by hand (optional)

```bash
cd node                      # or: cd nebulite
pip install -r requirements.txt
python node.py               # Pulsarite on port 5000, Nebulite on 5001
python wallet.py new         # a computer wallet, if you prefer one
python wallet.py balance
python wallet.py send plsr<recipient-address> 12.5
python miner.py --address plsr…   # mine from the computer too
```

Version history, with each feature marked major, medium or minor: [CHANGELOG.md](CHANGELOG.md).

## Useful work: star routes

**The problem.** Each block's 24 stars are picked from the previous block's hash, so nobody can work on a block's route before that block exists. A probe launches from rest at the Sun in **2100** and must visit every star once. A route is a list of stars **and a cruise speed for each leg**, from 1% to 10% of light speed. The probe speeds up or slows down at a steady 0.03 g (0 to 10% of c takes 10 years and half a light-year), and flies past most stars at whatever speed it has. Four of each block's stars are **survey stops**, also picked from the hash: the probe must brake to a halt at each one, **survey it for 5 years plus 2 years per known planet** (riding along with the star as it moves), then speed up again. Stops favour **planetary systems**: a star's chance of being a stop is 1 + 3 × its number of confirmed planets, so TRAPPIST-1 (7 planets) is 22 times likelier than a star with none, and about 84% of stops are planet hosts. Planet counts come from Wikipedia's list of nearest exoplanets (confirmed planets only, November 2026). If it's moving too fast to stop in time, it overshoots and comes back.

**Fuel.** Every change of speed burns fuel. The probe's total speed change over the mission (its delta-v) must fit a budget of **50% of light speed**; a route that needs more is invalid. Flying everything at top speed would need about 90%, so a good route decides where speed is worth the fuel: fast on long runs of flybys, slower on legs into and out of stops (each stop costs the speed you arrive with plus the speed you leave with). The node also reports the **mass ratio** this implies by the rocket equation (an advanced fusion drive with 10%-of-c exhaust): typically about 150 tonnes of launch mass per tonne of probe.

**Stars move.** Every star has a space velocity (proper motion plus radial velocity). Over a mission lasting thousands of years they drift noticeably: Barnard's Star moves about half a light-year per thousand years. Each leg aims at where the star *will be* when the probe arrives, solved by iterating the intercept.

**The score is mission time.** Every node computes a greedy route ("fly to whichever star you can reach soonest") flown at the fastest single speed whose fuel fits (usually 5% of c) as the baseline. A route 10% faster makes the hash target (1/0.9)¹² ≈ 3.5× easier. In testing, optimised plans were 11–46% faster than greedy, for missions of roughly 2,500–5,500 years, and nearly always used the whole fuel budget. Everything (positions, velocities, speeds, fuel, times) is whole-number arithmetic, so every node and phone computes identical results; the app matches the node on 240 of 240 test plans (time, fuel, distance and baseline) and 5,000 of 5,000 individual legs.

**Why keep hashing at all?** Route quality alone can't set a steady block time, and the best route for a block would quickly become a known answer. The hash keeps blocks unpredictable and lets difficulty adjust; the route bonus makes optimisation the thing that wins.

**On the phone.** The rig plans each new block's route for about 2.5 seconds (a fast optimiser on mid-mission star positions, then an exact polish scored by true mission time, taking turns with a speed tuner that moves fuel between legs), starts hashing, then keeps refining every 10 seconds. The RIG screen shows the live route, e.g. `ROUTE 24★ · 4 STOPS · 4,098 YR · 299 LY · FUEL 100% · 46.4% FASTER THAN GREEDY`. On the MAP tab, survey stops are marked ◆; tap a star to see when the probe gets there, the leg's cruise speed and the fuel it burned, and tap the probe to see how much of the tank is used.

**The map.** `GET /routes` lists recent routes by star name with mission time, distance flown, survey stops, improvement and the miner's username. `GET /mining/work` includes the block's `stops`, `survey_years` and `dv_budget_pct_c`; route rows include `speeds_pct_c`, `fuel_used_pct` and `mass_ratio`. `GET /stars` shows the catalog with velocities.

**Using real star data.** The built-in catalog has ~50 well-known nearby systems with approximate positions and motions. For a serious network, build a catalog from the HYG database (positions and velocities from the Hipparcos and Gaia surveys):

```bash
python tools/build_catalog.py hygdata_v41.csv --max-ly 50 -o stars.json
```

Every node must use the same catalog (`GET /info` shows a `catalog_id` to compare), and changing it starts a new chain. Afterwards, run `python tools/gen_solo_data.py` so the app's solo mode matches, then rebuild the app.

**Limits.** Acceleration is constant (about 0.03 g) and doesn't depend on how much fuel is left, the fuel budget is a delta-v total rather than propellant mass, travel is in straight lines, and gravity and relativity are ignored (at 0.1c relativity changes times by only 0.5%). ROADMAP.md lists next steps.

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

## Troubleshooting

**The app can't reach the node ("can't reach … Is the node running?")**
1. Start the node on your computer: `cd node && python node.py` for Pulsarite, `cd nebulite && python node.py` for Nebulite. It prints the exact address to use, e.g. `set NODE_URI to http://192.168.40.10:5001`.
2. Put the phone on the same Wi-Fi as the computer, then tap **[FIND NODE]** on the RIG tab, or type that address.
3. Windows: when Python first runs, allow it through the firewall on **private networks**. macOS: allow incoming connections for Python.
4. Guest networks and some mesh Wi-Fi systems block devices from talking to each other. Use your main network.

**Solo mode says my chain wasn't adopted.** The node already has a chain with more work than yours (it has been mining on its own). Push to a fresh node, or keep mining that node directly.

**ENGAGE RIG does nothing.** The app explains why right under the button. Usually the wallet address is incomplete: run `python wallet.py new` in the coin's folder and paste the whole address (52 characters, `plsr…` or `nblt…`).

**Mining shows "PAUSED: NOT CHARGING".** CHARGING ONLY is on by default. Plug in, or untick it.

**A grey title bar appears at the top of the app.** An older version's file is still in your repo. When updating, replace the repo's contents with the new zip rather than copying over it, so deleted files go away. (This version prevents that particular file from causing problems.)

## Running more than one node

```bash
# second machine (or a second port)
python node.py --port 5001 --data ./data2 \
  --peer http://192.168.1.10:5000 --public-url http://192.168.1.11:5001
```

Nodes forward new blocks and transactions to each other and re-sync every 30 seconds, adopting whichever valid chain has the most work.

## Make it your own

1. **Name and economics:** edit `node/config.py` (`COIN_NAME`, `TICKER`, `ADDRESS_PREFIX`, reward, block time, genesis message).
2. **App:** match those in `android/core/src/main/java/com/example/stellariteminer/Coin.kt` and rename the app in `res/values/strings.xml`. To change the package name, update `namespace` and `applicationId` in `android/app/build.gradle.kts` and move the source folder.
3. **Start fresh:** changing `config.py` changes the genesis block, so delete `node/data/` on every node.
4. **Sign releases properly:** CI signs the APK with Android's debug key so it installs out of the box. Before sharing it widely, create your own keystore and set it as the release `signingConfig`.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/info` | height, tip hash, current target, peers |
| GET | `/chain`, `/blocks/<height>` | block data |
| GET | `/balance/<address>` | balance and next nonce |
| POST | `/tx` | submit a signed transaction, or a fee-free username claim (`"type": "name"`, with proof of work; `/info` gives `name_pow_bits`) |
| GET | `/mining/work?address=…` | get a job: this block's stars, baseline route, base target |
| POST | `/mining/route` | `{ "job_id", "route": [[star id, cruise % of c], …] }` → header prefix and the route's target |
| POST | `/mining/submit` | `{ "job_id", "route", "nonce" }` |
| GET | `/routes?limit=20` | the route map: recent blocks' routes, lengths, improvement |
| GET | `/stars` | the star catalog in use (with `planets` per star) |
| GET | `/map` | the web map page; `/map/data` is its data |
| (Nebulite) GET | `/scouts?stars=1,49` | escape-mission blocks in the form Pulsarite blocks cite them as scouts |
| POST | `/chain/import` | offer a whole chain (e.g. from solo mode); adopted if valid and longer |
| GET | `/name/<name>` | the address that owns a username |
| GET | `/names` | every claimed username |

`GET /mining/work` takes an optional `&name=` to claim a username in the block's coinbase; `/balance/<address>` includes the address's `name`.

Nebulite's node has the same transaction, balance, chain and peer endpoints, plus `GET /mining/work`, `POST /mining/trajectory` (`{job_id, seq, days}`), `POST /mining/submit` (`{job_id, seq, days, nonce}`), `GET /missions`, `GET /planets` (orbital elements and physics constants) and the same `/map` and `/map/data`.
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

**The problem.** Each block's mission comes from the previous block's hash: get a spacecraft from Earth to Jupiter, Saturn, Uranus or Neptune, launching inside a 4-year window somewhere in 2025–2039, within a maximum flight time (8 to 30 years, depending on the target).

**Mission types.** The hash also picks what's flying, which changes how much time is worth:

| Type | Share of planet missions (4 blocks in 8) | A year of travel costs | Flight time allowed |
|---|---|---|---|
| Science (robotic probe) | 1 in 2 | 250 m/s | full (8–30 years) |
| Cargo (supplies) | 1 in 4 | 50 m/s | full |
| Crewed (people aboard) | 1 in 4 | 3,000 m/s | half (4–15 years) |

So the same block-to-block skill pays off differently: cargo missions favour long, fuel-saving loops past several planets, crewed missions favour fast, direct burns. Miners choose which planets to fly past on the way (Venus, Earth, Mars, and Jupiter or Saturn when they're on the way) and the date of each encounter.

**The cost** is what a mission planner cares about, in m/s of rocket effort:
- departure speed from Earth (what the launcher must supply)
- fuel burned at each flyby. Flybys are **powered**: the craft can burn at closest approach, where the planet's gravity well multiplies the burn's effect (the Oberth effect), and the closest-approach distance is chosen to give exactly the bend needed. Turning harder than the planet allows at a safe distance (1.1 planet radii) costs extra fuel
- arrival speed at the target (what must be shed to stop)
- travel time: each year of flight counts as 50, 250 or 3,000 m/s, depending on the mission type

Planets follow **real orbits** from the full **VSOP87A** planetary theory: all 39,198 terms, accurate to about 1 arcsecond for thousands of years, so missions arriving in the 2060s and beyond are as accurate as near-term ones. Masses are JPL DE440 values. Checked against reality, it puts recent Mars, Jupiter and Saturn oppositions within 12 minutes of the published times, and reproduces Mars' 2003 close approach (0.372719 AU) to six decimals. Flown on their actual dates, Voyager 1 and 2 need almost no fuel at their flybys, just as in reality. [ACCURACY.md](ACCURACY.md) has the full validation, including an N-body integration to 2150.

Each leg between planets is solved with Lambert's problem, the standard tool for "leave here on day A, arrive there on day B". The solver was checked against step-by-step orbit integration (agreement to 1e-11) and textbook Hohmann transfers. It refuses paths that dive inside Mercury's orbit, and flybys slower than 1 km/s, which aren't real gravity assists.

**The score.** Every node computes the best *direct* transfer on a coarse grid as the baseline. A trajectory 15% cheaper than that makes the hash target (1/0.85)¹² ≈ 7× easier. Only the first 1.6× of improvement counts (a cap of (1.6)¹² ≈ 280× easier), so no block can become effectively free to mine. In testing, the optimisers found Jupiter-assisted routes to Saturn and Uranus 14–20% cheaper than going direct, the same strategy the Voyager and Cassini missions used. Jupiter missions gain less (2–5%), because there's little to fly past on the way.

**Fair checking.** Costs involve floating-point maths, which can differ in the last digit between computers. Blocks therefore carry their claimed cost, and nodes accept it within 1 m/s of their own result, so rounding can never split the network. (The phone matches the node to 0.3 mm on planet positions and to 0.0000000002 m/s on mission costs.)

**On the phone.** The rig plans each new mission for about 3 seconds, searching every flyby sequence with up to 2 flybys, then keeps refining every 10 seconds while it hashes. The HUD shows the live plan, e.g. `SCIENCE MISSION E-J-S · 11.53 KM/S · 8.6 YR · ARRIVES 2041-03-14 · 20.7% CHEAPER THAN DIRECT`, and the ledger records missions planned and your best mission.

**The mission log.** `GET /missions` lists recent blocks' trajectories: mission type, planet path, encounter days and calendar dates (`launch_date`, `arrival_date`, `encounters`), Δv, years and improvement. `GET /mining/work` includes the mission's `type` and `time_penalty_mps_per_year`.

## Nebulite × Pulsarite: leaving the solar system

The two coins work as one pipeline for interstellar missions: **Nebulite plans the departure from the solar system, and Pulsarite plans the journey between the stars.**

Out of every 8 Nebulite blocks, **2 are escape missions**, **1 is a heliopause run** and **1 is an interstellar-object intercept** (below); the other 4 are planet missions.

An **escape mission**: The block's hash picks a target star from Pulsarite's catalog, favouring stars with known planets (the same rule as Pulsarite's survey stops). The miner must get a probe out of the solar system on a path whose final direction points **exactly** at that star, as fast as possible. The score is the **time from launch until the probe passes 550 AU**, where the Sun's gravity starts to focus light from the target star into a telescope. Pulsarite takes it from there.

- **Launch:** up to 17 km/s from Earth (C3 ≈ 290 km²/s²). That's an SLS-class rocket with kick stages, the assumption of the Johns Hopkins APL Interstellar Probe study.
- **Fuel after launch:** up to 3 km/s in total, for burns at flybys and at the Sun.
- **Flybys:** Venus, Earth, Mars, Jupiter and Saturn, up to three, each with an optional burn at closest approach (a powered flyby, the "Jupiter Oberth" option the Interstellar Probe study favoured). A flyby at Jupiter or Saturn can also tilt the path out of the planets' plane, toward stars far above or below it, the way Ulysses left the ecliptic.
- **Sun dives:** a path may fall to as close as 0.05 AU (about the Parker Solar Probe's distance) and burn at perihelion, the "solar Oberth" manoeuvre. In this model dives rarely pay off: getting from Jupiter onto a sunward orbit costs most of the fuel. That matches the Interstellar Probe study's own conclusion that the manoeuvre "offers no advantage over prograde gravity assists". Miners still find the occasional geometry where one helps.
- **Aim:** the escape asymptote points at the star to better than a billionth of a radian. The 550 AU timing is checked against a direct numerical integration.
- **Always solvable:** a block only becomes an escape mission if the baseline search finds a working path toward its star; otherwise it's a planet mission. Every escape block therefore has at least one valid answer.
- **Baseline:** the best of three textbook strategies on a coarse grid (direct launch, Jupiter flyby, Jupiter flyby plus Sun dive), each at the fastest speed its limits allow.

Typical results in testing: the best escapes left at 30–37 km/s (**6–8 AU per year**, about twice Voyager 1's 3.6), reaching 550 AU in 70–90 years. Most were 20–30 km/s, and awkward star directions in poor launch windows can be much slower. APL's Interstellar Probe study targets about 7 AU per year with today's technology. Even so, Alpha Centauri is tens of thousands of years away at these speeds. Reaching the stars needs new propulsion, and these departures are the first leg of any such mission. The mission log, HUD, MAP tab and web map show each escape's target star, speed and the year it passes 550 AU, with a pointer toward the star.

### Heliopause runs

A heliopause run is an escape aimed at the **nose of the heliosphere**, the direction the interstellar wind blows in from (ecliptic longitude 255.7°, latitude 5.1°, measured by NASA's IBEX). It's scored by the time to reach **120 AU**, about where Voyager 1 (2012) and Voyager 2 (2018) crossed the heliopause into interstellar space. This is the first goal of the Interstellar Probe study. Same launch, fuel, flyby and Sun-dive rules as an escape. In testing the best runs reach 120 AU in **16–20 years** (Voyager 1 took 35). Heliopause runs aren't aimed at a star, so they can't be Pulsarite scouts.

### Interstellar-object intercepts

Objects from other stars pass through the solar system: 'Oumuamua (2017), Borisov (2019) and 3I/ATLAS (2025). They're found only months before their closest approach to the Sun, and then they leave for good. An intercept block draws one on a hyperbolic orbit within the range of those three:

- **The object:** 20–60 km/s far from the Sun, closest approach 0.3–3 AU, arriving from any direction in the sky, closest to the Sun 300–900 days after its discovery (the block's window start).
- **The probe:** launches 60–730 days after discovery and must reach the object within 6 years, with up to three flybys of Venus, Earth, Mars or Jupiter.
- **The cost:** launch and flyby burns, plus the speed of the encounter at a **tenth** of its value (a flyby past the object, like ESA's Comet Interceptor, not a rendezvous), plus 250 m/s per year of flight.
- **The orbit** is an exact Kepler hyperbola; tests check it against a step-by-step integration (under 1 km apart after 800 days).

Typical plans launch at 4–9 km/s and meet the object at 25–60 km/s. Mission rows show the object's discovery date, its speed, its closest approach and the encounter speed, and the maps draw its path in pink.

### Scouts: how Nebulite's escapes guide Pulsarite's routes

Pulsarite's probe assumes a future drive, reaching 10% of light speed, while Nebulite's craft are chemical rockets we could launch this decade. A literal hand-off would barely help Pulsarite: Nebulite's 35 km/s is a thousandth of its speed. Instead the two coins link the way real exploration works: **scout first, then send the big probe.**

- **A Nebulite escape is a scout.** Past 550 AU it uses the Sun's gravity as a lens to image its target star's planets.
- **A scouted stop becomes a flyby.** When a Pulsarite block's survey stop has been scouted, the probe doesn't need to stop there: it flies past at speed, with no braking, no survey years, and much less fuel. In testing, one scouted stop made a whole mission 12–24% faster (600–1,200 years), and four made it about 40% faster.
- **The proof travels in the block.** A Pulsarite block cites a scout by including the Nebulite block itself (header, trajectory and nonce). Every Pulsarite node re-checks the escape physics and the proof of work on its own, so it never contacts the Nebulite network and neither chain can stall the other.
- **Forging doesn't pay.** A cited Nebulite block must carry at least a third of the hashing the Pulsarite block needs. Each Nebulite block can be cited only once. Scouts can make a Pulsarite hash target at most about 1.27× easier, which saves at most 21% of the hashing. Even someone citing their own fake scout, and collecting its 5% reward, gains less than the third of a block's work the fake scout cost, while the full time saving still shows in the mission log and maps.
- **Scouts get paid.** Each cited scout earns its Nebulite miner **5% of the Pulsarite block reward** (2.5 PLSR today), newly minted and paid in the citing block's coinbase. The Pulsarite miner keeps their full reward. Payment goes to the same wallet's Pulsarite address: one key gives both a `nblt…` and a `plsr…` address that differ only in prefix, so mining Nebulite escapes earns Pulsarite too. The proof carries the Nebulite block's coinbase and transaction IDs, and every node checks they reproduce the block's `tx_root`, so the payee can't be swapped.
- **Automatic for miners.** Start the Pulsarite node with `NEBULITE_URL` set to a Nebulite node (the Docker setup does this). It then fetches escape missions from that node's `/scouts`, checks them, and attaches the best one for each survey stop to the work it hands out. Phones and `miner.py` simply see the scouted stops as flybys. The RIG line shows `+ 1 SCOUTED`, and the maps mark scouted stars ✦.
- **Solo mode too:** with SOLO MODE on, Pulsarite routes can cite escape missions from the phone's own Nebulite solo chain. Mine some Nebulite solo blocks first; about 2 in 8 are escape missions toward a star. The same rules apply as on a node (proof in the block, work rule, cite once), so a solo chain with scouts is accepted when you push it, as long as you push the Nebulite chain to the matching Nebulite network as well.

`python tools/make_scouts.py` mines Nebulite escape blocks for testing and demos.

Every Nebulite node reports `star_catalog_id` in `/info`. It should equal the Pulsarite node's `catalog_id`, which confirms both coins use the same stars. `nebulite/star_targets.json` is generated from Pulsarite's catalog by `tools/gen_solo_data.py`.

**Limits today.** Paths are patched conics: the planets' gravity is ignored between encounters, and flybys are treated as instantaneous. That is now the largest source of error, far above the planet positions. There are also no deep-space engine burns or multi-loop transfers, and arrival is scored as arrival speed rather than orbit insertion. ROADMAP.md covers each of these.

## Using the coins in the Stellura wallet

[Stellura](https://github.com/courier-iot/Stellura-Crypto-Wallet) holds, sends and mines Pulsarite and Nebulite next to its other test coins. It derives one key for both coins from its recovery phrase (path `m/44'/7827'/0'/0/0`), shows both addresses, sends to addresses or `@names`, claims usernames, and mines solo or with your node, using the same engine as this app.

The engine lives in `android/core`. After each release, run `tools/sync-stellarite-core.sh <path to this repo>` in the Stellura repo and commit, so the wallet follows the same consensus rules. Stellura only connects over HTTPS, so point it at a cloud node set up with [DEPLOY.md](DEPLOY.md).

## The MAP tab

A rotating 3D map of the useful work. Drag to rotate, pinch to zoom (star names appear as you zoom in), double-tap to reset. **Tap** any star, planet or encounter for details: distance, speed, orbit, flyby dates. The **time slider** flies the live plan (or the latest mined one):

- Pulsarite: the probe moves along the route while every star drifts to where it really is that year; visited stars turn amber.
- Nebulite: the spacecraft follows its real trajectory while the planets move on their orbits.

- **PLSR, star map:** every catalog star around the Sun with distance rings at 10, 20, 30 and 40 light-years. Recently mined routes are drawn in crimson, and the route your rig is optimising right now is drawn in amber, with its stars highlighted.
- **NBLT, orbit map:** the planets' real orbits, with distances compressed so Mercury and Neptune both fit on screen. Recently mined missions are in crimson, and your rig's live mission plan is in amber, with each encounter labelled (e.g. `FLYBY JUPITER 2041`).

The map loads from the selected coin's node (`/stars` + `/routes`, or `/planets` + `/missions`). Tap **[REFRESH]** after changing nodes. It isn't available for pool coins. Stars with known planets are marked ● with their count.

## The web map

Every node also serves the map as a web page at **`/map`**, so anyone can watch the network's work in a browser without the app: `http://<your computer's IP>:5000/map` for Pulsarite, `:5001/map` for Nebulite, or `https://your-domain/pulsarite/map` and `https://your-domain/nebulite/map` on a cloud server. Drag to rotate, scroll or pinch to zoom, tap a star, planet or flyby for details, and pick a block from the list to highlight its route or mission. It refreshes every 30 seconds. Distances are compressed (square root) so near and far objects both fit; directions are true. The page gets its data from `GET /map/data`.

## Known limitations (good next steps)

- Transactions are listed in a block rather than committed in a Merkle tree, so light clients can't verify inclusion.
- Peers sync by downloading the whole chain, which is fine for thousands of blocks but not millions.
- No HTTPS or authentication on the node; keep it on your home network or put it behind a reverse proxy.
- SHA-256 is simple but favours ASICs and GPUs. If you open the network to strangers, phones won't be competitive.
- Pool mining keeps each job's timestamp fixed rather than rolling it, which is fine at phone speeds.

## License

MIT
