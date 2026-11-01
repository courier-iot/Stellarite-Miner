package com.example.stellariteminer

import org.json.JSONObject
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.cosh
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sinh
import kotlin.math.sqrt

/**
 * Nebulite trajectory physics: a Kotlin port of nebulite/trajectory.py.
 * Planets follow JPL's approximate Keplerian elements (elliptical, inclined
 * orbits, 3D). The phone uses this to search for cheap missions and to draw the
 * orbit map; the node does the official scoring. All constants and planet data
 * come from the node (/mining/work or /planets), so the phone always uses the
 * same model as the network.
 */
class TrajectoryModel(work: JSONObject) {
    class Planet(val name: String, val code: String, val gm: Double, val radius: Double,
                 val el: DoubleArray, val rate: DoubleArray)   // a, e, i, L, peri, node (+ rates per century)

    val planets: List<Planet>
    val muSun: Double
    private val kms: Double
    private val timePenalty: Double
    val minLegDays: Int
    private val flybySafety: Double
    private val minFlybyVinf: Double
    private val minPerihelion: Double
    private val keplerIterations: Int

    // mission (absent when the model is built from /planets for the map)
    val target: Int
    val windowStart: Int
    val windowEnd: Int
    val maxTofDays: Int
    /** "science", "cargo" or "crewed" (as trajectory.MISSION_TYPES). */
    val missionType: String
    val flybyBodies: List<Int>
    val maxFlybys: Int

    init {
        val keys = arrayOf("a", "e", "i", "l", "peri", "node")
        val ps = work.getJSONArray("planets")
        planets = List(ps.length()) {
            val p = ps.getJSONObject(it)
            val e = p.getJSONObject("elements"); val r = p.getJSONObject("rates")
            Planet(p.getString("name"), p.getString("code"), p.getDouble("gm"), p.getDouble("radius_km"),
                DoubleArray(6) { k -> e.getDouble(keys[k]) }, DoubleArray(6) { k -> r.getDouble(keys[k]) })
        }
        val ph = work.getJSONObject("physics")
        muSun = ph.getDouble("mu_sun")
        kms = ph.getDouble("au_per_day_to_kms")
        timePenalty = work.optJSONObject("mission")?.optDouble("time_penalty_mps_per_year", Double.NaN)
            ?.takeIf { !it.isNaN() } ?: ph.getDouble("time_penalty_mps_per_year")
        minLegDays = ph.getInt("min_leg_days")
        flybySafety = ph.getDouble("flyby_safety")
        minFlybyVinf = ph.getDouble("min_flyby_vinf")
        minPerihelion = ph.getDouble("min_perihelion_au")
        keplerIterations = ph.optInt("kepler_iterations", 12)
        val m = work.optJSONObject("mission")
        target = m?.getInt("target") ?: 4
        windowStart = m?.getInt("window_start") ?: 0
        windowEnd = m?.getInt("window_end") ?: 0
        maxTofDays = m?.getInt("max_tof_days") ?: 0
        flybyBodies = m?.getJSONArray("flyby_bodies")?.let { fb -> List(fb.length()) { fb.getInt(it) } } ?: emptyList()
        maxFlybys = m?.getInt("max_flybys") ?: 0
        missionType = m?.optString("type", "science") ?: "science"
    }

    /** Heliocentric ecliptic position (AU) and velocity (AU/day): x, y, z, vx, vy, vz. */
    fun state(pid: Int, day: Double): DoubleArray {
        val p = planets[pid]
        val t = day / 36525.0
        val a = p.el[0] + p.rate[0] * t
        val e = p.el[1] + p.rate[1] * t
        val inc = p.el[2] + p.rate[2] * t
        val l = p.el[3] + p.rate[3] * t
        val peri = p.el[4] + p.rate[4] * t
        val node = p.el[5] + p.rate[5] * t
        val mDeg = (l - peri) % 360.0
        val m = Math.toRadians(if (mDeg < 0) mDeg + 360.0 else mDeg)
        val w = Math.toRadians(peri - node); val o = Math.toRadians(node); val i = Math.toRadians(inc)
        var ea = m + e * sin(m)
        repeat(keplerIterations) { ea -= (ea - e * sin(ea) - m) / (1 - e * cos(ea)) }
        val cE = cos(ea); val sE = sin(ea); val b = sqrt(1 - e * e)
        val xp = a * (cE - e); val yp = a * b * sE
        val edot = sqrt(muSun / (a * a * a)) / (1 - e * cE)
        val vxp = -a * sE * edot; val vyp = a * b * cE * edot
        val cw = cos(w); val sw = sin(w); val cO = cos(o); val sO = sin(o); val ci = cos(i); val si = sin(i)
        val r11 = cw * cO - sw * sO * ci; val r12 = -sw * cO - cw * sO * ci
        val r21 = cw * sO + sw * cO * ci; val r22 = -sw * sO + cw * cO * ci
        val r31 = sw * si; val r32 = cw * si
        return doubleArrayOf(r11 * xp + r12 * yp, r21 * xp + r22 * yp, r31 * xp + r32 * yp,
            r11 * vxp + r12 * vyp, r21 * vxp + r22 * vyp, r31 * vxp + r32 * vyp)
    }

