package com.example.stellariteminer

import org.json.JSONObject
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.cosh
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sinh
import kotlin.math.sqrt

/**
 * Nebulite trajectory physics: a Kotlin port of nebulite/trajectory.py.
 * The phone uses it to search for cheap missions; the node does the official scoring.
 * All constants and planet data come from the node's /mining/work reply, so the
 * phone always uses the same model as the network.
 */
class TrajectoryModel(work: JSONObject) {
    class Planet(val name: String, val code: String, val a: Double, val l0: Double, val gm: Double, val radius: Double)

    val planets: List<Planet>
    private val muSun: Double
    private val kms: Double
    private val timePenalty: Double
    val minLegDays: Int
    private val flybySafety: Double
    private val minFlybyVinf: Double
    private val minPerihelion: Double

    // mission
    val target: Int
    val windowStart: Int
    val windowEnd: Int
    val maxTofDays: Int
    val flybyBodies: List<Int>
    val maxFlybys: Int

    init {
        val ps = work.getJSONArray("planets")
        planets = List(ps.length()) {
            val p = ps.getJSONObject(it)
            Planet(p.getString("name"), p.getString("code"), p.getDouble("a_au"),
                p.getDouble("l0_deg"), p.getDouble("gm"), p.getDouble("radius_km"))
        }
        val ph = work.getJSONObject("physics")
        muSun = ph.getDouble("mu_sun")
        kms = ph.getDouble("au_per_day_to_kms")
        timePenalty = ph.getDouble("time_penalty_mps_per_year")
        minLegDays = ph.getInt("min_leg_days")
        flybySafety = ph.getDouble("flyby_safety")
        minFlybyVinf = ph.getDouble("min_flyby_vinf")
        minPerihelion = ph.getDouble("min_perihelion_au")
        val m = work.getJSONObject("mission")
        target = m.getInt("target")
        windowStart = m.getInt("window_start")
        windowEnd = m.getInt("window_end")
        maxTofDays = m.getInt("max_tof_days")
        val fb = m.getJSONArray("flyby_bodies")
        flybyBodies = List(fb.length()) { fb.getInt(it) }
        maxFlybys = m.getInt("max_flybys")
    }

    /** Position (AU) and velocity (AU/day): x, y, vx, vy. */
    fun state(pid: Int, day: Double): DoubleArray {
        val p = planets[pid]
        val n = sqrt(muSun / (p.a * p.a * p.a))
        val th = Math.toRadians(p.l0) + n * day
        val v = sqrt(muSun / p.a)
        return doubleArrayOf(p.a * cos(th), p.a * sin(th), -v * sin(th), v * cos(th))
    }

    private fun stumpff(psi: Double): Pair<Double, Double> = when {
        psi > 1e-6 -> { val s = sqrt(psi); (1 - cos(s)) / psi to (s - sin(s)) / (s * s * s) }
        psi < -1e-6 -> { val s = sqrt(-psi); (1 - cosh(s)) / psi to (sinh(s) - s) / (s * s * s) }
        else -> 0.5 to 1.0 / 6.0
    }

