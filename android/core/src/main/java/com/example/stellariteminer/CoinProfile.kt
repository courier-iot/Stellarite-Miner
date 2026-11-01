package com.example.stellariteminer

/** How the app reaches the network for a coin. */
enum class Protocol { NODE, STRATUM }

/** What mining a coin involves on top of hashing. */
enum class WorkKind { STAR_ROUTES, TRAJECTORIES, NONE }

/**
 * A coin the app can mine. Every coin here uses SHA-256d hashing (Pulsarite adds
 * star-route useful work on top, Nebulite adds spacecraft trajectories); adding a CPU-friendly algorithm (e.g. RandomX for Monero)
 * would mean adding a new hashing engine.
 */
class CoinProfile(
    val id: String,
    val name: String,
    val ticker: String,
    val protocol: Protocol,
    val urlHint: String,
    val userLabel: String,
    val userHint: String,
    val note: String,
    val kind: WorkKind = WorkKind.NONE,
    val addressPrefix: String = "",     // own coins: required address prefix
    val addressLength: Int = 0,
    val nodeFolder: String = "",        // own coins: folder in the repo that holds node.py
    val defaultPort: Int = 0,
) {
    companion object {
        val ALL = listOf(
            CoinProfile(
                id = "plsr", name = "Pulsarite", ticker = Coin.TICKER, protocol = Protocol.NODE,
                urlHint = "http://<computer-ip>:5000",
                userLabel = "WALLET_ADDR", userHint = "${Coin.ADDRESS_PREFIX}…",
                note = "Mines your own coin through your node. Every block needs a route through 24 nearby " +
                    "stars: the rig keeps shortening it while it hashes, and shorter routes make " +
                    "blocks easier to win. Blocks pay straight to your address.",
                kind = WorkKind.STAR_ROUTES, addressPrefix = Coin.ADDRESS_PREFIX, addressLength = Coin.ADDRESS_LENGTH,
                nodeFolder = "node", defaultPort = 5000,
            ),
            CoinProfile(
                id = "nblt", name = "Nebulite", ticker = NebuliteCoin.TICKER, protocol = Protocol.NODE,
                urlHint = "http://<computer-ip>:5001",
                userLabel = "WALLET_ADDR", userHint = "${NebuliteCoin.ADDRESS_PREFIX}…",
                note = "Mines Nebulite through its own node. Every block needs a spacecraft trajectory " +
                    "from Earth to an outer planet: the rig searches gravity-assist flybys for the " +
                    "least fuel and travel time, and cheaper missions make blocks easier to win.",
                kind = WorkKind.TRAJECTORIES, addressPrefix = NebuliteCoin.ADDRESS_PREFIX,
                addressLength = NebuliteCoin.ADDRESS_LENGTH, nodeFolder = "nebulite", defaultPort = 5001,
            ),
            CoinProfile(
                id = "btc", name = "Bitcoin", ticker = "BTC", protocol = Protocol.STRATUM,
                urlHint = "stratum+tcp://pool.example.com:3333",
                userLabel = "WORKER", userHint = "bc1q…yourAddress.phone",
                note = "Bitcoin is secured by industrial ASIC farms. A phone can earn pool shares " +
                    "but expect effectively zero BTC. Pick a pool that allows very low difficulty.",
            ),
            CoinProfile(
                id = "bch", name = "Bitcoin Cash", ticker = "BCH", protocol = Protocol.STRATUM,
                urlHint = "stratum+tcp://pool.example.com:3333",
                userLabel = "WORKER", userHint = "bitcoincash:q…yourAddress.phone",
                note = "Same SHA-256d algorithm as Bitcoin, so the same expectations apply.",
            ),
            CoinProfile(
                id = "custom", name = "Custom SHA-256d", ticker = "SHA", protocol = Protocol.STRATUM,
                urlHint = "stratum+tcp://host:port",
                userLabel = "WORKER", userHint = "username.worker",
                note = "Any Stratum v1 pool for a SHA-256d coin. Password field is passed to the pool as-is.",
            ),
        )

        fun byId(id: String) = ALL.firstOrNull { it.id == id } ?: ALL[0]
    }
}
