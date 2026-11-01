"""Generates the app's solo-mode consensus data from the Python nodes.

Solo mode runs the blockchain inside the app, so it must use exactly the same
constants, star catalog and planet data as the nodes. Run this after changing
node/config.py, node/stars.py, nebulite/config.py or nebulite/trajectory.py:

  python tools/gen_solo_data.py

It rewrites android/app/src/main/java/com/example/stellariteminer/SoloData.kt.
"""
import importlib
import json
import math
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "android/app/src/main/java/com/example/stellariteminer/SoloData.kt")


def load(folder, *mods):
    for m in ("config", "stars", "trajectory", "crypto_utils"):
        sys.modules.pop(m, None)
    os.environ.pop("PULSARITE_DIFFICULTY_BITS", None)
    os.environ.pop("NEBULITE_DIFFICULTY_BITS", None)
    os.environ.pop("PULSARITE_STARS", None)
    sys.path.insert(0, os.path.join(ROOT, folder))
    try:
        return [importlib.import_module(m) for m in mods]
    finally:
        sys.path.pop(0)


def kstr(s):
    return json.dumps(s)          # a valid Kotlin string literal for ASCII text


def consts(C, extra):
    return f"""        coinName = {kstr(C.COIN_NAME)},
        ticker = {kstr(C.TICKER)},
        addressPrefix = {kstr(C.ADDRESS_PREFIX)},
        unitsPerCoin = {C.UNITS_PER_COIN}L,
        blockReward = {C.BLOCK_REWARD}L,
        halvingInterval = {C.HALVING_INTERVAL},
        targetBlockSeconds = {C.TARGET_BLOCK_SECONDS},
        retargetInterval = {C.RETARGET_INTERVAL},
        maxRetargetFactor = {C.MAX_RETARGET_FACTOR},
        genesisDifficultyBits = {C.GENESIS_DIFFICULTY_BITS},
        genesisTimestamp = {C.GENESIS_TIMESTAMP}L,
        genesisMessage = {kstr(C.GENESIS_MESSAGE)},
        bonusExponent = {extra},"""


OBLIQUITY_J2000_DEG = 84381.406 / 3600            # IAU 2006 mean obliquity of the ecliptic at J2000


def write_star_targets(PC, stars):
    """nebulite/star_targets.json: each Pulsarite star's direction from the Sun in Nebulite's
    frame (ecliptic J2000), where the star will be when Pulsarite's probe launches."""
    eps = math.radians(OBLIQUITY_J2000_DEG)
    out = []
    for s in stars.CATALOG:
        x, y, z = stars.pos(s["id"], stars.LAUNCH_T)        # equatorial, milli-light-years
        ye, ze = math.cos(eps) * y + math.sin(eps) * z, -math.sin(eps) * y + math.cos(eps) * z
        r = math.sqrt(x * x + ye * ye + ze * ze)
        out.append({"id": s["id"], "name": s["name"], "planets": s["planets"], "distance_ly": round(r / 1000, 3),
                    "dir": [round(x / r, 12), round(ye / r, 12), round(ze / r, 12)]})
    data = {"source": "Pulsarite star catalog (node/stars.py)", "catalog_id": stars.CATALOG_ID,
            "frame": "ecliptic J2000, unit vectors", "launch_year": PC.LAUNCH_YEAR, "stars": out}
    path = os.path.join(ROOT, "nebulite/star_targets.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")
    print("wrote", os.path.relpath(path, ROOT))


