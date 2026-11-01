package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject

/**
 * Moving stars and a probe at constant speed: an exact port of node/stars.py's
 * integer maths (positions in mly, velocities in mly per 1000 years, time in
 * milli-years), so mission times match the node to the last digit.
 */
class StarField(
    val ids: IntArray,
    private val x: LongArray, private val y: LongArray, private val z: LongArray,
    private val vx: LongArray, private val vy: LongArray, private val vz: LongArray,
    val speed: Long, val launchT: Long, private val iterations: Int,
) {
    val size get() = ids.size

    /** Position of star i (local index) at time t (milli-years after J2000). */
    fun pos(i: Int, t: Long) = longArrayOf(
        x[i] + Math.floorDiv(vx[i] * t, 1_000_000L),
        y[i] + Math.floorDiv(vy[i] * t, 1_000_000L),
        z[i] + Math.floorDiv(vz[i] * t, 1_000_000L))

    private fun isqrt(v: Long): Long {
        var r = Math.sqrt(v.toDouble()).toLong()
        while (r * r > v) r--
        while ((r + 1) * (r + 1) <= v) r++
        return r
    }

    fun distance(a: LongArray, b: LongArray): Long {
        val dx = a[0] - b[0]; val dy = a[1] - b[1]; val dz = a[2] - b[2]
        return isqrt(dx * dx + dy * dy + dz * dz)
    }

    /** Arrival time when a probe at `here` at time t heads for star i. */
    fun intercept(here: LongArray, t: Long, i: Int): Long {
        var arrive = t
        repeat(iterations) { arrive = t + distance(here, pos(i, arrive)) * 1000 / speed }
        return arrive
    }

    class Leg(val star: Int, val t: Long, val at: LongArray)

    /** Each flyby's local star index, arrival time and position, for a route of local indices. */
    fun legs(order: IntArray): List<Leg> {
        var here = longArrayOf(0, 0, 0); var t = launchT
        return order.map { i -> t = intercept(here, t, i); here = pos(i, t); Leg(i, t, here) }
    }

    /** Mission time in milli-years. */
    fun time(order: IntArray): Long = (legs(order).lastOrNull()?.t ?: launchT) - launchT

    /** Distance flown in mly (for display). */
    fun length(order: IntArray): Long {
        var prev = longArrayOf(0, 0, 0); var total = 0L
        legs(order).forEach { total += distance(prev, it.at); prev = it.at }
        return total
    }

    /** Greedy route (soonest reachable star next, ties by star id), as in stars.baseline_route. */
    fun baseline(): IntArray {
        val left = (0 until size).sortedBy { ids[it] }.toMutableList()
        var here = longArrayOf(0, 0, 0); var t = launchT
        val out = ArrayList<Int>()
        while (left.isNotEmpty()) {
            val best = left.minWith(compareBy<Int>({ intercept(here, t, it) }, { ids[it] }))
            left.remove(best)
            t = intercept(here, t, best); here = pos(best, t)
            out += best
        }
        return out.toIntArray()
    }

    companion object {
        /** From the stars in a node's /mining/work reply. */
        fun fromWork(work: JSONObject): StarField {
            val st: JSONArray = work.getJSONArray("stars")
            val n = st.length()
            fun col(k: String) = LongArray(n) { st.getJSONObject(it).optLong(k, 0) }
            return StarField(IntArray(n) { st.getJSONObject(it).getInt("id") }, col("x"), col("y"), col("z"),
                col("vx"), col("vy"), col("vz"), work.getLong("probe_speed_mly_per_year"),
                work.getLong("launch_t"), work.getInt("intercept_iterations"))
        }

        /** From the built-in catalog (solo mode), for the given star ids. */
        fun fromCatalog(ids: List<Int>): StarField {
            fun col(a: LongArray) = LongArray(ids.size) { a[ids[it]] }
            return StarField(ids.toIntArray(), col(SoloData.STAR_X), col(SoloData.STAR_Y), col(SoloData.STAR_Z),
                col(SoloData.STAR_VX), col(SoloData.STAR_VY), col(SoloData.STAR_VZ),
                SoloData.PROBE_SPEED, SoloData.LAUNCH_T, SoloData.INTERCEPT_ITERATIONS)
        }
    }
}

/**
 * Plans a fast route through moving stars: the fast static optimiser works on
 * star positions mid-mission, then an exact polish (2-opt and Or-opt scored by
 * true mission time) refines it. The best exact route is kept between calls.
 */
class MovingRoutePlanner(private val field: StarField) {
    private val midT = field.launchT + field.time(field.baseline()) / 2
    private val static = RouteOptimizer(
        DoubleArray(field.size) { field.pos(it, midT)[0].toDouble() },
        DoubleArray(field.size) { field.pos(it, midT)[1].toDouble() },
        DoubleArray(field.size) { field.pos(it, midT)[2].toDouble() })

    var best: IntArray = field.baseline()
        private set
    var bestTime: Long = field.time(best)
        private set

    fun improve(millis: Long) {
        val deadline = System.currentTimeMillis() + millis
        static.improve(millis * 6 / 10)
        val cand = polish(static.best.copyOf(), deadline)
        val t = field.time(cand)
        if (t < bestTime) { best = cand; bestTime = t }
        if (System.currentTimeMillis() < deadline) {
            val again = polish(best.copyOf(), deadline)
            val t2 = field.time(again)
            if (t2 < bestTime) { best = again; bestTime = t2 }
        }
    }

    private fun polish(start: IntArray, deadline: Long): IntArray {
        var order = start; var cur = field.time(order); var improved = true
        val n = order.size
        while (improved && System.currentTimeMillis() < deadline) {
            improved = false
            for (i in 0 until n - 1) for (j in i + 1 until n) {
                val c = order.copyOf(); var a = i; var b = j
                while (a < b) { val tmp = c[a]; c[a] = c[b]; c[b] = tmp; a++; b-- }
                val t = field.time(c)
                if (t < cur) { order = c; cur = t; improved = true }
            }
            for (i in 0 until n) for (j in 0 until n) if (i != j) {
                val rest = order.toMutableList(); val s = rest.removeAt(i); rest.add(j, s)
                val c = rest.toIntArray(); val t = field.time(c)
                if (t < cur) { order = c; cur = t; improved = true }
            }
        }
        return order
    }
}