    /** Prograde zero-revolution Lambert solver: returns v1x, v1y, v2x, v2y (AU/day) or null. */
    fun lambert(x1: Double, y1: Double, x2: Double, y2: Double, tof: Double): DoubleArray? {
        val r1 = hypot(x1, y1); val r2 = hypot(x2, y2)
        val cosDnu = max(-1.0, min(1.0, (x1 * x2 + y1 * y2) / (r1 * r2)))
        var dnu = acos(cosDnu)
        if (x1 * y2 - y1 * x2 < 0) dnu = 2 * PI - dnu
        if (abs(1 - cosDnu) < 1e-12) return null
        val a = sin(dnu) * sqrt(r1 * r2 / (1 - cosDnu))
        if (abs(a) < 1e-12) return null
        var lo = -400.0; var hi = 4 * PI * PI; var psi = 0.0
        repeat(80) {
            val (c2, c3) = stumpff(psi)
            val y = r1 + r2 + a * (psi * c3 - 1) / sqrt(c2)
            if (a > 0 && y < 0) {
                lo = psi
            } else {
                val chi = sqrt(y / c2)
                val dt = (chi * chi * chi * c3 + a * sqrt(y)) / sqrt(muSun)
                if (dt <= tof) lo = psi else hi = psi
            }
            psi = (lo + hi) / 2
        }
        val (c2, c3) = stumpff(psi)
        val y = r1 + r2 + a * (psi * c3 - 1) / sqrt(c2)
        if (y <= 0) return null
        val chi = sqrt(y / c2)
        if (abs((chi * chi * chi * c3 + a * sqrt(y)) / sqrt(muSun) - tof) > 1e-6 * tof) return null
        val f = 1 - y / r1
        val g = a * sqrt(y / muSun)
        val gdot = 1 - y / r2
        val v1x = (x2 - f * x1) / g; val v1y = (y2 - f * y1) / g
        val v2x = (gdot * x2 - x1) / g; val v2y = (gdot * y2 - y1) / g
        val hz = x1 * v1y - y1 * v1x
        val energy = (v1x * v1x + v1y * v1y) / 2 - muSun / r1
        val ecc = sqrt(max(0.0, 1 + 2 * energy * hz * hz / (muSun * muSun)))
        if (hz * hz / muSun / (1 + ecc) < minPerihelion) return null
        return doubleArrayOf(v1x, v1y, v2x, v2y)
    }

    private fun flybyDv(pid: Int, ix: Double, iy: Double, ox: Double, oy: Double): Double {
        val p = planets[pid]
        val a = hypot(ix, iy); val b = hypot(ox, oy)
        var dv = abs(b - a)
        if (a < 1e-9 || b < 1e-9) return dv
        val vavg = (a + b) / 2
        val turn = acos(max(-1.0, min(1.0, (ix * ox + iy * oy) / (a * b))))
        val maxTurn = 2 * asin(1 / (1 + flybySafety * p.radius * vavg * vavg / p.gm))
        if (turn > maxTurn) dv += 2 * vavg * sin((turn - maxTurn) / 2)
        return dv
    }

    /** Mission rules (same as trajectory.check). */
    fun allowed(seq: IntArray, days: IntArray): Boolean {
        if (seq.size < 2 || seq.size > maxFlybys + 2 || days.size != seq.size) return false
        if (seq[0] != EARTH || seq.last() != target) return false
        for (i in 1 until seq.size - 1) if (seq[i] !in flybyBodies) return false
        if (days[0] < windowStart || days[0] > windowEnd) return false
        return days.last() - days[0] <= maxTofDays
    }

    /** Cost in m/s-equivalent (fuel plus travel-time penalty), or +infinity if impossible. */
    fun cost(seq: IntArray, days: IntArray): Double = evaluate(seq, days)?.cost ?: Double.POSITIVE_INFINITY

    class Eval(val dvKms: Double, val years: Double, val cost: Double)

    fun evaluate(seq: IntArray, days: IntArray): Eval? {
        if (!allowed(seq, days)) return null
        val n = seq.size
        val legs = arrayOfNulls<DoubleArray>(n - 1)
        for (i in 0 until n - 1) {
            val tof = (days[i + 1] - days[i]).toDouble()
            if (tof < minLegDays) return null
            val s1 = state(seq[i], days[i].toDouble())
            val s2 = state(seq[i + 1], days[i + 1].toDouble())
            legs[i] = lambert(s1[0], s1[1], s2[0], s2[1], tof) ?: return null
        }
        val p0 = state(seq[0], days[0].toDouble())
        var dv = hypot(legs[0]!![0] - p0[2], legs[0]!![1] - p0[3]) * kms
        for (i in 1 until n - 1) {
            val p = state(seq[i], days[i].toDouble())
            val ix = (legs[i - 1]!![2] - p[2]) * kms; val iy = (legs[i - 1]!![3] - p[3]) * kms
            val ox = (legs[i]!![0] - p[2]) * kms; val oy = (legs[i]!![1] - p[3]) * kms
            if (hypot(ix, iy) < minFlybyVinf) return null
            dv += flybyDv(seq[i], ix, iy, ox, oy)
        }
        val pn = state(seq[n - 1], days[n - 1].toDouble())
        dv += hypot(legs[n - 2]!![2] - pn[2], legs[n - 2]!![3] - pn[3]) * kms
        val years = (days[n - 1] - days[0]) / 365.25
        return Eval(dv, years, dv * 1000 + timePenalty * years)
    }

