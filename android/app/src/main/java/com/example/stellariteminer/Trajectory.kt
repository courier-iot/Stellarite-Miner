package com.example.stellariteminer

import org.json.JSONObject
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.asin
import kotlin.math.asinh
import kotlin.math.cos
import kotlin.math.cosh
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sinh
import kotlin.math.sqrt

/**
 * Nebulite trajectory physics: a Kotlin port of nebulite/trajectory.py.
 * Planets follow the full VSOP87A theory ([Vsop87], about 1 arcsecond accuracy).
 * The phone uses this to search for cheap missions and to draw the orbit map; the
 * node does the official scoring. Constants come from the node (/mining/work or
 * /planets), and the node's `ephemeris_id` must match the app's planet data.
 */
class TrajectoryModel(work: JSONObject) {
    class Planet(val name: String, val code: String, val gm: Double, val radius: Double,
                 val el: DoubleArray, val rate: DoubleArray)   // mean a, e, i, L, peri, node (+ rates): sizes only

    val planets: List<Planet>
    val muSun: Double
    val kms: Double
    private val timePenalty: Double
    val minLegDays: Int
    private val flybySafety: Double
    val minFlybyVinf: Double
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
    /** Interstellar-object intercepts only count the encounter speed at this weight (else 1). */
    val arrivalWeight: Double
    /** The block's interstellar object (intercept missions only). */
    val iso: IsoOrbit?

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
        // The node and the app must use the same planet data; older nodes didn't say which they used.
        val nodeEphemeris = ph.optString("ephemeris_id", "")
        val mine = Vsop87.ensureLoaded()
        if (nodeEphemeris.isNotEmpty() && nodeEphemeris != mine)
            throw IllegalStateException("This app's planet data ($mine) doesn't match the node's ($nodeEphemeris): update the app or the node")
        val m = work.optJSONObject("mission")
        target = m?.getInt("target") ?: 4
        windowStart = m?.getInt("window_start") ?: 0
        windowEnd = m?.getInt("window_end") ?: 0
        maxTofDays = m?.getInt("max_tof_days") ?: 0
        flybyBodies = m?.getJSONArray("flyby_bodies")?.let { fb -> List(fb.length()) { fb.getInt(it) } } ?: emptyList()
        maxFlybys = m?.getInt("max_flybys") ?: 0
        missionType = m?.optString("type", "science") ?: "science"
        arrivalWeight = m?.optDouble("arrival_weight", 1.0) ?: 1.0
        iso = m?.optJSONObject("iso")?.let { IsoOrbit(it, muSun, ph.optInt("hyperbola_iterations", 30)) }
    }

    /** Heliocentric ecliptic J2000 position (AU) and velocity (AU/day): x, y, z, vx, vy, vz (full VSOP87A,
     *  or the block's interstellar object for [ISO]). */
    fun state(pid: Int, day: Double): DoubleArray =
        if (pid == ISO) ((iso ?: extraIso) ?: throw IllegalStateException("no interstellar object in this mission")).state(day)
        else Vsop87.state(pid, day)

    /** For drawing: an interstellar object to use when this model has no mission of its own (the map). */
    var extraIso: IsoOrbit? = null

    private fun stumpff(psi: Double): Pair<Double, Double> = when {
        psi > 1e-6 -> { val s = sqrt(psi); (1 - cos(s)) / psi to (s - sin(s)) / (s * s * s) }
        psi < -1e-6 -> { val s = sqrt(-psi); (1 - cosh(s)) / psi to (sinh(s) - s) / (s * s * s) }
        else -> 0.5 to 1.0 / 6.0
    }

    /**
     * Prograde zero-revolution Lambert solver in 3D. r1, r2: positions (first 3 entries used).
     * Returns v1 (3) + v2 (3) in AU/day, or null.
     */
    fun lambert(r1: DoubleArray, r2: DoubleArray, tof: Double, minPeri: Double = minPerihelion): DoubleArray? {
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
            val y = if (c2 > 0) n1 + n2 + a * (psi * c3 - 1) / sqrt(c2) else Double.NaN
            if (c2 <= 0) {
                hi = psi                       // at the one-revolution limit: psi is too large
            } else if (a > 0 && y < 0) {
                lo = psi
            } else if (y <= 0) {
                hi = psi                       // long-way transfer past its limit (as trajectory.lambert)
            } else {
                val chi = sqrt(y / c2)
                val dt = (chi * chi * chi * c3 + a * sqrt(y)) / sqrt(muSun)
                if (dt <= tof) lo = psi else hi = psi
            }
            psi = (lo + hi) / 2
        }
        val (c2, c3) = stumpff(psi)
        if (c2 <= 0) return null
        val y = n1 + n2 + a * (psi * c3 - 1) / sqrt(c2)
        if (!(y > 0)) return null
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
        if (h2 / muSun / (1 + ecc) < minPeri) return null
        return v
    }

    /**
     * Burn for a powered flyby (as trajectory.flyby_dv): the craft swings past the planet on
     * an incoming hyperbola at |vin| and leaves on an outgoing one at |vout|, both sharing one
     * periapsis, where a single burn changes the speed (the Oberth effect: a burn deep in the
     * planet's gravity well changes the speed far from it by more). The periapsis is chosen so
     * the two half-turns add up to the bend needed; if even 1.1 planet radii can't bend enough,
     * the missing turn is paid for directly.
     */
    fun flybyDv(pid: Int, vin: DoubleArray, vout: DoubleArray): Double {
        val p = planets[pid]
        val mu = p.gm
        val a = norm(vin); val b = norm(vout)
        if (a < 1e-9 || b < 1e-9) return abs(b - a)
        val turn = acos(max(-1.0, min(1.0, (vin[0] * vout[0] + vin[1] * vout[1] + vin[2] * vout[2]) / (a * b))))
        val rpMin = flybySafety * p.radius
        fun maxTurn(rp: Double) = asin(1 / (1 + rp * a * a / mu)) + asin(1 / (1 + rp * b * b / mu))
        val rp: Double; val extra: Double
        if (turn > maxTurn(rpMin)) { rp = rpMin; extra = turn - maxTurn(rpMin) }
        else {
            var lo = rpMin; var hi = 1e12
            repeat(FLYBY_RP_ITERATIONS) {
                val mid = sqrt(lo * hi)
                if (maxTurn(mid) > turn) lo = mid else hi = mid
            }
            rp = sqrt(lo * hi); extra = 0.0
        }
        var burn = abs(sqrt(b * b + 2 * mu / rp) - sqrt(a * a + 2 * mu / rp))
        if (extra > 0) burn += 2 * ((a + b) / 2) * sin(extra / 2)
        return burn
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

    class Eval(val dvKms: Double, val years: Double, val cost: Double, val launchKms: Double = 0.0,
               val flybyKms: Double = 0.0, val arrivalKms: Double = 0.0)

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
        val launch = norm(rel(legs[0]!!, 0, st[0]))
        var flybys = 0.0
        for (i in 1 until n - 1) {
            val vin = rel(legs[i - 1]!!, 3, st[i]); val vout = rel(legs[i]!!, 0, st[i])
            if (norm(vin) < minFlybyVinf) return null
            flybys += flybyDv(seq[i], vin, vout)
        }
        val arrival = norm(rel(legs[n - 2]!!, 3, st[n - 1]))
        // same order of additions as trajectory.evaluate: launch + sum(flybys) + weight * arrival
        val dv = launch + flybys + arrivalWeight * arrival
        val years = (days[n - 1] - days[0]) / 365.25
        return Eval(dv, years, dv * 1000 + timePenalty * years, launch, flybys, arrival)
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

    fun deriv(s: DoubleArray): DoubleArray {
        val r = sqrt(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]); val k = -muSun / (r * r * r)
        return doubleArrayOf(s[3], s[4], s[5], k * s[0], k * s[1], k * s[2])
    }

    fun rk4(s: DoubleArray, h: Double): DoubleArray {
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

    fun pathName(seq: IntArray) = seq.joinToString("-") { if (it == SUN) "Sun" else if (it == ISO) "ISO" else planets[it].code }

    /** The block's escape mission (toward a star, or a heliopause run), if this model was built for one (else null). */
    val escape: EscapeMission? = work.optJSONObject("mission")
        ?.takeIf { it.optString("type") == "escape" || it.optString("type") == "heliopause" }?.let { EscapeMission(it) }

    companion object {
        const val EARTH = 2
        const val SUN = 8                 // pseudo-body: an escape mission's Sun dive (as trajectory.SUN)
        const val ISO = 9                 // pseudo-body: the block's interstellar object (as trajectory.ISO)
        const val FLYBY_RP_ITERATIONS = 60

        /** Calendar date (YYYY-MM-DD) of a mission day number: days since J2000 (noon, 1 Jan 2000). */
        fun dateOf(day: Number): String = java.time.LocalDateTime.of(2000, 1, 1, 12, 0)
            .plusSeconds(Math.floor(day.toDouble() * 86400).toLong()).toLocalDate().toString()
    }
}