def main():
    PC, stars = load("node", "config", "stars")
    if stars.CATALOG_SOURCE != "built-in":
        print("note: solo mode uses the node's current catalog:", stars.CATALOG_SOURCE)
    names = ",\n        ".join(kstr(s["name"]) for s in stars.CATALOG)
    xs = ", ".join(str(s["x"]) for s in stars.CATALOG)
    ys = ", ".join(str(s["y"]) for s in stars.CATALOG)
    zs = ", ".join(str(s["z"]) for s in stars.CATALOG)
    vxs = ", ".join(str(s["vx"]) for s in stars.CATALOG)
    vys = ", ".join(str(s["vy"]) for s in stars.CATALOG)
    vzs = ", ".join(str(s["vz"]) for s in stars.CATALOG)
    planets = ", ".join(str(s["planets"]) for s in stars.CATALOG)
    pul = consts(PC, PC.ROUTE_BONUS_EXPONENT)

    write_star_targets(PC, stars)                 # trajectory.py reads this file when it loads
    NC, T = load("nebulite", "config", "trajectory")
    neb = consts(NC, NC.TRAJECTORY_BONUS_EXPONENT) + (
        f"\n        bonusCapNum = {NC.BONUS_RATIO_CAP_NUM}L,\n        bonusCapDen = {NC.BONUS_RATIO_CAP_DEN}L,")
    model_json = json.dumps({"planets": T.planets_json(), "physics": T.physics_json()}, sort_keys=True)
    mission = json.dumps({
        "targets": T.TARGETS, "max_tof_years": {str(k): v for k, v in T.MAX_TOF_YEARS.items()},
        "max_flybys": T.MAX_FLYBYS, "window_days": T.WINDOW_DAYS,
        "window_start_min": T.WINDOW_START_MIN, "window_start_spread": T.WINDOW_START_SPREAD,
        "mission_types": T.MISSION_TYPES, "mission_draw": T.MISSION_DRAW,
        "escape": {"odds": T.ESCAPE_ODDS, "goal_au": T.ESCAPE_GOAL_AU,
                   "launch_vinf_max_kms": T.ESCAPE_LAUNCH_VINF_MAX, "burn_budget_kms": T.ESCAPE_BURN_BUDGET,
                   "min_perihelion_au": T.ESCAPE_MIN_PERIHELION_AU, "max_cruise_days": T.ESCAPE_MAX_CRUISE_DAYS,
                   "flyby_bodies": T.ESCAPE_FLYBY_BODIES, "star_weight_per_planet": T.STAR_WEIGHT_PER_PLANET},
        "star_targets": [{k: st[k] for k in ("id", "name", "planets", "distance_ly", "dir")}
                         for st in T.STAR_TARGETS["stars"]],
        "star_catalog_id": T.STAR_TARGETS["catalog_id"],
    }, sort_keys=True)

    src = f'''package com.example.stellariteminer

// GENERATED by tools/gen_solo_data.py from the Python nodes. Do not edit by hand:
// solo mode must match the nodes' consensus rules exactly.

object SoloData {{
    val PULSARITE = CoinRules(
{pul}
    )

    val NEBULITE = CoinRules(
{neb}
    )

    /** Pulsarite's star catalog ({stars.CATALOG_SOURCE}, id {stars.CATALOG_ID}): positions in milli-light-years. */
    const val STARS_PER_PROBLEM = {stars.STARS_PER_PROBLEM}
    val STAR_NAMES = arrayOf(
        {names},
    )
    val STAR_X = longArrayOf({xs})
    val STAR_Y = longArrayOf({ys})
    val STAR_Z = longArrayOf({zs})
    /** Star velocities in mly per 1000 years. */
    val STAR_VX = longArrayOf({vxs})
    val STAR_VY = longArrayOf({vys})
    val STAR_VZ = longArrayOf({vzs})
    /** Confirmed planets in each system (longer surveys, likelier survey stops). */
    val STAR_PLANETS = intArrayOf({planets})
    /** The probe: speed (mly per year), launch time (milli-years after J2000), intercept iterations. */
    const val PROBE_SPEED = {stars.SPEED}L
    /** Probe acceleration (mly/yr²) and survey stops per block. */
    const val PROBE_ACCEL = {PC.PROBE_ACCEL_MLY_PER_YEAR2}L
    const val SURVEY_STOPS = {stars.SURVEY_STOPS}
    /** Years spent at each survey stop; fuel budget and exhaust speed in % of light speed. */
    const val SURVEY_YEARS = {PC.SURVEY_YEARS}L
    const val SURVEY_YEARS_PER_PLANET = {PC.SURVEY_YEARS_PER_PLANET}L
    const val STOP_WEIGHT_PER_PLANET = {PC.STOP_WEIGHT_PER_PLANET}
    const val DV_BUDGET_PCT_C = {PC.DV_BUDGET_PCT_C}L
    const val EXHAUST_PCT_C = {PC.EXHAUST_PCT_C}L
    const val LAUNCH_T = {stars.LAUNCH_T}L
    const val INTERCEPT_ITERATIONS = {stars.INTERCEPT_ITERATIONS}

    /** Nebulite planet orbits and physics (same JSON the node serves at /planets). */
    const val NEBULITE_MODEL_JSON = {kstr(model_json)}
    const val NEBULITE_MISSION_RULES_JSON = {kstr(mission)}
}}
'''
    with open(OUT, "w") as f:
        f.write(src)
    print("wrote", os.path.relpath(OUT, ROOT))
    # The app reads the same planetary theory the node uses (Vsop87.kt loads it as a resource).
    res = os.path.join(ROOT, "android/app/src/main/resources/vsop87a.txt")
    os.makedirs(os.path.dirname(res), exist_ok=True)
    shutil.copyfile(T.VSOP87_FILE, res)
    print("wrote", os.path.relpath(res, ROOT))


if __name__ == "__main__":
    main()
