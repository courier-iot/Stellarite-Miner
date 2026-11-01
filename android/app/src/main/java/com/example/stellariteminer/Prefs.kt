package com.example.stellariteminer

import android.content.Context

/** Saved settings. Connection details are stored per coin. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("miner", Context.MODE_PRIVATE)

    var coinId: String
        get() = sp.getString("coin", "plsr")!!
        set(v) = sp.edit().putString("coin", v).apply()

    val coin: CoinProfile get() = CoinProfile.byId(coinId)

    fun url(coin: String): String =
        sp.getString("url_$coin", null) ?: if (coin == "plsr") CoinProfile.byId(coin).urlHint else ""
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
            Protocol.NODE -> NodeClient(url(c.id), user(c.id))
            Protocol.STRATUM -> StratumClient(url(c.id), user(c.id), password(c.id))
        }
    }

    companion object {
        fun maxThreads() = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
        /** Half the cores by default, so the phone stays responsive and cooler. */
        fun defaultThreads() = (maxThreads() / 2).coerceAtLeast(1)
    }
}
