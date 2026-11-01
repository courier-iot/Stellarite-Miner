# Roadmap: from prototype to useful science

Both coins already turn mining into checkable space problems. This list is what it takes to make their output genuinely useful. Items are in priority order within each coin; **bold** items are the ones that matter most for a working prototype.

Every change to how blocks are scored is a consensus change: all nodes must upgrade together, and it starts a new chain (delete each node's `data/` folder).

## Pulsarite: star routes

Today: straight-line routes from the Sun through 24 stars at fixed positions, scored by total distance.

- [ ] **Star movement.** Stars drift across the sky (proper motion) and toward or away from us (radial velocity); over a century-long trip Barnard's Star moves about 0.05 light-years. Add `pmra`, `pmdec` and `rv` to each catalog star and compute positions at the moment the probe arrives, not today.
  - [ ] Extend `tools/build_catalog.py` to read proper motion and radial velocity from HYG (`pmra`, `pmdec`, `rv`) or Gaia DR3.
  - [ ] Store motion as integer milli-light-years per millennium, so consensus stays exact.
  - [ ] Compute each star's position at its arrival time (needs the travel-time item below).
- [ ] **Travel time.** Give the probe a cruise speed (start with 0.1c as a configurable network parameter) and score routes by total mission time, not just distance. With moving stars, each leg becomes an intercept problem: aim where the star will be.
  - [ ] Add `PROBE_SPEED_C` to `config.py`; compute arrival times leg by leg.
  - [ ] Iterate each leg's intercept point a fixed number of times, deterministic and integer-based.
  - [ ] Show mission duration in years on the HUD, the ledger and `/routes`.
- [ ] **Real star catalog by default.** Ship a Gaia/HYG-derived catalog of every star within 50 ly (about 1,500 stars, many of them faint red dwarfs) and record its fingerprint in the genesis block, so nodes can't disagree about it.
- [ ] **Scale problems with the catalog.** Raise `STARS_PER_PROBLEM` from 24 to 40–60 so optimisation stays hard as phones get better at it.
- [ ] **Science-weighted targets.** Favour stars with known exoplanets or habitable-zone planets (from the NASA Exoplanet Archive), so routes prioritise worthwhile destinations. Score science value per year of travel.
- [ ] **Stop vs flyby.** Let a route mark stars as flybys (pass through) or stops (decelerate). Stopping costs time, and fuel once fuel is modelled.
- [ ] **Best-known route archive.** Keep the best route ever found for each star set, so the map improves over time instead of only growing.
- [x] **3D route map in the app** (MAP tab).
- [ ] **3D route map on the web.** A page served by the node that draws recent routes among the stars.

## Nebulite: spacecraft trajectories

Today: planets on circular, flat orbits; Lambert transfers between planets; patched-conic flybys; cost = fuel (km/s) + 250 m/s per year of travel.

- [x] **Real planet motion (ephemerides).** Planets follow JPL's approximate Keplerian elements and their rates (elliptical, inclined orbits, valid 1800–2050), in 3D with a 3D Lambert solver.
  - [x] Checked against reality: oppositions of Mars through Neptune land within a day of the real dates, Mars' 2003 close approach matches to 0.0003 AU, and Voyager 1 and 2 flown on their real dates need almost no flyby fuel.
  - [ ] Missions arriving after 2050 (some Uranus and Neptune missions) use the elements beyond their fitted range; switch to JPL's long-span table (3000 BC–3000 AD) or a full ephemeris.
  - [ ] Regression tests for Cassini (V-V-E-J-S) and Juno (E-E-J), once multi-revolution legs and deep-space manoeuvres exist.
- [ ] **Travel time as a mission parameter.** Travel time is already scored, as a fixed 250 m/s per year. Make the trade-off part of each mission instead (crewed missions value speed, robotic ones value fuel) and report launch and arrival dates in plain calendar terms.
  - [ ] Per-mission `time_penalty` and `max_tof` chosen from the block hash, across a range of mission types.
  - [ ] Show arrival dates on the HUD and in `/missions`.
- [ ] **More varied missions.** Blocks whose launch windows overlap often share the same best trajectory, so known solutions can be reused. Vary more per block (destinations including asteroids and moons, arrival-date limits, time penalties) so each block is a genuinely new problem.
- [ ] **Multi-revolution transfers and deep-space manoeuvres.** Allow legs that loop around the Sun more than once, plus engine burns mid-leg. Real missions need these: Cassini's two Venus flybys use a resonant loop.
- [ ] **Arrival into orbit.** Score the burn needed to enter a capture orbit at the target (a periapsis height and eccentricity), not just the arrival speed.
- [ ] **Realistic flyby limits.** Use per-planet minimum altitudes, larger safety margins at Jupiter for radiation, and avoid flying through atmospheres.
- [ ] **Launch vehicle and mass.** Convert Δv into propellant mass with the rocket equation, add launcher limits on departure energy (C3) and declination, and score payload delivered.
- [ ] **Space-survival missions.** Add mission types beyond the outer planets: crewed Mars round trips (abort and return windows), asteroid and comet rendezvous (resources, planetary defence), and Moon–Mars logistics.
- [ ] **Deterministic maths for consensus.** Costs are currently checked within 1 m/s, so tiny floating-point differences between computers can't split the chain. Before running a public network, switch to a portable, correctly rounded maths library (or fixed-point arithmetic) so every node computes the identical number.

## Both coins

- [ ] **Send coins from the app.** The app wallet can receive and mine; add ECDSA signing (secp256k1, as wallet.py does) so it can send transactions to a node too.
- [ ] **Merge solo chains.** Today a pushed solo chain wins only if it has more work than the node's. Pools of solo miners, or reorganising onto the node's chain while keeping your coins, would avoid losing solo blocks.

- [ ] **Independent expert review.** Have an astrodynamicist check the physics against established tools (NASA's GMAT, ESA's pykep) before claiming results are mission-grade.
- [ ] **Open science data.** Publish the route map and mission log as downloadable CSV/JSON under an open license (CC BY 4.0), with a stable public API.
- [ ] **Pool for useful work.** Let phones share block rewards by submitting partial solutions (good routes or trajectories plus low-difficulty hashes), so a phone earns steadily instead of rarely.
- [ ] **Faster sync and light clients.** Add Merkle trees for transactions, header-first sync, and compact proofs.
- [ ] **Network security.** HTTPS between nodes, peer limits and rate limiting, signed app releases with a real keystore.
- [x] **3D map tab.** Star map with mined routes (Pulsarite) and real-orbit mission map (Nebulite), with the rig's live work highlighted.
  - [ ] Tap a star or planet for details; time slider to watch a mission fly; show star motion once Pulsarite models it.

## Done

- [x] Pulsarite: star-route proof of work, exact integer distances, catalog builder, route map (`/routes`)
- [x] Nebulite: separate coin with trajectory proof of work, Lambert solver checked against numerical integration, gravity-assist flybys, travel-time penalty, mission log (`/missions`)
- [x] Phone optimisers for both coins, cross-checked against the nodes' physics
- [x] Multi-coin app with a mining ledger
- [x] Nebulite: real 3D planet motion from JPL elements, validated against oppositions and the Voyager missions
- [x] MAP tab: interactive 3D star map and orbit map
- [x] Solo mode: both blockchains run inside the app; phone-mined chains are accepted by the Python nodes and can be pushed with `/chain/import`
- [x] In-app wallet compatible with wallet.py; start scripts for Windows/Mac/Linux; Docker + Caddy cloud deployment