    fun pathName(seq: IntArray) = seq.joinToString("-") { planets[it].code }

    companion object {
        const val EARTH = 2
    }
}

/**
 * Searches flyby sequences and dates for cheap Nebulite missions (port of traj_opt.py).
 * Keeps the best trajectory per sequence between calls, so the plan keeps improving.
 */
class TrajectoryOptimizer(private val model: TrajectoryModel) {
    private val rnd = kotlin.random.Random(System.nanoTime())
    private val best = LinkedHashMap<List<Int>, Pair<IntArray, Double>>()
    private val sequences: List<IntArray> = buildList {
        val fb = model.flybyBodies
        val maxK = minOf(2, model.maxFlybys)
        fun rec(prefix: List<Int>, k: Int) {
            add((listOf(TrajectoryModel.EARTH) + prefix + model.target).toIntArray())
            if (k < maxK) for (b in fb) rec(prefix + b, k + 1)
        }
        rec(emptyList(), 0)
    }
    private var rounds = 0

    var bestSeq: IntArray? = null
        private set
    var bestDays: IntArray? = null
        private set
    var bestCost = Double.POSITIVE_INFINITY
        private set

    private fun randomDays(seq: IntArray): IntArray {
        val n = seq.size
        val launch = model.windowStart + rnd.nextInt(model.windowEnd - model.windowStart + 1)
        val total = (0.3 + 0.7 * rnd.nextDouble()) * model.maxTofDays
        val cuts = DoubleArray(n - 2) { rnd.nextDouble() }.sorted()
        val fr = listOf(0.0) + cuts + listOf(1.0)
        val days = IntArray(n) { launch + Math.round(total * fr[it]).toInt() }
        for (i in 1 until n) days[i] = maxOf(days[i], days[i - 1] + model.minLegDays)
        return days
    }

    private fun patternSearch(seq: IntArray, start: IntArray, startCost: Double, deadline: Long): Pair<IntArray, Double> {
        var days = start; var cost = startCost; var step = 256
        while (step >= 1 && System.currentTimeMillis() < deadline) {
            var improved = false
            for (i in days.indices) for (s in intArrayOf(step, -step)) {
                val cand = if (i == 0) IntArray(days.size) { days[it] + s } else days.copyOf().also { it[i] += s }
                val c = model.cost(seq, cand)
                if (c < cost) { days = cand; cost = c; improved = true }
            }
            if (!improved) step /= 2
        }
        return days to cost
    }

    /** Keep searching for up to [millis] ms. Returns true if the best plan improved. */
    fun improve(millis: Long): Boolean {
        val before = bestCost
        val deadline = System.currentTimeMillis() + millis
        while (System.currentTimeMillis() < deadline && !Thread.currentThread().isInterrupted) {
            val pool = if (rounds < 2) sequences
                else best.entries.sortedBy { it.value.second }.take(6).map { it.key.toIntArray() }
            for (seq in pool) {
                if (System.currentTimeMillis() >= deadline) break
                var days: IntArray? = null; var c = Double.POSITIVE_INFINITY
                for (t in 0 until 20) {
                    val d = randomDays(seq)
                    val cc = model.cost(seq, d)
                    if (cc.isFinite()) { days = d; c = cc; break }
                }
                val key = seq.toList()
                if (days == null) { best.putIfAbsent(key, IntArray(0) to Double.POSITIVE_INFINITY); continue }
                val (d2, c2) = patternSearch(seq, days, c, deadline)
                if (c2 < (best[key]?.second ?: Double.POSITIVE_INFINITY)) best[key] = d2 to c2
                if (c2 < bestCost) { bestCost = c2; bestSeq = seq; bestDays = d2 }
            }
            rounds++
        }
        return bestCost < before
    }
}
