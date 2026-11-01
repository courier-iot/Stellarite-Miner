package com.example.stellariteminer

import java.security.MessageDigest
import kotlin.math.cos
import kotlin.math.sin

/**
 * The planets' real positions: the full VSOP87A theory (Bretagnon & Francou 1988),
 * exactly as nebulite/trajectory.py uses it. Heliocentric rectangular coordinates
 * in the J2000 ecliptic frame, 39,198 terms for Mercury to Neptune, accurate to
 * about 1 arcsecond for thousands of years around 2000. Nothing is truncated, and
 * velocities are the series' exact derivatives.
 *
 * The coefficients ship with the app as a Java resource (vsop87a.txt, the same
 * file the node reads; tools/gen_solo_data.py copies it), and [id] is the same
 * fingerprint the node reports as `ephemeris_id`, so a mismatch is caught.
 */
object Vsop87 {
    private class Series(val coord: IntArray, val power: IntArray, val a: DoubleArray, val b: DoubleArray, val c: DoubleArray)

    private lateinit var series: Array<Series>

    /** First 16 hex digits of the data file's SHA-256 (as trajectory.EPHEMERIS_ID). */
    lateinit var id: String
        private set

    private val loaded: Boolean by lazy { load(); true }

    private fun load() {
        val raw = Vsop87::class.java.getResourceAsStream("/vsop87a.txt")?.use { it.readBytes() }
            ?: throw IllegalStateException("vsop87a.txt is missing from the app")
        id = MessageDigest.getInstance("SHA-256").digest(raw).joinToString("") { "%02x".format(it.toInt() and 0xff) }.take(16)
        val rows = Array(8) { ArrayList<Array<String>>() }
        for (line in String(raw, Charsets.UTF_8).lineSequence()) {
            if (line.isEmpty() || line.startsWith("#")) continue
            val f = line.split(' ')
            rows[f[0].toInt()].add(f.toTypedArray())
        }
        series = Array(8) { p ->
            val r = rows[p]
            Series(IntArray(r.size) { r[it][1].toInt() }, IntArray(r.size) { r[it][2].toInt() },
                DoubleArray(r.size) { r[it][3].toDouble() }, DoubleArray(r.size) { r[it][4].toDouble() },
                DoubleArray(r.size) { r[it][5].toDouble() })
        }
    }

    fun ensureLoaded(): String { check(loaded); return id }

    // Most calls are for whole-day dates the optimiser revisits, so recent states are cached.
    private val cache = object : LinkedHashMap<Long, DoubleArray>(4096, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Long, DoubleArray>?) = size > 200_000
    }

    /** Heliocentric ecliptic J2000 position (AU) and velocity (AU/day): x, y, z, vx, vy, vz. */
    fun state(pid: Int, day: Double): DoubleArray {
        val whole = day == Math.floor(day) && Math.abs(day) < 1e7
        val key = if (whole) pid * 100_000_000L + day.toLong() else 0L
        if (whole) synchronized(cache) { cache[key]?.let { return it.copyOf() } }
        check(loaded)
        val s = series[pid]
        val t = day / 365250.0                                // Julian millennia from J2000
        val pos = DoubleArray(3); val vel = DoubleArray(3)
        for (k in s.a.indices) {
            val ph = s.b[k] + s.c[k] * t
            val cs = cos(ph); val sn = sin(ph)
            val pw = s.power[k]
            val tp = Math.pow(t, pw.toDouble())
            val dtp = if (pw > 0) pw * Math.pow(t, (pw - 1).toDouble()) else 0.0
            pos[s.coord[k]] += s.a[k] * cs * tp
            vel[s.coord[k]] += s.a[k] * (cs * dtp - sn * s.c[k] * tp)
        }
        val out = doubleArrayOf(pos[0], pos[1], pos[2], vel[0] / 365250.0, vel[1] / 365250.0, vel[2] / 365250.0)
        if (whole) synchronized(cache) { cache[key] = out.copyOf() }
        return out
    }
}
