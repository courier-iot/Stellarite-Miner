# Changelog

Every feature is tagged by size, for the version records:

- **[MAJOR]** a new capability, or a change to the blockchain rules (a consensus change that starts a new chain)
- **[MEDIUM]** a notable addition or improvement to something that already exists
- **[MINOR]** a small tweak, a fix or polish

Version numbers follow the same idea: a release with a major feature bumps the middle number (0.7 → 0.8), a release with only medium or minor changes bumps the last one (0.8.0 → 0.8.1). The app's `versionName` in `android/app/build.gradle.kts` matches the latest entry here. Tag a release `v0.8.0` on GitHub and the workflow attaches the APK.

Versions before 0.8.0 were recorded after the fact, grouping the work in the order it was built.

## 0.8.0: Fuel and survey time

- **[MAJOR]** Pulsarite: each leg of a route now has its own cruise speed, from 1% to 10% of light speed. Routes are sent as `[[star id, speed], …]` pairs. *Consensus change: new chain (genesis v4).*
- **[MAJOR]** Pulsarite: fuel budget. The probe's total speed change over a mission must fit within 50% of light speed, so routes have to spend speed where it saves the most time. Routes that need more fuel are rejected.
- **[MEDIUM]** Pulsarite: the probe surveys each stop for 5 years, riding along with the moving star, before it leaves.
- **[MEDIUM]** New baseline: the greedy route flown at the fastest single speed that fits the fuel.
- **[MEDIUM]** Speed tuning in both miners (phone and `miner.py`): they shift fuel between legs and take turns with the route-order polish.
- **[MINOR]** Fuel used and rocket-equation mass ratio in `/routes`, `/mining/route`, the RIG summary line and the PC miner's output.
- **[MINOR]** MAP tab: each star shows its leg's speed and fuel, and the probe shows the tank used. The probe also waits at stars while it surveys them.
- **[MINOR]** App version numbering starts following this changelog (0.8.0).

## 0.7.0: Username claims and probe acceleration

- **[MAJOR]** Pulsarite: the probe accelerates from rest and brakes (0 to 10% of c in 10 years). Four survey stops per block, where the probe must come to rest. If it can't stop in time, it overshoots and comes back. *Consensus change: new chain (genesis v3).*
- **[MEDIUM]** Usernames can be claimed without mining: a free signed name transaction with a small proof of work against spam. Both coins support it.
- **[MEDIUM]** App: a username status line and a [CLAIM NOW] / [SWITCH] button on the RIG tab.
- **[MINOR]** `wallet.py claim NAME`. `/info` reports `name_pow_bits`.
- **[MINOR]** MAP tab: survey stops are marked ◆, and stars show the probe's speed as it passes.

## 0.6.0: Setup, usernames, sending and moving stars

- **[MAJOR]** Send coins from the app: wallet signing on the phone (secp256k1, RFC 6979), to an address or a username.
- **[MEDIUM]** First-run setup: username, a wallet with a backup check, and a choice of where to mine.
- **[MEDIUM]** On-chain usernames: claimed in the coinbase of a mined block, unique per network, kept with your key.
- **[MEDIUM]** MAP tab: tap a star or planet for details, and a time slider to fly missions and watch stars move.
- **[MAJOR]** Pulsarite: moving stars (proper motion and radial velocity) and probe travel time at 10% of c. Routes are scored by mission time. *Consensus change.*

## 0.5.0: Mine anywhere

- **[MAJOR]** Solo mode: both blockchains run inside the app. Chains mined on the phone can be pushed to a node (`/chain/import`).
- **[MEDIUM]** Start scripts for Windows, Mac and Linux to run a node on your computer. [FIND NODE] scans your Wi-Fi for it.
- **[MEDIUM]** Cloud deployment: Docker, Caddy (HTTPS) and DEPLOY.md.
- **[MINOR]** In-app wallet compatible with `wallet.py` (new, backup, import).

## 0.4.1: Fixes

- **[MINOR]** Map download failing on the placeholder node address. Friendlier connection errors.
- **[MINOR]** Grey title bar removed.
- **[MINOR]** Clear mining feedback: alerts under ENGAGE, a setup guide and an explanation when mining is paused.

## 0.4.0: Real planet motion and the 3D map

- **[MAJOR]** Nebulite: real planet motion from JPL orbital elements, in 3D, with a 3D Lambert solver. Checked against real oppositions and the Voyager flybys. *Consensus change.*
- **[MAJOR]** MAP tab: an interactive 3D star map and orbit map, with mined routes and your rig's live work.

## 0.3.0: Useful work

- **[MAJOR]** Pulsarite proof of useful work: routes through stars picked from each block's hash. Faster routes make blocks easier to find.
- **[MAJOR]** Nebulite: a second, separate coin whose proof of work is interplanetary spacecraft trajectories (Lambert transfers, gravity-assist flybys).
- **[MEDIUM]** Route optimisers on the phone, cross-checked against the nodes.

## 0.2.0: Neon Pulsar

- **[MAJOR]** Multi-coin mining: Bitcoin and other SHA-256 coins through Stratum pools.
- **[MEDIUM]** LEDGER tab: tracks what you mined, how much, and when.
- **[MEDIUM]** "Neon Pulsar" theme (stellar space / cyberpunk corporate, crimson accents).
- **[MINOR]** Renamed to Stellarite Miner, and the coin to Pulsarite (PLSR).

## 0.1.0: First release

- **[MAJOR]** Pulsarite, a learning cryptocurrency built from scratch: an account ledger, SHA-256d proof of work, difficulty retargeting and peer sync.
- **[MAJOR]** Android miner app with a foreground mining service.
- **[MEDIUM]** GitHub Actions workflow: tests both nodes and builds the APK.