    private fun stumpff(psi: Double): Pair<Double, Double> = when {
        psi > 1e-6 -> { val s = sqrt(psi); (1 - cos(s)) / psi to (s - sin(s)) / (s * s * s) }
        psi < -1e-6 -> { val s = sqrt(-psi); (1 - cosh(s)) / psi to (sinh(s) - s) / (s * s * s) }
        else -> 0.5 to 1.0 / 6.0
    }

    /**
     * Prograde zero-revolution Lambert solver in 3D. r1, r2: positions (first 3 entries used).
     * Returns v1 (3) + v2 (3) in AU/day, or null.
     */
    fun lambert(r1: DoubleArray, r2: DoubleArray, tof: Double): DoubleArray? {
        val n1 = sqrt(r1[0] * r1[0] + r1[1] * r1[1] + r1[2] * r1[2])
        val n2 = sqrt(r2[0] * r2[0] + r2[1] * r2[1] + r2[2] * r2[2])
        val cosDnu = max(-1.0, min(1.0, (r1[0] * r2[0] + r1[1] * r2[1] + r1[2] * r2[2]) / (n1 * n2)))
        var dnu = acos(cosDnu)
        if (r1[0] * r2[1] - r1[1] * r2[0] < 0) dnu = 2 * PI - dnu
        if (abs(1 - cosDnu) < 1e-12) return null
        val a = sin(dnu) * sqrt(n1 * n2 / (1 - cosDnu))
        if (abs(a) < 1e-12) return null
        var lo = -400.0; var hi = 4 * PI * PI; var psi = 0.0
        repeat(80) {
            val (c2, c3) = stumpff(psi)
            val y = n1 + n2 + a * (psi * c3 - 1) / sqrt(c2)
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
        val y = n1 + n2 + a * (psi * c3 - 1) / sqrt(c2)
        if (y <= 0) return null
        val chi = sqrt(y / c2)
        if (abs((chi * chi * chi * c3 + a * sqrt(y)) / sqrt(muSun) - tof) > 1e-6 * tof) return null
        val f = 1 - y / n1
        val g = a * sqrt(y / muSun)
        val gdot = 1 - y / n2
        val v = DoubleArray(6)
        for (k in 0 until 3) {
            v[k] = (r2[k] - f * r1[k]) / g
            v[k + 3] = (gdot * r2[k] - r1[k]) / g
        }
        val hx = r1[1] * v[2] - r1[2] * v[1]; val hy = r1[2] * v[0] - r1[0] * v[2]; val hz = r1[0] * v[1] - r1[1] * v[0]
        val h2 = hx * hx + hy * hy + hz * hz
        val energy = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) / 2 - muSun / n1
        val ecc = sqrt(max(0.0, 1 + 2 * energy * h2 / (muSun * muSun)))
        if (h2 / muSun / (1 + ecc) < minPerihelion) return null
        return v
    }

    private fun flybyDv(pid: Int, vin: DoubleArray, vout: DoubleArray): Double {
        val p = planets[pid]
        val a = norm(vin); val b = norm(vout)
        var dv = abs(b - a)
        if (a < 1e-9 || b < 1e-9) return dv
        val vavg = (a + b) / 2
        val turn = acos(max(-1.0, min(1.0, (vin[0] * vout[0] + vin[1] * vout[1] + vin[2] * vout[2]) / (a * b))))
        val maxTurn = 2 * asin(1 / (1 + flybySafety * p.radius * vavg * vavg / p.gm))
        if (turn > maxTurn) dv += 2 * vavg * sin((turn - maxTurn) / 2)
        return dv
    }

    private fun norm(v: DoubleArray) = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    /** Mission rules (same as trajectory.check). */
    fun allowed(seq: IntArray, days: IntArray): Boolean {
        if (seq.size < 2 || seq.size > maxFlybys + 2 || days.size != seq.size) return false
        if (seq[0] != EARTH || seq.last() != target) return false
        for (i in 1 until seq.size - 1) if (seq[i] !in flybyBodies) return false
        if (days[0] < windowStart || days[0] > windowEnd) return false
        return days.last() - days[0] <= maxTofDays
    }

    /** Cost in m/s-equivalent (fuel plus travel-time penalty), or +infinity if impossible. */
    fun cost(seq: IntArray, days: IntArray): Double =
        if (allowed(seq, days)) evaluate(seq, days)?.cost ?: Double.POSITIVE_INFINITY else Double.POSITIVE_INFINITY

    class Eval(val dvKms: Double, val years: Double, val cost: Double)

