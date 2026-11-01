# Accuracy of Nebulite's planet positions and paths

Nebulite's useful work is planning spacecraft trajectories, so the planets have to be where they really are on the dates a mission uses: launches from 2025, arrivals as late as the 2060s and beyond. This page explains which model the network uses, how it was checked, and how much error is left.

## The model: full VSOP87A

Since 8.0.0, both the node and the app compute planet positions with **VSOP87A**: the planetary theory of Bretagnon and Francou (Bureau des Longitudes, 1988). It is a long sum of periodic terms fitted to JPL's numerical ephemeris, and it is widely used where arcsecond accuracy is needed.

- **Full series, nothing cut.** All 39,198 terms for Mercury to Neptune are used. Truncating the series was measured and rejected: even the smallest cut tried (dropping terms below 1e-10 AU) adds up to 0.5 km of error, so none is dropped.
- **Earth itself, not the Earth-Moon barycentre.** That removes an error of up to 4,700 km at launch and at Earth flybys.
- **Exact velocities.** The planets' velocities, which set flyby and arrival speeds, are the series' exact time derivatives, not finite differences.
- **Valid for millennia.** The published accuracy is about 1 arcsecond: over ±2,000 years from 2000 for Mercury to Mars, ±1,000 years for Jupiter and Saturn, and ±3,000 years for Uranus and Neptune. Every mission window this coin uses, including all arrivals after 2050, is well inside that.
- **JPL DE440 masses.** The Sun's and planets' gravitational constants (GM), which shape every transfer and flyby, are JPL DE440 values. The astronomical unit is the IAU 2012 value.

The coefficients live in `nebulite/vsop87a.txt`. The app bundles an identical copy, and both sides report its fingerprint (`ephemeris_id`) so a mismatch is caught.

## How it was checked

**1. Against the authors' official test values.** `vsop87.chk` gives positions and velocities for every planet at 10 dates between 4000 BC and AD 2000. The node and the app reproduce all 80 planet cases to the file's 10 printed decimals (a few metres). Six of them are in the test suite.

**2. Against real events.**

| Event (published time, UT) | VSOP87A (new) | Old model |
|---|---|---|
| Mars opposition, 2018-07-27 05:07 | 0.00 h off | within 2 days |
| Mars opposition, 2022-12-08 05:41 | 0.09 h off | within 2 days |
| Jupiter opposition, 2023-11-03 05:03 | 0.18 h off | within 2 days |
| Saturn opposition, 2023-08-27 08:28 | 0.20 h off | within 2 days |
| Mars closest approach, 2003-08-27 09:51, 0.372719 AU | 0.372719 AU, about 1 minute off | 0.3727 ± 0.002 AU |

The few minutes left at the oppositions come from the published times using the equinox of date and light-time, which this comparison ignores.

**3. Against an independent N-body integration, to 2150.** The solar system was integrated with Newtonian gravity for the Sun and the eight planets, plus general relativity for the Sun. The integrator was DOP853 with a tolerance of 1e-13, starting from VSOP87A's own positions and velocities on 1 January 2025. The table shows the largest gap (km) from VSOP87A in each period, next to the old model's gap from VSOP87A:

| Planet | N-body vs VSOP87A: 2025–2050 | 2050–2100 | 2100–2150 | Old model: 2025–2050 | 2050–2100 | 2100–2150 |
|---|---:|---:|---:|---:|---:|---:|
| Mercury | 153 | 438 | 712 | 2,492 | 5,712 | 4,851 |
| Venus | 1,472 | 4,435 | 7,442 | 12,231 | 12,839 | 11,460 |
| Earth | 1,006 | 3,021 | 5,035 | 5,911 | 9,100 | 14,276 |
| Mars | 1,719 | 5,627 | 9,533 | 69,490 | 69,490 | 86,000 |
| Jupiter | 10,969 | 34,402 | 56,924 | 1,126,457 | 1,391,042 | 2,060,089 |
| Saturn | 8,827 | 11,872 | 13,530 | 3,348,836 | 7,565,735 | 10,317,158 |
| Uranus | 17,179 | 47,480 | 48,877 | 1,591,429 | 2,849,968 | 9,360,070 |
| Neptune | 26,580 | 163,966 | 241,540 | 1,278,214 | 2,023,079 | 3,156,282 |

