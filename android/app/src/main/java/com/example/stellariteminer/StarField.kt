package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject

/**
 * Moving stars and a probe that speeds up, cruises, brakes, surveys and burns
 * fuel: an exact port of node/stars.py's integer maths (positions in mly,
 * velocities in mly per 1000 years, time in milli-years; kinematics in micro-ly,
 * uly/yr and uly/yr²), so mission times and fuel match the node to the last digit.
 *
 * Routes are an order of local star indices plus a cruise speed for each leg
 * (1-10 % of light speed).
 */
class StarField(
    val ids: IntArray,
    private val x: LongArray, private val y: LongArray, private val z: LongArray,
    private val vx: LongArray, private val vy: LongArray, private val vz: LongArray,
    val speed: Long, val launchT: Long, private val iterations: Int,
    /** Acceleration in mly/yr². */
    accel: Long = SoloData.PROBE_ACCEL,
    /** Survey stops (local indices): the probe must arrive at rest and stay [surveyYears]. */
    val stop: BooleanArray = BooleanArray(ids.size),
    surveyYears: Long = SoloData.SURVEY_YEARS,
    /** Fuel: total speed change allowed, in % of light speed. */
    dvBudgetPct: Long = SoloData.DV_BUDGET_PCT_C,
) {
    val size get() = ids.size
    private val V = speed * 1000          // top cruise speed, uly/yr
    private val A = accel * 1000          // uly/yr²
    val pct = V / 10                      // 1% of c in uly/yr
    private val surveyT = surveyYears * 1000
    val dvBudget = dvBudgetPct * pct

    /** Position of star i (local index) at time t (milli-years after J2000). */
    fun pos(i: Int, t: Long) = longArrayOf(
        x[i] + Math.floorDiv(vx[i] * t, 1_000_000L),
        y[i] + Math.floorDiv(vy[i] * t, 1_000_000L),
        z[i] + Math.floorDiv(vz[i] * t, 1_000_000L))

    fun distance(a: LongArray, b: LongArray): Long {
        val dx = a[0] - b[0]; val dy = a[1] - b[1]; val dz = a[2] - b[2]
        return isqrt(dx * dx + dy * dy + dz * dz)
    }

    private fun distanceUly(a: LongArray, b: LongArray): Long {
        val dx = a[0] - b[0]; val dy = a[1] - b[1]; val dz = a[2] - b[2]
        return isqrt((dx * dx + dy * dy + dz * dz) * 1_000_000L)
    }

    /** One leg of d uly from speed u cruising at c: (milli-years, end speed, delta-v). Same as stars.leg. */
    fun leg(d: Long, u: Long, c: Long, stop: Boolean): LongArray {
        if (!stop) {
            if (u <= c) {
                val ramp = (c * c - u * u) / (2 * A)
                if (d >= ramp) return longArrayOf((c - u) * 1000 / A + (d - ramp) * 1000 / c, c, c - u)
                val w = isqrt(u * u + 2 * A * d)
                return longArrayOf((w - u) * 1000 / A, w, w - u)
            }
            val ramp = (u * u - c * c) / (2 * A)
            if (d >= ramp) return longArrayOf((u - c) * 1000 / A + (d - ramp) * 1000 / c, c, u - c)
            val w = isqrt(u * u - 2 * A * d)
            return longArrayOf((u - w) * 1000 / A, w, u - w)
        }
        val brake = u * u / (2 * A)
        if (brake >= d) {
            val e = brake - d
            return longArrayOf(u * 1000 / A + 2 * isqrt(e * 1_000_000L / A), 0, u + 2 * isqrt(A * e))
        }
        if (u > c) return longArrayOf((u - c) * 1000 / A + c * 1000 / A + (d - brake) * 1000 / c, 0, u)
        val up = (c * c - u * u) / (2 * A); val down = c * c / (2 * A)
        if (up + down <= d) return longArrayOf((c - u) * 1000 / A + c * 1000 / A + (d - up - down) * 1000 / c, 0, 2 * c - u)
        val p = isqrt((2 * A * d + u * u) / 2)
        return longArrayOf((p - u) * 1000 / A + p * 1000 / A, 0, 2 * p - u)
    }

    /** (arrival time, speed there, delta-v) for a probe at `here` at time t, speed u, cruising at c to star i. */
    fun intercept(here: LongArray, t: Long, i: Int, u: Long, c: Long): LongArray {
        var arrive = t; var r = longArrayOf(0, u, 0)
        repeat(iterations) {
            r = leg(distanceUly(here, pos(i, arrive)), u, c, stop[i])
            arrive = t + r[0]
        }
        return longArrayOf(arrive, r[1], r[2])
    }

    /** [arrive]/[at]: arrival time and place; [depart]/[leaveAt]: after the survey, if this is a stop. */
    class Leg(val star: Int, val t: Long, val at: LongArray, val speed: Long, val dv: Long,
              val depart: Long, val leaveAt: LongArray, val pctC: Int)

    /** Each star's arrival, speed, fuel and departure, for local indices [order] at cruise speeds [speeds] (% of c). */
    fun legs(order: IntArray, speeds: IntArray): List<Leg> {
        var here = longArrayOf(0, 0, 0); var t = launchT; var u = 0L
        return order.mapIndexed { k, i ->
            val r = intercept(here, t, i, u, speeds[k] * pct)
            val at = pos(i, r[0])
            t = if (stop[i]) r[0] + surveyT else r[0]
            here = if (stop[i]) pos(i, t) else at
            u = r[1]
            Leg(i, r[0], at, r[1], r[2], t, here, speeds[k])
        }
    }

    /** (mission time in milli-years, delta-v in uly/yr). */
    fun eval(order: IntArray, speeds: IntArray): LongArray {
        var here = longArrayOf(0, 0, 0); var t = launchT; var u = 0L; var dv = 0L
        for (k in order.indices) {
            val i = order[k]
            val r = intercept(here, t, i, u, speeds[k] * pct)
            t = if (stop[i]) r[0] + surveyT else r[0]
            here = pos(i, t); u = r[1]; dv += r[2]
        }
        return longArrayOf(t - launchT, dv)
    }

    fun time(order: IntArray, speeds: IntArray): Long = eval(order, speeds)[0]
    fun dv(order: IntArray, speeds: IntArray): Long = eval(order, speeds)[1]

    /** Mission time, or Long.MAX_VALUE if the plan needs more fuel than the probe carries. */
    fun cost(order: IntArray, speeds: IntArray): Long = eval(order, speeds).let { if (it[1] > dvBudget) Long.MAX_VALUE else it[0] }

    /** Distance flown in mly (for display). */
    fun length(order: IntArray, speeds: IntArray): Long {
        var prev = longArrayOf(0, 0, 0); var total = 0L
        legs(order, speeds).forEach { total += distance(prev, it.at); prev = it.leaveAt }
        return total
    }

    private fun greedy(c: Long): IntArray {
        val left = (0 until size).sortedBy { ids[it] }.toMutableList()
        var here = longArrayOf(0, 0, 0); var t = launchT; var u = 0L
        val out = ArrayList<Int>()
        while (left.isNotEmpty()) {
            val best = left.minWith(compareBy<Int>({ intercept(here, t, it, u, c)[0] }, { ids[it] }))
            left.remove(best)
            val r = intercept(here, t, best, u, c)
            t = if (stop[best]) r[0] + surveyT else r[0]
            here = pos(best, t); u = r[1]
            out += best
        }
        return out.toIntArray()
    }

    /**
     * The greedy baseline (soonest reachable star next, ties by star id) at the fastest
     * uniform cruise speed whose fuel fits, as in stars.baseline_route: (order, speeds).
     */
    fun baseline(): Pair<IntArray, IntArray> {
        for (p in MAX_PCT downTo 1) {
            val order = greedy(p * pct); val speeds = IntArray(size) { p }
            if (dv(order, speeds) <= dvBudget) return order to speeds
        }
        error("no cruise speed fits the fuel budget")
    }

    companion object {
        const val MAX_PCT = 10

        fun isqrt(v: Long): Long {
            var r = Math.sqrt(v.toDouble()).toLong()
            while (r * r > v) r--
            while ((r + 1) * (r + 1) <= v) r++
            return r
        }

        /** Rocket equation (display only): launch mass / dry mass for a delta-v in uly/yr. */
        fun massRatio(dv: Long, pct: Long) = Math.exp(dv.toDouble() / (SoloData.EXHAUST_PCT_C * pct))

        /** From the stars in a node's /mining/work reply. */
        fun fromWork(work: JSONObject): StarField {
            val st: JSONArray = work.getJSONArray("stars")
            val n = st.length()
            fun col(k: String) = LongArray(n) { st.getJSONObject(it).optLong(k, 0) }
            val ids = IntArray(n) { st.getJSONObject(it).getInt("id") }
            val stopIds = work.optJSONArray("stops")?.let { a -> (0 until a.length()).map { a.getInt(it) }.toSet() } ?: emptySet()
            return StarField(ids, col("x"), col("y"), col("z"),
                col("vx"), col("vy"), col("vz"), work.getLong("probe_speed_mly_per_year"),
                work.getLong("launch_t"), work.getInt("intercept_iterations"),
                work.optLong("probe_accel_mly_per_year2", SoloData.PROBE_ACCEL),
                BooleanArray(n) { ids[it] in stopIds },
                work.optLong("survey_years", SoloData.SURVEY_YEARS),
                work.optLong("dv_budget_pct_c", SoloData.DV_BUDGET_PCT_C))
        }

        /** From the built-in catalog (solo mode), for the given star ids and survey stops. */
        fun fromCatalog(ids: List<Int>, stopIds: Collection<Int> = emptyList()): StarField {
            fun col(a: LongArray) = LongArray(ids.size) { a[ids[it]] }
            return StarField(ids.toIntArray(), col(SoloData.STAR_X), col(SoloData.STAR_Y), col(SoloData.STAR_Z),
                col(SoloData.STAR_VX), col(SoloData.STAR_VY), col(SoloData.STAR_VZ),
                SoloData.PROBE_SPEED, SoloData.LAUNCH_T, SoloData.INTERCEPT_ITERATIONS,
                SoloData.PROBE_ACCEL, BooleanArray(ids.size) { ids[it] in stopIds })
        }
    }
}