    /** Physics only (no mission rules), like trajectory.evaluate. */
    fun evaluate(seq: IntArray, days: IntArray): Eval? {
        val n = seq.size
        if (n < 2 || days.size != n) return null
        val st = Array(n) { state(seq[it], days[it].toDouble()) }
        val legs = arrayOfNulls<DoubleArray>(n - 1)
        for (i in 0 until n - 1) {
            val tof = (days[i + 1] - days[i]).toDouble()
            if (tof < minLegDays) return null
            legs[i] = lambert(st[i], st[i + 1], tof) ?: return null
        }
        fun rel(v: DoubleArray, off: Int, p: DoubleArray) =
            doubleArrayOf((v[off] - p[3]) * kms, (v[off + 1] - p[4]) * kms, (v[off + 2] - p[5]) * kms)
        var dv = norm(rel(legs[0]!!, 0, st[0]))
        for (i in 1 until n - 1) {
            val vin = rel(legs[i - 1]!!, 3, st[i]); val vout = rel(legs[i]!!, 0, st[i])
            if (norm(vin) < minFlybyVinf) return null
            dv += flybyDv(seq[i], vin, vout)
        }
        dv += norm(rel(legs[n - 2]!!, 3, st[n - 1]))
        val years = (days[n - 1] - days[0]) / 365.25
        return Eval(dv, years, dv * 1000 + timePenalty * years)
    }

    /** Points along a trajectory for drawing: each leg's Lambert arc integrated step by step. */
    fun samplePath(seq: IntArray, days: IntArray, pointsPerLeg: Int = 60): List<DoubleArray> {
        val out = ArrayList<DoubleArray>()
        for (i in 0 until seq.size - 1) {
            val r1 = state(seq[i], days[i].toDouble()); val r2 = state(seq[i + 1], days[i + 1].toDouble())
            val tof = (days[i + 1] - days[i]).toDouble()
            val v = lambert(r1, r2, tof) ?: continue
            var s = doubleArrayOf(r1[0], r1[1], r1[2], v[0], v[1], v[2])
            val sub = 20
            val h = tof / (pointsPerLeg * sub)
            out.add(doubleArrayOf(s[0], s[1], s[2]))
            repeat(pointsPerLeg) {
                repeat(sub) { s = rk4(s, h) }
                out.add(doubleArrayOf(s[0], s[1], s[2]))
            }
        }
        return out
    }

    private fun deriv(s: DoubleArray): DoubleArray {
        val r = sqrt(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]); val k = -muSun / (r * r * r)
        return doubleArrayOf(s[3], s[4], s[5], k * s[0], k * s[1], k * s[2])
    }

    private fun rk4(s: DoubleArray, h: Double): DoubleArray {
        fun add(a: DoubleArray, b: DoubleArray, f: Double) = DoubleArray(6) { a[it] + f * b[it] }
        val k1 = deriv(s); val k2 = deriv(add(s, k1, h / 2)); val k3 = deriv(add(s, k2, h / 2)); val k4 = deriv(add(s, k3, h))
        return DoubleArray(6) { s[it] + h / 6 * (k1[it] + 2 * k2[it] + 2 * k3[it] + k4[it]) }
    }

    /** The spacecraft's position (AU) on day `day` of a mission, or null outside it. */
    fun positionAt(seq: IntArray, days: IntArray, day: Double): DoubleArray? {
        for (i in 0 until seq.size - 1) {
            if (day < days[i] || day > days[i + 1]) continue
            val r1 = state(seq[i], days[i].toDouble()); val r2 = state(seq[i + 1], days[i + 1].toDouble())
            val v = lambert(r1, r2, (days[i + 1] - days[i]).toDouble()) ?: return null
            var s = doubleArrayOf(r1[0], r1[1], r1[2], v[0], v[1], v[2])
            val dt = day - days[i]
            val steps = maxOf(1, (dt / 2.0).toInt())
            repeat(steps) { s = rk4(s, dt / steps) }
            return doubleArrayOf(s[0], s[1], s[2])
        }
        return null
    }

    /** One orbit of a planet as drawable points (from its elements at `day`). */
    fun orbitPoints(pid: Int, day: Double, n: Int = 120): List<DoubleArray> {
        val a = planets[pid].el[0]
        val period = 2 * PI * sqrt(a * a * a / muSun)
        return List(n + 1) { k -> state(pid, day + period * k / n).copyOfRange(0, 3) }
    }

    fun pathName(seq: IntArray) = seq.joinToString("-") { planets[it].code }

    companion object {
        const val EARTH = 2

        /** Calendar date (YYYY-MM-DD) of a mission day number: days since J2000 (noon, 1 Jan 2000). */
        fun dateOf(day: Number): String = java.time.LocalDateTime.of(2000, 1, 1, 12, 0)
            .plusSeconds(Math.floor(day.toDouble() * 86400).toLong()).toLocalDate().toString()
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
