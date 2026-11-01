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

# The probe: launched from the Sun in LAUNCH_YEAR, cruising at a constant speed
# (100 milli-light-years per year = 10% of light speed), flying past each star.
# Stars move while it travels, so routes are scored by mission time.
PROBE_SPEED_MLY_PER_YEAR = 100
LAUNCH_YEAR = 2100

GENESIS_TIMESTAMP = 1_790_812_800  # 2026-10-01 00:00 UTC
GENESIS_MESSAGE = "Pulsarite genesis v2 - moving stars, real travel times"
