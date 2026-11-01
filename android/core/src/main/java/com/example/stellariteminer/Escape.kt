package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.acosh
import kotlin.math.atan
import kotlin.math.atanh
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sinh
import kotlin.math.sqrt
import kotlin.math.tan

/**
 * Nebulite escape missions: leave the solar system on a hyperbola aimed exactly at a
 * Pulsarite star, as fast as the launch and fuel limits allow, scored by the days from
 * launch until the craft passes 550 AU. An exact port of the escape section of
 * nebulite/trajectory.py; see that file for the full explanation.
 */
class EscapeMission(m: JSONObject) {
    val starId: Int
    val starName: String
    val starPlanets: Int
    val starDistanceLy: Double
    val dir: DoubleArray
    val windowStart = m.getInt("window_start")
    val windowEnd = m.getInt("window_end")
    val maxCruiseDays = m.getInt("max_tof_days")
    val flybyBodies: List<Int> = m.getJSONArray("flyby_bodies").let { a -> List(a.length()) { a.getInt(it) } }
    val maxFlybys = m.getInt("max_flybys")
    val goalAu = m.getDouble("goal_au")
    val launchMax = m.getDouble("launch_vinf_max_kms")
    val burnBudget = m.getDouble("burn_budget_kms")
    val minPerihelion = m.getDouble("min_perihelion_au")

    init {
        val s = m.getJSONObject("target_star")
        starId = s.getInt("id"); starName = s.getString("name"); starPlanets = s.optInt("planets", 0)
        starDistanceLy = s.getDouble("distance_ly")
        dir = s.getJSONArray("dir").let { a -> DoubleArray(3) { a.getDouble(it) } }
    }

    companion object {
        /** The escape mission for a block, as trajectory.escape_problem (before the solvability check). */
        fun build(prevHash: String, start: Int, rules: JSONObject): JSONObject {
            val e = rules.getJSONObject("escape")
            val stars = rules.getJSONArray("star_targets")
            val weights = LongArray(stars.length()) { 1L + e.getInt("star_weight_per_planet") * stars.getJSONObject(it).getInt("planets") }
            var r = hashInt(prevHash, "star").mod(java.math.BigInteger.valueOf(weights.sum())).toLong()
            var k = 0
            while (r >= weights[k]) { r -= weights[k]; k++ }
            val st = stars.getJSONObject(k)
            return JSONObject().put("type", "escape").put("time_penalty_mps_per_year", 0).put("target", TrajectoryModel.SUN)
                .put("target_star", JSONObject().put("id", st.getInt("id")).put("name", st.getString("name"))
                    .put("planets", st.getInt("planets")).put("distance_ly", st.getDouble("distance_ly"))
                    .put("dir", st.getJSONArray("dir")))
                .put("window_start", start).put("window_end", start + rules.getInt("window_days"))
                .put("max_tof_days", e.getInt("max_cruise_days"))
                .put("flyby_bodies", e.getJSONArray("flyby_bodies")).put("max_flybys", rules.getInt("max_flybys"))
                .put("goal_au", e.getInt("goal_au")).put("launch_vinf_max_kms", e.getDouble("launch_vinf_max_kms"))
                .put("burn_budget_kms", e.getDouble("burn_budget_kms")).put("min_perihelion_au", e.getDouble("min_perihelion_au"))
                .put("star_catalog_id", rules.getString("star_catalog_id"))
        }

        /** A heliopause run, as trajectory.heliopause_problem: an escape aimed at the heliosphere's nose,
         *  scored on reaching 120 AU. */
        fun buildHeliopause(prevHash: String, start: Int, rules: JSONObject): JSONObject {
            val h = rules.getJSONObject("heliopause")
            return build(prevHash, start, rules).put("type", "heliopause").put("goal_au", h.getInt("goal_au"))
                .put("target_star", JSONObject().put("id", -1).put("name", "Heliosphere nose").put("planets", 0)
                    .put("distance_ly", 0.0).put("dir", h.getJSONArray("dir")))
        }

        fun hashInt(prevHash: String, tag: String): java.math.BigInteger =
            java.math.BigInteger(1, java.security.MessageDigest.getInstance("SHA-256").digest(bytesOfHex(prevHash) + tag.toByteArray()))
    }
}

