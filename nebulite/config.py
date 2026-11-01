"""Nebulite network parameters. A separate coin from Pulsarite: its own chain, addresses and node.

Every node on a network must use identical values, or they will reject
each other's blocks.
"""
import os

COIN_NAME = "Nebulite"
TICKER = "NBLT"
ADDRESS_PREFIX = "nblt"          # addresses look like nblt1a2b3...

UNITS_PER_COIN = 100_000_000     # like satoshis: amounts are stored as integers
BLOCK_REWARD = 50 * UNITS_PER_COIN
HALVING_INTERVAL = 100_000       # reward halves every N blocks
MIN_FEE = 1_000                  # smallest fee a node accepts (0.00001 NBLT)
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
GENESIS_DIFFICULTY_BITS = int(os.environ.get("NEBULITE_DIFFICULTY_BITS", "20"))
MAX_TARGET = (1 << 256) - 1
GENESIS_TARGET = MAX_TARGET >> GENESIS_DIFFICULTY_BITS

# Trajectory proof of work: each block carries a spacecraft trajectory for a
# mission chosen from the previous block's hash. A trajectory R times cheaper
# than the direct-transfer baseline makes the block's hash target
# R^TRAJECTORY_BONUS_EXPONENT times easier to hit. See trajectory.py.
TRAJECTORY_BONUS_EXPONENT = 12
# Nodes recompute costs with floating point; claimed costs may differ from a
# node's own result by at most this much (m/s) so tiny rounding differences
# between computers can't split the network.
COST_TOLERANCE_MPS = 1

GENESIS_TIMESTAMP = 1_790_812_800  # 2026-10-01 00:00 UTC
GENESIS_MESSAGE = "Nebulite genesis - planning paths between the planets"