/**
 * Plans a fast route through moving stars within the fuel budget: the fast static
 * optimiser orders the stars on mid-mission positions, then an exact polish
 * (2-opt and Or-opt scored by true mission time) and a speed tuner (per-leg
 * cruise speeds, spending fuel where it saves the most time) take turns.
 * The best plan is kept between calls.
 */
class MovingRoutePlanner(private val field: StarField) {
    private val base = field.baseline()
    private val midT = field.launchT + field.time(base.first, base.second) / 2
    private val static = RouteOptimizer(
        DoubleArray(field.size) { field.pos(it, midT)[0].toDouble() },
        DoubleArray(field.size) { field.pos(it, midT)[1].toDouble() },
        DoubleArray(field.size) { field.pos(it, midT)[2].toDouble() })

    var best: IntArray = base.first
        private set
    var bestSpeeds: IntArray = base.second
        private set
    var bestTime: Long = field.time(best, bestSpeeds)
        private set
    val baselineTime = bestTime

    fun improve(millis: Long) {
        val deadline = System.currentTimeMillis() + millis
        static.improve(millis * 4 / 10)
        // a fresh candidate from the static optimiser at the baseline speed...
        var order = polish(static.best.copyOf(), base.second, deadline - millis * 3 / 10)
        var speeds = base.second.copyOf()
        consider(order, speeds)
        // ...then alternate speed tuning and order polishing on the best plan
        order = best.copyOf(); speeds = bestSpeeds.copyOf()
        while (System.currentTimeMillis() < deadline) {
            speeds = tune(order, speeds, deadline)
            order = polish(order, speeds, deadline)
            if (!consider(order, speeds)) break
        }
    }