/** An escape plan: planet encounters, then the departure speed (and perihelion for a Sun dive). */
class EscapePlan(val seq: IntArray, val days: IntArray, val vinfMs: Int, val rpMau: Int?) {
    val dive get() = seq.last() == TrajectoryModel.SUN && seq.size > 2
    fun escapeJson(): JSONObject = JSONObject().put("vinf_ms", vinfMs).also { if (rpMau != null) it.put("rp_mau", rpMau) }
    /** As chain.trajectory_text's escape part: "#rp_mau=..,vinf_ms=.." (keys sorted). */
    fun headerPart(): String = "#" + (if (rpMau != null) "rp_mau=$rpMau," else "") + "vinf_ms=$vinfMs"
    companion object {
        fun fromJson(seq: IntArray, days: IntArray, esc: JSONObject) =
            EscapePlan(seq, days, esc.getInt("vinf_ms"), if (esc.has("rp_mau")) esc.getInt("rp_mau") else null)
    }
}

class EscapeEval(val cost: Double, val launchKms: Double, val burnsKms: Double, val vinfKms: Double,
                 val perihelionDay: Double?) {
    val auPerYear get() = vinfKms / Escape.KM_S_PER_AU_YEAR
    val years get() = cost / 365.25
}

class Escape(private val model: TrajectoryModel, val mission: EscapeMission) {
    private val mu = model.muSun
    private val k = model.kms
    private val s = mission.dir

    // ---- the orbits --------------------------------------------------------

    private fun hyperbolaTime(r: Double, e: Double, a: Double, nu: Double, goal: Double): Double? {
        if (r >= goal) return null
        var f1 = acosh(max(1.0, (1 - r / a) / e))
        if (nu < 0) f1 = -f1
        val f2 = acosh((1 - goal / a) / e)
        val n = sqrt(mu / (-a).pow(3))
        return ((e * sinh(f2) - f2) - (e * sinh(f1) - f1)) / n
    }

    /** (velocity needed at r, days to the goal) for a hyperbola from r with asymptote s at vinf (AU/day). */
    fun fromPoint(r: DoubleArray, vinf: Double, longWay: Boolean): Pair<DoubleArray, Double>? {
        val rn = norm(r)
        val rh = scale(r, 1 / rn)
        val cross = cross(r, s)
        if (norm(cross) < 1e-9 * rn) return null
        var hHat = unit(cross)
        var theta = acos(max(-1.0, min(1.0, dot(rh, s))))
        if (longWay) { hHat = scale(hHat, -1.0); theta = 2 * PI - theta }
        val v2 = vinf * vinf
        fun f(e: Double): Double {
            val nu = acos(-1 / e) - theta
            return mu * (e * e - 1) / v2 - rn * (1 + e * cos(nu))
        }
        var lo = 1e-12; var hi = 1e6
        if (f(1 + lo) >= 0 || f(1 + hi) <= 0) return null
        repeat(100) { val mid = sqrt(lo * hi); if (f(1 + mid) < 0) lo = mid else hi = mid }
        val e = 1 + sqrt(lo * hi)
        val nu = acos(-1 / e) - theta
        if (nu <= -acos(-1 / e)) return null
        val p = mu * (e * e - 1) / v2
        if (nu < 0 && p / (1 + e) < mission.minPerihelion) return null
        val c = sqrt(mu / p)
        val tHat = cross(hHat, rh)
        val v = add(scale(rh, c * e * sin(nu)), scale(tHat, c * (1 + e * cos(nu))))
        val days = hyperbolaTime(rn, e, -mu / v2, nu, mission.goalAu) ?: return null
        return v to days
    }

    private fun timeFromPerihelion(q: Double, e: Double, nu: Double): Double {
        if (abs(e - 1) < 1e-9) {
            val d = tan(nu / 2)
            return -sqrt(2 * q * q * q / mu) * (d + d * d * d / 3)
        }
        val a = q / (1 - e)
        if (e < 1) {
            val ea = 2 * atan(sqrt((1 - e) / (1 + e)) * tan(nu / 2))
            return -(ea - e * sin(ea)) / sqrt(mu / (a * a * a))
        }
        val fa = 2 * atanh(sqrt((e - 1) / (e + 1)) * tan(nu / 2))
        return -(e * sinh(fa) - fa) / sqrt(mu / (-a).pow(3))
    }

