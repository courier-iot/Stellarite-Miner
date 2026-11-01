package com.example.stellariteminer

import java.util.Locale

/** Small formatting helpers for the HUD and ledger. */
object Format {
    fun duration(seconds: Long): String {
        val h = seconds / 3600
        val m = (seconds % 3600) / 60
        val s = seconds % 60
        return when {
            h > 0 -> "${h}h ${m}m"
            m > 0 -> "${m}m ${s}s"
            else -> "${s}s"
        }
    }

    fun clock(seconds: Long): String =
        String.format(Locale.US, "%02d:%02d:%02d", seconds / 3600, (seconds % 3600) / 60, seconds % 60)

    /** 1234567890 -> "1.23 G" */
    fun count(n: Long): String {
        val units = arrayOf("", " k", " M", " G", " T", " P")
        var v = n.toDouble()
        var i = 0
        while (v >= 1000 && i < units.size - 1) { v /= 1000; i++ }
        return if (i == 0) n.toString() else String.format(Locale.US, "%.2f%s", v, units[i])
    }

    fun coins(units: Long, unitsPerCoin: Long, decimals: Int = 4): String =
        String.format(Locale.US, "%.${decimals}f", units.toDouble() / unitsPerCoin)

    /** Splits a hashrate into the big number and its unit for the HUD. */
    fun rateParts(hps: Double): Pair<String, String> = when {
        hps >= 1e9 -> String.format(Locale.US, "%.2f", hps / 1e9) to "GH/s"
        hps >= 1e6 -> String.format(Locale.US, "%.2f", hps / 1e6) to "MH/s"
        else -> String.format(Locale.US, "%05.1f", hps / 1e3) to "kH/s"
    }
}
