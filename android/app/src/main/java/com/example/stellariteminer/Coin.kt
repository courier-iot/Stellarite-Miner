package com.example.stellariteminer

/** Pulsarite constants. Must match node/config.py if you rename the coin. */
object Coin {
    const val TICKER = "PLSR"
    const val ADDRESS_PREFIX = "plsr"
    const val ADDRESS_LENGTH = ADDRESS_PREFIX.length + 48  // prefix + 48 hex characters
}

/** Nebulite constants. Must match nebulite/config.py if you rename the coin. */
object NebuliteCoin {
    const val TICKER = "NBLT"
    const val ADDRESS_PREFIX = "nblt"
    const val ADDRESS_LENGTH = ADDRESS_PREFIX.length + 48
}