    /** A Sun dive from r: (velocity needed at r, days to perihelion, burn AU/day, days perihelion -> goal). */
    fun sunDive(r: DoubleArray, vinf: Double, rp: Double, longWay: Boolean): DoubleArray? {
        val rn = norm(r)
        val rh = scale(r, 1 / rn)
        val cross = cross(r, s)
        if (norm(cross) < 1e-9 * rn || rn <= rp) return null
        var hHat = unit(cross)
        var theta = acos(max(-1.0, min(1.0, dot(rh, s))))
        if (longWay) { hHat = scale(hHat, -1.0); theta = 2 * PI - theta }
        val eOut = 1 + rp * vinf * vinf / mu
        val sweep = theta - acos(-1 / eOut)
        if (!(sweep > 0 && sweep < PI)) return null
        val nu = -sweep
        val e = (rn - rp) / (rp - rn * cos(nu))
        if (e < 0 || 1 + e * cos(nu) <= 0) return null
        val pf = rp * (1 + e)
        val c = sqrt(mu / pf)
        val tHat = cross(hHat, rh)
        val v = add(scale(rh, c * e * sin(nu)), scale(tHat, c * (1 + e * cos(nu))))
        val burn = sqrt(vinf * vinf + 2 * mu / rp) - c * (1 + e)
        val fall = timeFromPerihelion(rp, e, nu)
        val out = hyperbolaTime(rp, eOut, -mu / (vinf * vinf), 0.0, mission.goalAu) ?: return null
        return doubleArrayOf(v[0], v[1], v[2], fall, abs(burn), out)
    }

    // ---- rules and scoring (as trajectory.escape_check / escape_evaluate) ----

    fun allowed(p: EscapePlan): Boolean {
        val seq = p.seq; val days = p.days
        if (seq.isEmpty() || seq.size > mission.maxFlybys + 2 || seq[0] != TrajectoryModel.EARTH) return false
        for (i in 1 until seq.size) if (seq[i] != TrajectoryModel.SUN && seq[i] !in mission.flybyBodies) return false
        for (i in 0 until seq.size - 1) if (seq[i] == TrajectoryModel.SUN) return false
        if (seq.last() == TrajectoryModel.SUN && !p.dive) return false
        if (days.size != seq.size - (if (p.dive) 1 else 0)) return false
        if ((p.rpMau != null) != p.dive) return false
        if (p.vinfMs < 100 || p.vinfMs > 200_000) return false
        if (p.dive && (p.rpMau!! < Math.round(mission.minPerihelion * 1000).toInt() || p.rpMau > 1000)) return false
        if (days[0] < mission.windowStart || days[0] > mission.windowEnd) return false
        return days.last() - days[0] <= mission.maxCruiseDays
    }