The N-body column is an upper bound, not VSOP87A's own error. The integration leaves out the asteroids and Pluto, treats the Earth-Moon system as one point, and starts from VSOP87A's own velocities, whose small errors grow steadily with time. Even so, the two independent methods agree to within a few thousand km for the inner planets through 2150. They also agree far more closely than the old model did, by a factor of 10 to 700 for Mars and the giant planets.

**The old model** (JPL's approximate Keplerian elements, fitted for 1800–2050) was already **1 to 3 million km off for the giant planets in 2025**, and Saturn drifts to 10 million km by 2150. That is 20 to 150 times Jupiter's radius. A spacecraft aimed using those positions would miss the planet completely.

**4. App against node.** On 400 random planet states between 1000 BC and AD 2150, the app and the node agree to 0.3 mm in position. On 25 optimised missions, mission costs agree to 0.0000000002 m/s, and so do the per-block baselines. Consensus allows 1 m/s, so floating-point differences between phones and computers can't split the network.

## What the old errors did to scores

Scoring the same optimised trajectories with the old and the new model changes mission costs by only 3 to 21 m/s. The model mainly fixes the geometry, not the scores: under the old model, flyby and arrival points could be millions of km from the real planet.

## Error budget today

| Source | Size | Notes |
|---|---|---|
| Planet positions (theory) | about 1″: roughly 700 km at Earth, 4,000 km at Jupiter, 7,000 km at Saturn, 14,000 km at Uranus, 22,000 km at Neptune, at most | VSOP87A's published accuracy against JPL |
| Series truncation | 0 | full series |
| Phone vs node arithmetic | below 1 mm, below 1e-9 m/s | measured |
| Lambert legs | below 1e-6 of the flight time | checked by the solver; legs that miss are rejected |
| **Trajectory model (patched conics)** | **largest remaining error** | the planets' gravity is ignored during cruise and flybys are treated as instantaneous; flybys must stay outside 1.1 planet radii |

The next step for even lower error is refining each mined path with an N-body integration: planetary gravity throughout the flight, with each flyby solved as a real hyperbolic encounter. That turns a patched-conic sketch into a trajectory accurate enough to fly. It's listed in ROADMAP.md.

## Escape missions (9.0.0)

Escape missions add hyperbolic departures, Sun dives and timing to 550 AU. Each piece is checked in the test suite:

- **Aim:** recovering the asymptote from the computed departure state gives the target star's direction to within 1e-9 radians, and the orbital energy gives the requested escape speed to within 1e-12.
- **Sun dives:** the infall orbit's perihelion equals the requested distance (0.05 AU) to within 1e-10 AU, and the burn is purely along the direction of motion.
- **Timing:** the analytic time to 550 AU agrees with a step-by-step numerical integration of the same orbit to within one integration step (under a day in about a century).
- **Phone vs node:** across 140 blocks they agree on which blocks are escape missions and on every target star and baseline plan (to 3e-11 days). On 115 test plans they agree on feasibility, with costs equal to 4e-11 days.
- **Physics check against a real study:** with realistic launch and fuel limits the model finds that Sun dives rarely beat Jupiter flybys. That matches the Interstellar Probe study's conclusion about the solar Oberth manoeuvre.

The remaining approximation is the same as for planet missions: patched conics. The planets' pull after the last flyby is ignored, and so is the slow outward drift of the Sun's own position around the solar system's centre of mass.

## References

- P. Bretagnon and G. Francou, *Planetary theories in rectangular and spherical variables: VSOP87 solutions*, Astronomy and Astrophysics 202, 309–315 (1988).
- VSOP87 coefficients: transcription in [gmiller123456/vsop87-multilang](https://github.com/gmiller123456/vsop87-multilang) (public domain), verified against the authors' `vsop87.chk`.
- R. S. Park et al., *The JPL Planetary and Lunar Ephemerides DE440 and DE441*, The Astronomical Journal 161:105 (2021), for the masses (GM).
- E. M. Standish, *Keplerian Elements for Approximate Positions of the Major Planets* (JPL), the old model.
