# Changelog

Release numbers are **MAJOR.MEDIUM.MINOR**, and every feature is tagged by size:

- **[MAJOR]** a new capability, or a change to the blockchain rules (a consensus change that starts a new chain)
- **[MEDIUM]** a notable addition or improvement to something that already exists
- **[MINOR]** a small tweak, a fix or polish

A release bumps the number for the biggest change in it and resets the ones after it: a major feature takes 5.4.3 to 6.0.0, a medium one to 5.5.0, and minor-only changes to 5.4.4. The app's `versionName` in `android/app/build.gradle.kts` matches the latest release here, and `versionCode` is MAJOR×10000 + MEDIUM×100 + MINOR (10.0.0 → 100000). Tag a release (e.g. `v7.0.0`) on GitHub and the workflow attaches the APK.

## 10.0.0: Nebulite scouts guide Pulsarite routes

- **[MAJOR]** Scouts: a Pulsarite block can cite Nebulite escape missions aimed at its survey stars. A scouted stop becomes a flyby: no braking, no survey and much less fuel, making missions 12–24% faster per scouted stop in testing. *Consensus change: new Pulsarite chain (genesis v6).*
- **[MAJOR]** Cross-chain proofs without cross-chain trust: the cited Nebulite block travels inside the Pulsarite block, and Pulsarite nodes re-check its escape physics and proof of work themselves (Nebulite's physics is loaded by `node/scouts.py`).
- **[MEDIUM]** Anti-forgery rules: a scout must carry at least 1/3 of the citing block's needed work, each Nebulite block can be cited once, and scouts ease a Pulsarite hash target by at most about 1.27×.
- **[MEDIUM]** The Pulsarite node fetches scouts from `NEBULITE_URL` and attaches the best valid one per survey stop to its work. A new Nebulite endpoint, `/scouts`, publishes escape blocks as proofs. Docker sets this up automatically.
- **[MINOR]** Scouted stars on the RIG line (`+ 1 SCOUTED`), the MAP tab and the web map (✦), and in `/routes` and `miner.py` output.
- **[MINOR]** `tools/make_scouts.py` mines Nebulite escape blocks for tests and demos.
- **[MINOR]** `numpy` is now a Pulsarite node requirement too (for checking scouts).

## 9.0.0: Escape missions, linking Nebulite and Pulsarite

- **[MAJOR]** Nebulite escape missions: about 1 block in 5 asks for a departure from the solar system aimed exactly at a star from Pulsarite's catalog (favouring planetary systems), scored by years from launch to 550 AU. Flybys of Venus to Saturn, optional Sun dives to 0.05 AU with a perihelion burn, a 17 km/s launch and 3 km/s of fuel. *Consensus change: new chain (genesis v4).*
- **[MAJOR]** The two coins become one interstellar pipeline: Nebulite plans the departure, Pulsarite the route between the stars. Both share one star catalog (`star_catalog_id` in `/info`).
- **[MEDIUM]** Escape blocks are always solvable: a block becomes an escape mission only if the baseline search finds a path to its star.
- **[MEDIUM]** Escape planning in the app (solo and node mining) and in `miner.py`, starting from the block's baseline plan. The best results reach 6–8 AU per year.
- **[MEDIUM]** The MAP tab and the web map draw escape paths, including Sun dives, with a pointer to the target star. The web map zooms out to fit them.
- **[MINOR]** Bonus cap: only the first 1.6× improvement over a baseline counts toward an easier hash target (all Nebulite missions).
- **[MINOR]** Fixed: solo mining with a username another address already owns on that chain produced blocks a node would refuse. The claim is now left out instead.
- **[MINOR]** The Lambert solver takes a per-mission minimum perihelion (0.3 AU for planet missions, 0.05 AU for escapes).

## 8.0.0: Planet positions accurate past 2050

- **[MAJOR]** Nebulite: planets now follow the full VSOP87A theory (all 39,198 terms, about 1″ for millennia) instead of JPL's approximate elements, which were only fitted for 1800–2050. Giant-planet positions improve from 1–10 million km off to the theory's arcsecond level. Earth is the planet itself, not the Earth-Moon barycentre. *Consensus change: new chain (genesis v3).*
- **[MEDIUM]** JPL DE440 masses for the Sun and planets, and the IAU astronomical unit.
- **[MEDIUM]** ACCURACY.md: validation against the official VSOP87 test values, real oppositions and Mars 2003, and an N-body integration to 2150, plus the error budget.
- **[MINOR]** The node reports `ephemeris_id`, and the app refuses to mine against a node with different planet data.
- **[MINOR]** Lambert solver: long-way transfers beyond the solver's range are handled explicitly and identically in node and app (they could crash the PC optimiser).
- **[MINOR]** Tighter real-world tests: oppositions to the hour, Mars 2003 to 0.000002 AU.
- **[MINOR]** `numpy` is now a Nebulite node requirement. The app bundles the planetary data (about 2 MB).

## 7.0.0: Planetary surveys, mission types and the web map

- **[MAJOR]** Pulsarite: survey stops favour planetary systems. Each star carries its confirmed-planet count, and its chance of being a stop is 1 + 3 × planets (84% of stops are now planet hosts). *Consensus change: new chain (genesis v5).*
- **[MAJOR]** Nebulite: mission types. Each block is a science, cargo or crewed mission, with its own value of travel time (250 / 50 / 3,000 m/s per year) and flight-time limit (crewed trips get half). The baseline and the score follow the mission. *Consensus change: new chain (genesis v2).*
- **[MAJOR]** Web map: every node serves an interactive 3D map at `/map` (routes among the stars, or missions among the planets), for any browser, with no app needed.
- **[MEDIUM]** Pulsarite: surveys take 2 extra years per known planet (TRAPPIST-1: 19 years).
- **[MEDIUM]** Nebulite: calendar dates for launch, each flyby and arrival in `/missions`, the RIG summary, the MAP tab and the PC miner.
- **[MINOR]** MAP tab: stars show their planet count (●), and the Nebulite legend explains the mission type.
- **[MINOR]** `GET /map/data` for the web map. `/stars` and `/mining/work` include planets per star.
- **[MINOR]** DEPLOY.md lists the map addresses to share.

## 6.0.0: Fuel and survey time

- **[MAJOR]** Pulsarite: each leg of a route now has its own cruise speed, from 1% to 10% of light speed. Routes are sent as `[[star id, speed], …]` pairs. *Consensus change: new chain (genesis v4).*
- **[MAJOR]** Pulsarite: fuel budget. The probe's total speed change over a mission must fit within 50% of light speed, so routes have to spend speed where it saves the most time. Routes that need more fuel are rejected.
- **[MEDIUM]** Pulsarite: the probe surveys each stop for 5 years, riding along with the moving star, before it leaves.
- **[MEDIUM]** New baseline: the greedy route flown at the fastest single speed that fits the fuel.
- **[MEDIUM]** Speed tuning in both miners (phone and `miner.py`): they shift fuel between legs and take turns with the route-order polish.
- **[MINOR]** Fuel used and rocket-equation mass ratio in `/routes`, `/mining/route`, the RIG summary line and the PC miner's output.
- **[MINOR]** MAP tab: each star shows its leg's speed and fuel, and the probe shows the tank used. The probe also waits at stars while it surveys them.
- **[MINOR]** The app's version now follows this changelog (6.0.0).

## 5.4.3 and earlier

Everything up to the previous recorded release, v5.4.3, summarised by size. Your own release records have the exact version for each item.

### Username claims and probe acceleration

- **[MAJOR]** Pulsarite: the probe accelerates from rest and brakes (0 to 10% of c in 10 years). Four survey stops per block, where the probe must come to rest. If it can't stop in time, it overshoots and comes back. *Consensus change: new chain (genesis v3).*
- **[MEDIUM]** Usernames can be claimed without mining: a free signed name transaction with a small proof of work against spam. Both coins support it.
- **[MEDIUM]** App: a username status line and a [CLAIM NOW] / [SWITCH] button on the RIG tab.
- **[MINOR]** `wallet.py claim NAME`. `/info` reports `name_pow_bits`.
- **[MINOR]** MAP tab: survey stops are marked ◆, and stars show the probe's speed as it passes.

### Setup, usernames, sending and moving stars

- **[MAJOR]** Send coins from the app: wallet signing on the phone (secp256k1, RFC 6979), to an address or a username.
- **[MEDIUM]** First-run setup: username, a wallet with a backup check, and a choice of where to mine.
- **[MEDIUM]** On-chain usernames: claimed in the coinbase of a mined block, unique per network, kept with your key.
- **[MEDIUM]** MAP tab: tap a star or planet for details, and a time slider to fly missions and watch stars move.
- **[MAJOR]** Pulsarite: moving stars (proper motion and radial velocity) and probe travel time at 10% of c. Routes are scored by mission time. *Consensus change.*

### Mine anywhere

- **[MAJOR]** Solo mode: both blockchains run inside the app. Chains mined on the phone can be pushed to a node (`/chain/import`).
- **[MEDIUM]** Start scripts for Windows, Mac and Linux to run a node on your computer. [FIND NODE] scans your Wi-Fi for it.
- **[MEDIUM]** Cloud deployment: Docker, Caddy (HTTPS) and DEPLOY.md.
- **[MINOR]** In-app wallet compatible with `wallet.py` (new, backup, import).

### Fixes

- **[MINOR]** Map download failing on the placeholder node address. Friendlier connection errors.
- **[MINOR]** Grey title bar removed.
- **[MINOR]** Clear mining feedback: alerts under ENGAGE, a setup guide and an explanation when mining is paused.

### Real planet motion and the 3D map

- **[MAJOR]** Nebulite: real planet motion from JPL orbital elements, in 3D, with a 3D Lambert solver. Checked against real oppositions and the Voyager flybys. *Consensus change.*
- **[MAJOR]** MAP tab: an interactive 3D star map and orbit map, with mined routes and your rig's live work.

### Useful work

- **[MAJOR]** Pulsarite proof of useful work: routes through stars picked from each block's hash. Faster routes make blocks easier to find.
- **[MAJOR]** Nebulite: a second, separate coin whose proof of work is interplanetary spacecraft trajectories (Lambert transfers, gravity-assist flybys).
- **[MEDIUM]** Route optimisers on the phone, cross-checked against the nodes.

### Neon Pulsar

- **[MAJOR]** Multi-coin mining: Bitcoin and other SHA-256 coins through Stratum pools.
- **[MEDIUM]** LEDGER tab: tracks what you mined, how much, and when.
- **[MEDIUM]** "Neon Pulsar" theme (stellar space / cyberpunk corporate, crimson accents).
- **[MINOR]** Renamed to Stellarite Miner, and the coin to Pulsarite (PLSR).

### First release

- **[MAJOR]** Pulsarite, a learning cryptocurrency built from scratch: an account ledger, SHA-256d proof of work, difficulty retargeting and peer sync.
- **[MAJOR]** Android miner app with a foreground mining service.
- **[MEDIUM]** GitHub Actions workflow: tests both nodes and builds the APK.