    fun evaluate(p: EscapePlan): EscapeEval? {
        val vinf = p.vinfMs / 1000.0 / k
        val dive = p.dive
        val planets = if (dive) p.seq.copyOfRange(0, p.seq.size - 1) else p.seq
        val days = p.days
        val st = Array(planets.size) { model.state(planets[it], days[it].toDouble()) }
        val legs = ArrayList<DoubleArray>()
        for (i in 0 until planets.size - 1) {
            val tof = (days[i + 1] - days[i]).toDouble()
            if (tof < model.minLegDays) return null
            legs += model.lambert(pos(st[i]), pos(st[i + 1]), tof, mission.minPerihelion) ?: return null
        }
        var burns = 0.0
        for (i in 1 until planets.size - 1) {
            val vin = rel(legs[i - 1], 3, st[i]); val vout = rel(legs[i], 0, st[i])
            if (norm(vin) < model.minFlybyVinf) return null
            burns += model.flybyDv(planets[i], vin, vout)
        }
        // leave from the last planet (or Earth): both ways round, keep the least fuel (or smallest launch)
        var best: DoubleArray? = null   // key, launch vx, vy, vz, last burns, extra days, to goal
        for (longWay in booleanArrayOf(false, true)) {
            val last = st.last()
            val vNeed: DoubleArray; val extra: Double; val periBurn: Double; val toGoal: Double
            if (dive) {
                val o = sunDive(pos(last), vinf, p.rpMau!! / 1000.0, longWay) ?: continue
                vNeed = doubleArrayOf(o[0], o[1], o[2]); extra = o[3]; periBurn = o[4] * k; toGoal = o[5]
            } else {
                val o = fromPoint(pos(last), vinf, longWay) ?: continue
                vNeed = o.first; extra = 0.0; periBurn = 0.0; toGoal = o.second
            }
            val launchV: DoubleArray; val lastBurns: Double; val key: Double
            if (planets.size == 1) {
                launchV = vNeed; lastBurns = 0.0
                key = norm(doubleArrayOf(vNeed[0] - last[3], vNeed[1] - last[4], vNeed[2] - last[5]))
            } else {
                val vin = rel(legs.last(), 3, last)
                if (norm(vin) < model.minFlybyVinf) continue
                launchV = doubleArrayOf(legs[0][0], legs[0][1], legs[0][2])
                val vout = doubleArrayOf((vNeed[0] - last[3]) * k, (vNeed[1] - last[4]) * k, (vNeed[2] - last[5]) * k)
                lastBurns = model.flybyDv(planets.last(), vin, vout) + (if (dive) periBurn else 0.0)
                key = lastBurns
            }
            if (best == null || key < best[0])
                best = doubleArrayOf(key, launchV[0], launchV[1], launchV[2], lastBurns, extra, toGoal)
        }
        val b = best ?: return null
        burns += b[4]
        val launch = norm(doubleArrayOf(b[1] - st[0][3], b[2] - st[0][4], b[3] - st[0][5])) * k
        if (launch > mission.launchMax || burns > mission.burnBudget) return null
        val total = days.last() - days[0] + b[5] + b[6]
        return EscapeEval(total, launch, burns, p.vinfMs / 1000.0, if (dive) days.last() + b[5] else null)
    }

    /** Days from launch to the goal, or +infinity if the plan breaks a rule or a limit. */
    fun cost(p: EscapePlan): Double = if (allowed(p)) evaluate(p)?.cost ?: Double.POSITIVE_INFINITY else Double.POSITIVE_INFINITY

    // ---- the baseline (as trajectory._escape_grid) ----------------------------

    private fun maxVinf(seq: IntArray, days: IntArray, rp: Int?, lo0: Int = 1000, hi0: Int = 80_000): Int? {
        var lo = lo0; var hi = hi0
        if (evaluate(EscapePlan(seq, days, lo, rp)) == null) return null
        repeat(17) {
            if (hi - lo <= 1) return@repeat
            val mid = (lo + hi) / 2
            if (evaluate(EscapePlan(seq, days, mid, rp)) == null) hi = mid else lo = mid
        }
        return lo
    }

    /** The best textbook escape on the coarse grid, or null if none works (then the block isn't an escape block). */
    fun grid(): Pair<EscapePlan, Double>? {
        val ws = mission.windowStart
        val a = (1 + model.planets[4].el[0]) / 2
        val hj = PI * sqrt(a * a * a / mu)
        val rp = Math.round(mission.minPerihelion * 1000).toInt()
        var best: Pair<EscapePlan, Double>? = null
        fun consider(seq: IntArray, days: IntArray, rpm: Int?) {
            val v = maxVinf(seq, days, rpm) ?: return
            val plan = EscapePlan(seq, days, v, rpm)
            val ev = evaluate(plan) ?: return
            if (best == null || ev.cost < best!!.second) best = plan to ev.cost
        }
        val e = TrajectoryModel.EARTH; val j = 4; val sun = TrajectoryModel.SUN
        for (i in 0 until 13) consider(intArrayOf(e), intArrayOf(ws + Math.rint(i * 1461.0 / 12).toInt()), null)
        for (i in 0 until 13) {
            val launch = ws + Math.rint(i * 1461.0 / 12).toInt()
            for (jj in 0 until 9) {
                val dj = launch + Math.rint(hj * (0.4 + 0.15 * jj)).toInt()
                consider(intArrayOf(e, j), intArrayOf(launch, dj), null)
                for (rpm in intArrayOf(rp, 2 * rp)) consider(intArrayOf(e, j, sun), intArrayOf(launch, dj), rpm)
            }
        }
        return best
    }

    // ---- drawing (as trajectory.escape_path) -------------------------------

