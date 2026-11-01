package com.example.stellariteminer

import android.content.Context

/** Saved settings. Connection details are stored per coin. */
class Prefs(context: Context) {
    private val app = context.applicationContext ?: context
    private val sp = context.getSharedPreferences("miner", Context.MODE_PRIVATE)

    /** Username, written into the blocks you mine (claims it on the network). Empty = none. */
    var username: String
        get() = sp.getString("username", "")!!
        set(v) = sp.edit().putString("username", v.trim().uppercase()).apply()

    /** First-run setup finished. */
    var setupDone: Boolean
        get() = sp.getBoolean("setup_done", false)
        set(v) = sp.edit().putBoolean("setup_done", v).apply()

    /** The app's own wallet (one key for both coins). */
    val wallet = Wallet(sp)

    /** Solo mode: mine against a blockchain on this phone instead of a node (own coins only). */
    fun solo(coin: String): Boolean = sp.getBoolean("solo_$coin", false)
    fun setSolo(coin: String, v: Boolean) = sp.edit().putBoolean("solo_$coin", v).apply()
    val isSolo: Boolean get() = coin.kind != WorkKind.NONE && solo(coinId)

    var coinId: String
        get() = sp.getString("coin", "plsr")!!
        set(v) = sp.edit().putString("coin", v).apply()

    val coin: CoinProfile get() = CoinProfile.byId(coinId)

    /** Saved node/pool address; empty until the user sets one (the old placeholder counts as unset). */
    fun url(coin: String): String {
        val v = sp.getString("url_$coin", "")!!
        return if (v in OLD_PLACEHOLDERS) "" else v
    }
    fun setUrl(coin: String, v: String) = sp.edit().putString("url_$coin", v.trim()).apply()

    fun user(coin: String): String = sp.getString("user_$coin", "")!!
    fun setUser(coin: String, v: String) = sp.edit().putString("user_$coin", v.trim()).apply()

    fun password(coin: String): String = sp.getString("pass_$coin", "x")!!
    fun setPassword(coin: String, v: String) = sp.edit().putString("pass_$coin", v).apply()

    var threads: Int
        get() = sp.getInt("threads", defaultThreads())
        set(v) = sp.edit().putInt("threads", v.coerceIn(1, maxThreads())).apply()

    var chargingOnly: Boolean
        get() = sp.getBoolean("charging_only", true)
        set(v) = sp.edit().putBoolean("charging_only", v).apply()

    /** Builds the backend for the selected coin with its saved settings. */
    fun backend(): PoolBackend {
        val c = coin
        return when (c.protocol) {
            Protocol.NODE -> when {
                solo(c.id) -> SoloBackend(SoloBackend.chainFor(app, c), user(c.id), username)
                c.kind == WorkKind.TRAJECTORIES -> NebuliteClient(url(c.id), user(c.id), username)
                else -> NodeClient(url(c.id), user(c.id), username)
            }
            Protocol.STRATUM -> StratumClient(url(c.id), user(c.id), password(c.id))
        }
    }

    companion object {
        private val OLD_PLACEHOLDERS = setOf("http://192.168.1.10:5000", "http://192.168.1.10:5001")

        fun maxThreads() = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
        /** Half the cores by default, so the phone stays responsive and cooler. */
        fun defaultThreads() = (maxThreads() / 2).coerceAtLeast(1)
    }
}
