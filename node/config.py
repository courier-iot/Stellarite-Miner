"""Network parameters. Change these to make the coin your own.

Every node on a network must use identical values, or they will reject
each other's blocks.
"""
import os

COIN_NAME = "Pulsarite"
TICKER = "PLSR"
ADDRESS_PREFIX = "plsr"          # addresses look like plsr1a2b3...

UNITS_PER_COIN = 100_000_000     # like satoshis: amounts are stored as integers
BLOCK_REWARD = 50 * UNITS_PER_COIN
HALVING_INTERVAL = 100_000       # reward halves every N blocks
MIN_FEE = 1_000                  # smallest fee a node accepts (0.00001 PLSR)
MAX_TXS_PER_BLOCK = 500

# Usernames can be claimed without coins: a name-claim transaction carries a small
# proof of work instead of a fee (sha256d of the claim must have this many leading
# zero bits, ~4 million tries, a few seconds on a phone). Cheap for one name,
# expensive for squatting thousands.
NAME_POW_BITS = int(os.environ.get("NAME_POW_BITS", "22"))

TARGET_BLOCK_SECONDS = 30
RETARGET_INTERVAL = 10           # adjust difficulty every N blocks
MAX_RETARGET_FACTOR = 4          # never move difficulty more than 4x at once

# Starting difficulty: a block needs ~2^GENESIS_DIFFICULTY_BITS hashes on average.
# 20 bits (~1M hashes) suits a handful of phones. Raise it as miners join.
GENESIS_DIFFICULTY_BITS = int(os.environ.get("PULSARITE_DIFFICULTY_BITS", "20"))
MAX_TARGET = (1 << 256) - 1
GENESIS_TARGET = MAX_TARGET >> GENESIS_DIFFICULTY_BITS

# Star-route proof of work: each block carries a route through stars chosen from
# the previous block's hash. A route R times shorter than the greedy baseline
# makes the block's hash target R^ROUTE_BONUS_EXPONENT times easier to hit, so
# better routes win blocks. See stars.py and README "Useful work".
ROUTE_BONUS_EXPONENT = 12

# The probe: launched from rest at the Sun in LAUNCH_YEAR. Each leg of a route
# names a cruise speed, 1-10% of light speed (10% = 100 milli-light-years per
# year). The probe speeds up or slows down at a steady 0.03 g (10 years from 0
# to 10%), flies past most stars at whatever speed it has, and at each block's
# survey stars brakes to a halt and stays SURVEY_YEARS before leaving.
# Every change of speed burns fuel: the probe's total speed change (delta-v) over
# the whole mission must fit within DV_BUDGET_PCT_C, so going fast everywhere is
# impossible and a good route spends its fuel where it saves the most time.
PROBE_SPEED_MLY_PER_YEAR = 100      # top cruise speed (10% of light speed)
PROBE_ACCEL_MLY_PER_YEAR2 = 10      # 0 to 10% of c in 10 years (about 0.03 g)
SURVEY_STOPS = 4                    # stars per block where the probe must stop
SURVEY_YEARS = 5                    # time spent surveying each stop...
SURVEY_YEARS_PER_PLANET = 2         # ...plus this much per known planet in the system
# Survey stops favour stars with known planets: each star's chance of being a
# stop is proportional to 1 + STOP_WEIGHT_PER_PLANET x its planet count.
STOP_WEIGHT_PER_PLANET = 3
DV_BUDGET_PCT_C = 50                # fuel: total delta-v of 50% of light speed
EXHAUST_PCT_C = 10                  # exhaust speed (advanced fusion), for the mass-ratio display
LAUNCH_YEAR = 2100

GENESIS_TIMESTAMP = 1_790_812_800  # 2026-10-01 00:00 UTC
GENESIS_MESSAGE = "Pulsarite genesis v6 - Nebulite scouts guide the routes"

# Scouts: a block may cite Nebulite escape missions aimed at its survey stars (see scouts.py).
# A scouted stop no longer needs a stop: the probe flies past at speed.
SCOUT_MAX_PER_BLOCK = 4
SCOUT_MIN_WORK_DIVISOR = 3          # a scout must carry at least 1/3 of the work the citing block needs
# Scouts can shorten the mission time used for the hash target by at most 2% (51/50), i.e. a target
# at most 1.02^12 = 1.27x easier, which saves at most 21% of a block's hashing. A scout must itself carry
# at least 1/3 (33%) of the hashing the citing block needs, so forging one always costs more than it saves.
SCOUT_TIME_CAP_NUM, SCOUT_TIME_CAP_DEN = 51, 50