    fun path(p: EscapePlan, outToAu: Double = 40.0): List<DoubleArray> {
        val vinf = p.vinfMs / 1000.0 / k
        val planets = if (p.dive) p.seq.copyOfRange(0, p.seq.size - 1) else p.seq
        val pts = ArrayList<DoubleArray>()
        if (planets.size > 1) pts += model.samplePath(planets, p.days, 40)
        val last = model.state(planets.last(), p.days.last().toDouble())
        var bestKey = Double.MAX_VALUE; var vNeed: DoubleArray? = null; var fall = 0.0
        for (longWay in booleanArrayOf(false, true)) {
            val o: DoubleArray = if (p.dive) sunDive(pos(last), vinf, p.rpMau!! / 1000.0, longWay) ?: continue
                else fromPoint(pos(last), vinf, longWay)?.let { doubleArrayOf(it.first[0], it.first[1], it.first[2], 0.0) } ?: continue
            val key = norm(doubleArrayOf(o[0] - last[3], o[1] - last[4], o[2] - last[5]))
            if (key < bestKey) { bestKey = key; vNeed = doubleArrayOf(o[0], o[1], o[2]); fall = o[3] }
        }
        val v0 = vNeed ?: return pts
        var st = doubleArrayOf(last[0], last[1], last[2], v0[0], v0[1], v0[2])
        var burned = !p.dive
        val vAfter = if (p.dive) sqrt(vinf * vinf + 2 * mu / (p.rpMau!! / 1000.0)) else 0.0
        pts += doubleArrayOf(st[0], st[1], st[2])
        var t = 0.0; var next = 0.0
        for (step in 0 until 200_000) {
            val rn = sqrt(st[0] * st[0] + st[1] * st[1] + st[2] * st[2])
            if (rn > outToAu) break
            var h = 0.02 * rn.pow(1.5) / sqrt(mu)
            if (!burned && t + h >= fall) h = max(fall - t, 1e-9)
            st = model.rk4(st, h); t += h
            if (!burned && t >= fall - 1e-9) {
                val sp = sqrt(st[3] * st[3] + st[4] * st[4] + st[5] * st[5])
                st = doubleArrayOf(st[0], st[1], st[2], st[3] * vAfter / sp, st[4] * vAfter / sp, st[5] * vAfter / sp)
                burned = true
            }
            if (t >= next) { pts += doubleArrayOf(st[0], st[1], st[2]); next = t + 0.1 * rn.pow(1.5) / sqrt(mu) }
        }
        pts += doubleArrayOf(st[0], st[1], st[2])
        return pts
    }

    // ---- small vector helpers ------------------------------------------------

    private fun rel(v: DoubleArray, off: Int, p: DoubleArray) =
        doubleArrayOf((v[off] - p[3]) * k, (v[off + 1] - p[4]) * k, (v[off + 2] - p[5]) * k)
    private fun pos(st: DoubleArray) = doubleArrayOf(st[0], st[1], st[2])
    private fun norm(a: DoubleArray) = sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    private fun dot(a: DoubleArray, b: DoubleArray) = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    private fun cross(a: DoubleArray, b: DoubleArray) =
        doubleArrayOf(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    private fun scale(a: DoubleArray, f: Double) = doubleArrayOf(a[0] * f, a[1] * f, a[2] * f)
    private fun add(a: DoubleArray, b: DoubleArray) = doubleArrayOf(a[0] + b[0], a[1] + b[1], a[2] + b[2])
    private fun unit(a: DoubleArray) = scale(a, 1 / norm(a))

    companion object {
        const val KM_S_PER_AU_YEAR = 149597870.7 / (365.25 * 86400)
    }
}

/**
 * Plans escape missions on the phone (port of traj_opt.optimise_escape): starts from the
 * block's baseline plan, then pattern-searches days, escape speed and perihelion across
 * flyby sequences. Keeps the best plan between calls.
 */
class EscapeOptimizer(private val esc: Escape, start: EscapePlan?) {
    private val rnd = kotlin.random.Random(System.nanoTime())
    private val m = esc.mission
    private val best = LinkedHashMap<List<Int>, Pair<IntArray, Double>>()
    private val sequences: List<IntArray> = buildList {
        add(intArrayOf(TrajectoryModel.EARTH))
        fun rec(prefix: List<Int>, k: Int) {
            for (b in m.flybyBodies) {
                val p = prefix + b
                add((listOf(TrajectoryModel.EARTH) + p).toIntArray())
                add((listOf(TrajectoryModel.EARTH) + p + TrajectoryModel.SUN).toIntArray())
                if (k + 1 < minOf(2, m.maxFlybys)) rec(p, k + 1)
            }
        }
        rec(emptyList(), 0)
    }
    private var rounds = 0
    var bestPlan: EscapePlan? = null
        private set
    var bestCost = Double.POSITIVE_INFINITY
        private set