    private fun consider(order: IntArray, speeds: IntArray): Boolean {
        val t = field.cost(order, speeds)
        if (t < bestTime) { best = order.copyOf(); bestSpeeds = speeds.copyOf(); bestTime = t; return true }
        return false
    }

    /** Hill-climb per-leg speeds: ±1/±2 on one leg, or one step moved from one leg to another. */
    private fun tune(order: IntArray, start: IntArray, deadline: Long): IntArray {
        var speeds = start; var cur = field.cost(order, speeds); var improved = true
        val n = speeds.size
        while (improved && System.currentTimeMillis() < deadline) {
            improved = false
            for (i in 0 until n) for (d in intArrayOf(1, -1, 2, -2)) {
                val v = speeds[i] + d
                if (v < 1 || v > StarField.MAX_PCT) continue
                val c = speeds.copyOf(); c[i] = v
                val t = field.cost(order, c)
                if (t < cur) { speeds = c; cur = t; improved = true }
            }
            for (i in 0 until n) for (j in 0 until n) if (i != j) {
                if (speeds[i] >= StarField.MAX_PCT || speeds[j] <= 1) continue
                val c = speeds.copyOf(); c[i]++; c[j]--
                val t = field.cost(order, c)
                if (t < cur) { speeds = c; cur = t; improved = true }
                if (System.currentTimeMillis() > deadline) break
            }
        }
        return speeds
    }

    /** 2-opt and Or-opt on the star order; speeds stay with their leg position. */
    private fun polish(start: IntArray, speeds: IntArray, deadline: Long): IntArray {
        var order = start; var cur = field.cost(order, speeds); var improved = true
        val n = order.size
        while (improved && System.currentTimeMillis() < deadline) {
            improved = false
            for (i in 0 until n - 1) for (j in i + 1 until n) {
                val c = order.copyOf(); var a = i; var b = j
                while (a < b) { val tmp = c[a]; c[a] = c[b]; c[b] = tmp; a++; b-- }
                val t = field.cost(c, speeds)
                if (t < cur) { order = c; cur = t; improved = true }
            }
            for (i in 0 until n) for (j in 0 until n) if (i != j) {
                val rest = order.toMutableList(); val s = rest.removeAt(i); rest.add(j, s)
                val c = rest.toIntArray(); val t = field.cost(c, speeds)
                if (t < cur) { order = c; cur = t; improved = true }
            }
        }
        return order
    }
}