/**
 * Searches flyby sequences and dates for cheap Nebulite missions (port of traj_opt.py).
 * Keeps the best trajectory per sequence between calls, so the plan keeps improving.
 */
class TrajectoryOptimizer(private val model: TrajectoryModel, private var start: Pair<IntArray, IntArray>? = null) {
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
        start?.let { (seq, days) ->              // refine the block's baseline first: never worse than it (as traj_opt)
            start = null
            val c = model.cost(seq, days)
            if (c.isFinite()) {
                val (d2, c2) = patternSearch(seq, days, c, minOf(deadline, System.currentTimeMillis() + millis / 4))
                best[seq.toList()] = d2 to c2
                if (c2 < bestCost) { bestCost = c2; bestSeq = seq; bestDays = d2 }
            }
        }
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

/**
 * An interstellar object's path: a Kepler hyperbola about the Sun (as trajectory.iso_state),
 * from the mission's "iso" block: e, q_au, t_peri and the orbit's perihelion and in-plane
 * directions p_hat, q_hat.
 */
class IsoOrbit(iso: JSONObject, private val mu: Double, private val iterations: Int) {
    val e = iso.getDouble("e")
    val q = iso.getDouble("q_au")
    val tPeri = iso.getDouble("t_peri")
    val vinfKms = iso.getDouble("vinf_kms")
    val p = iso.getJSONArray("p_hat").let { a -> DoubleArray(3) { a.getDouble(it) } }
    val qh = iso.getJSONArray("q_hat").let { a -> DoubleArray(3) { a.getDouble(it) } }