    init {
        if (start != null) {
            val c = esc.cost(start)
            if (c.isFinite()) { bestPlan = start; bestCost = c; best[start.seq.toList()] = vars(start) to c }
        }
    }

    private fun vars(p: EscapePlan) = p.days + intArrayOf(p.vinfMs) + (if (p.rpMau != null) intArrayOf(p.rpMau) else IntArray(0))
    private fun plan(seq: IntArray, x: IntArray): EscapePlan {
        val dive = seq.last() == TrajectoryModel.SUN && seq.size > 2
        val n = seq.size - (if (dive) 1 else 0)
        return EscapePlan(seq, x.copyOfRange(0, n), x[n], if (dive) x[n + 1] else null)
    }

    private fun randomStart(seq: IntArray): EscapePlan {
        val dive = seq.last() == TrajectoryModel.SUN && seq.size > 2
        val n = seq.size - (if (dive) 1 else 0)
        val days = IntArray(n)
        days[0] = m.windowStart + rnd.nextInt(m.windowEnd - m.windowStart + 1)
        for (i in 1 until n) {
            val a = 1.0 + 4.2 * (seq[i] / 4.0).pow(2)     // rough leg times (any order of magnitude will do)
            days[i] = days[i - 1] + maxOf(20, (200 * a * (0.4 + 1.1 * rnd.nextDouble())).toInt())
        }
        return EscapePlan(seq, days, 1000 + rnd.nextInt(3001), if (dive) 50 + rnd.nextInt(251) else null)
    }

    private fun refine(seq: IntArray, start: IntArray, startCost: Double, deadline: Long): Pair<IntArray, Double> {
        var x = start; var c = startCost; var step = 256
        val nDays = plan(seq, x).days.size
        while (step >= 1 && System.currentTimeMillis() < deadline) {
            var improved = false
            for (i in x.indices) for (s in intArrayOf(step, -step)) {
                val cand = x.copyOf()
                if (i == 0) for (d in 0 until nDays) cand[d] += s else cand[i] += s
                val cc = esc.cost(plan(seq, cand))
                if (cc < c) { x = cand; c = cc; improved = true }
            }
            if (!improved) step /= 2
        }
        return x to c
    }

    /** Keep searching for up to [millis] ms. Returns true if the best plan improved. */
    fun improve(millis: Long): Boolean {
        val before = bestCost
        val deadline = System.currentTimeMillis() + millis
        bestPlan?.let { p ->     // polish the current best first
            val (x, c) = refine(p.seq, vars(p), bestCost, System.currentTimeMillis() + millis / 3)
            if (c < bestCost) { bestCost = c; bestPlan = plan(p.seq, x); best[p.seq.toList()] = x to c }
        }
        while (System.currentTimeMillis() < deadline && !Thread.currentThread().isInterrupted) {
            val pool = if (rounds < 2) sequences
                else best.entries.sortedBy { it.value.second }.take(6).map { it.key.toIntArray() }
            for (seq in pool) {
                if (System.currentTimeMillis() >= deadline) break
                var x: IntArray? = null; var c = Double.POSITIVE_INFINITY
                for (t in 0 until 200) {
                    val p = randomStart(seq)
                    val cc = esc.cost(p)
                    if (cc.isFinite()) { x = vars(p); c = cc; break }
                }
                val key = seq.toList()
                if (x == null) { best.putIfAbsent(key, IntArray(0) to Double.POSITIVE_INFINITY); continue }
                val (x2, c2) = refine(seq, x, c, deadline)
                if (c2 < (best[key]?.second ?: Double.POSITIVE_INFINITY)) best[key] = x2 to c2
                if (c2 < bestCost) { bestCost = c2; bestPlan = plan(seq, x2) }
            }
            rounds++
        }
        return bestCost < before
    }
}
