package com.example.stellariteminer

import android.content.Context

/** Saved settings. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("miner", Context.MODE_PRIVATE)

    var nodeUrl: String
        get() = sp.getString("node_url", "http://192.168.1.10:5000")!!
        set(v) = sp.edit().putString("node_url", v.trim()).apply()

    var address: String
        get() = sp.getString("address", "")!!
        set(v) = sp.edit().putString("address", v.trim()).apply()

    var threads: Int
        get() = sp.getInt("threads", defaultThreads())
        set(v) = sp.edit().putInt("threads", v.coerceIn(1, maxThreads())).apply()

    var chargingOnly: Boolean
        get() = sp.getBoolean("charging_only", true)
        set(v) = sp.edit().putBoolean("charging_only", v).apply()

    companion object {
        fun maxThreads() = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
        /** Half the cores by default, so the phone stays responsive and cooler. */
        fun defaultThreads() = (maxThreads() / 2).coerceAtLeast(1)
    }
}