    fun state(day: Double): DoubleArray {
        val a = -q / (e - 1)
        val n = sqrt(mu / ((-a) * (-a) * (-a)))
        val m = n * (day - tPeri)
        var f = asinh(m / e)
        repeat(iterations) { f -= (e * sinh(f) - f - m) / (e * cosh(f) - 1) }
        val ch = cosh(f); val sh = sinh(f)
        val b = -a * sqrt(e * e - 1)
        val x = a * (ch - e); val y = b * sh
        val fdot = n / (e * ch - 1)
        val vx = a * sh * fdot; val vy = b * ch * fdot
        return DoubleArray(6) { if (it < 3) x * p[it] + y * qh[it] else vx * p[it - 3] + vy * qh[it - 3] }
    }

    /** Points (AU) along the hyperbola, out to `outToAu` on either side (as trajectory.iso_path). */
    fun path(outToAu: Double = 12.0, n: Int = 160): List<DoubleArray> {
        val nuMax = acos(min(1.0, (q * (1 + e) / outToAu - 1) / e))
        return List(n + 1) { i ->
            val nu = -nuMax + 2 * nuMax * i / n
            val r = q * (1 + e) / (1 + e * cos(nu))
            DoubleArray(3) { k -> r * (cos(nu) * p[k] + sin(nu) * qh[k]) }
        }
    }

    companion object {
        /** The block's intercept mission, as trajectory.intercept_problem. */
        fun build(prevHash: String, start: Int, rules: JSONObject, muSun: Double, auPerDayToKms: Double): JSONObject {
            val r = rules.getJSONObject("intercept")
            val d = java.security.MessageDigest.getInstance("SHA-256").digest(bytesOfHex(prevHash) + "iso".toByteArray())
            val u = DoubleArray(6) { i ->
                var v = 0L
                for (k in 0 until 4) v = (v shl 8) or (d[4 * i + k].toLong() and 0xff)
                v / 4294967296.0
            }
            val vr = r.getJSONArray("vinf_kms"); val qr = r.getJSONArray("q_au"); val pr = r.getJSONArray("peri_after_days")
            val vinf = vr.getDouble(0) + (vr.getDouble(1) - vr.getDouble(0)) * u[0]
            val q = qr.getDouble(0) + (qr.getDouble(1) - qr.getDouble(0)) * u[1]
            val z = 2 * u[2] - 1; val lon = 2 * PI * u[3]
            val xy = sqrt(max(0.0, 1 - z * z))
            val s = doubleArrayOf(xy * cos(lon), xy * sin(lon), z)
            val ref = if (abs(z) < 0.9) doubleArrayOf(0.0, 0.0, 1.0) else doubleArrayOf(1.0, 0.0, 0.0)
            val e1 = unit(cross(s, ref))
            val e2 = cross(s, e1)
            val psi = 2 * PI * u[4]
            val nh = DoubleArray(3) { e1[it] * cos(psi) + e2[it] * sin(psi) }
            val vau = vinf / auPerDayToKms
            val e = 1 + q * vau * vau / muSun
            val ca = 1 / e; val sa = sqrt(e * e - 1) / e
            val ns = cross(nh, s)
            val ph = DoubleArray(3) { s[it] * ca - ns[it] * sa }
            val qh = cross(nh, ph)
            val tPeri = start + pr.getInt(0) + (u[5] * (pr.getInt(1) - pr.getInt(0) + 1)).toInt()
            val launchAfter = r.getInt("launch_after")
            fun arr(v: DoubleArray) = org.json.JSONArray().also { a -> v.forEach { a.put(it) } }
            return JSONObject().put("type", "intercept").put("time_penalty_mps_per_year", r.getInt("time_penalty"))
                .put("target", TrajectoryModel.ISO)
                .put("window_start", start + launchAfter).put("window_end", start + launchAfter + r.getInt("window_days"))
                .put("max_tof_days", r.getInt("max_tof_days")).put("flyby_bodies", r.getJSONArray("flyby_bodies"))
                .put("max_flybys", rules.getInt("max_flybys")).put("arrival_weight", r.getDouble("arrival_weight"))
                .put("iso", JSONObject().put("discovery_day", start).put("vinf_kms", vinf).put("q_au", q).put("e", e)
                    .put("t_peri", tPeri).put("p_hat", arr(ph)).put("q_hat", arr(qh)).put("dir_in", arr(s)))
        }

        private fun cross(a: DoubleArray, b: DoubleArray) =
            doubleArrayOf(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        private fun unit(a: DoubleArray): DoubleArray { val n = sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]); return DoubleArray(3) { a[it] / n } }
    }
}
