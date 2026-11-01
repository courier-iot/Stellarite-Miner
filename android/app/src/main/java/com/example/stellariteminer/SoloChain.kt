package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.math.BigInteger
import java.security.MessageDigest

/** Network constants for one coin (generated from the node's config.py into SoloData). */
data class CoinRules(
    val coinName: String,
    val ticker: String,
    val addressPrefix: String,
    val unitsPerCoin: Long,
    val blockReward: Long,
    val halvingInterval: Int,
    val targetBlockSeconds: Int,
    val retargetInterval: Int,
    val maxRetargetFactor: Int,
    val genesisDifficultyBits: Int,
    val genesisTimestamp: Long,
    val genesisMessage: String,
    val bonusExponent: Int,
    /** Only the first NUM/DEN of improvement counts (0 = no cap); Nebulite: 8/5 (chain.effective_target). */
    val bonusCapNum: Long = 0,
    val bonusCapDen: Long = 1,
)

/** A block's useful work: problem, scoring and how it appears in the header. */
interface UsefulRules {
    val field: String                       // "route" or "trajectory"
    val genesisValue: Any                   // [] or null
    fun headerText(value: Any): String      // the part of the header prefix after tx_root
    /** Returns (score, baseline) as whole numbers; lower score is better. Throws if invalid.
     *  [scouted]: survey stars cited as scouted (Pulsarite only). */
    fun score(prevHash: String, value: Any, scouted: List<Int> = emptyList()): Pair<Long, Long>
}

private fun sha256(b: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(b)
internal fun sha256d(b: ByteArray): ByteArray = sha256(sha256(b))
internal fun hexOf(b: ByteArray) = b.joinToString("") { "%02x".format(it.toInt() and 0xff) }
internal fun bytesOfHex(s: String) = ByteArray(s.length / 2) { s.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
private val MAX_TARGET: BigInteger = BigInteger.ONE.shiftLeft(256).subtract(BigInteger.ONE)
internal fun target64(t: BigInteger) = t.toString(16).padStart(64, '0')

/**
 * A blockchain running inside the app (solo mode). It follows the nodes'
 * consensus rules exactly (chain.py), so a solo chain can later be pushed to a
 * real node with POST /chain/import and be accepted. Solo chains hold mined
 * blocks only (no transactions): to send coins, push the chain to a node first.
 */
class SoloChain(private val file: File, val rules: CoinRules, val useful: UsefulRules) {
    val blocks = ArrayList<JSONObject>()

    init {
        if (file.exists()) {
            try {
                val arr = JSONArray(file.readText())
                for (i in 0 until arr.length()) blocks += arr.getJSONObject(i)
                if (blocks.isEmpty() || blocks[0].getString("hash") != genesis().getString("hash")) {
                    blocks.clear()   // different rules or a damaged file: start over (the old file is kept)
                    file.renameTo(File(file.path + ".old"))
                }
            } catch (e: Exception) {
                blocks.clear()
                file.renameTo(File(file.path + ".bad"))
            }
        }
        if (blocks.isEmpty()) blocks += genesis()
    }

    val tip: JSONObject @Synchronized get() = blocks.last()
    val height: Long @Synchronized get() = tip.getLong("height")

    // ---- block format (identical to chain.py) -------------------------

    /** The coinbase in canonical JSON (keys sorted, as chain.py hashes it). [scouts] are paid their share. */
    private fun coinbaseJson(height: Long, to: String, amount: Long, name: String, scouts: List<Scouts.Info> = emptyList()): String {
        val nm = if (name.isEmpty()) "" else ",\"name\":\"$name\""
        val share = reward(height) * Scouts.REWARD_PCT / 100
        val rewards = if (scouts.isEmpty()) "" else
            ",\"scout_rewards\":" + scouts.joinToString(",", "[", "]") { "{\"amount\":$share,\"to\":\"${it.rewardTo}\"}" }
        return "{\"amount\":$amount,\"coinbase\":true,\"height\":$height$nm$rewards,\"to\":\"$to\"}"
    }

    private fun genesisCoinbaseJson() =
        "{\"amount\":0,\"coinbase\":true,\"height\":0,\"memo\":${pyQuote(rules.genesisMessage)},\"to\":\"genesis\"}"

    /** JSON string quoting as Python's json.dumps does it for ASCII text. */
    private fun pyQuote(s: String) = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

    private fun txRoot(canonicalTxs: List<String>): String =
        hexOf(sha256d(canonicalTxs.map { sha256d(it.toByteArray()) }.fold(ByteArray(0)) { a, b -> a + b }))

    fun headerPrefix(height: Long, prev: String, ts: Long, target: String, txRoot: String, usefulText: String): ByteArray =
        "${rules.coinName}|$height|$prev|$ts|$target|$txRoot|$usefulText|".toByteArray()

    private fun powHash(prefix: ByteArray, nonce: Long): String =
        hexOf(sha256d(prefix + ByteArray(8) { (nonce ushr (56 - 8 * it)).toByte() }))

    private fun genesis(): JSONObject {
        val cb = genesisCoinbaseJson()
        val target = target64(MAX_TARGET.shiftRight(rules.genesisDifficultyBits))
        val root = txRoot(listOf(cb))
        val prefix = headerPrefix(0, "0".repeat(64), rules.genesisTimestamp, target, root,
            useful.headerText(useful.genesisValue))
        return JSONObject()
            .put("height", 0).put("prev_hash", "0".repeat(64)).put("timestamp", rules.genesisTimestamp)
            .put("target", target).put("txs", JSONArray().put(JSONObject(cb)))
            .put(useful.field, useful.genesisValue).put("nonce", 0)
            .put("tx_root", root).put("hash", powHash(prefix, 0))
    }

    // ---- difficulty (identical to chain.next_target / median_time_past) ----

    @Synchronized fun nextTarget(): String {
        val t = tip
        val h = t.getLong("height") + 1
        if (h % rules.retargetInterval != 0L) return t.getString("target")
        val first = blocks[maxOf(1L, h - rules.retargetInterval).toInt()]
        val intervals = t.getLong("height") - first.getLong("height")
        if (intervals <= 0) return t.getString("target")
        val expected = intervals * rules.targetBlockSeconds
        var actual = t.getLong("timestamp") - first.getLong("timestamp")
        actual = maxOf(expected / rules.maxRetargetFactor, minOf(actual, expected * rules.maxRetargetFactor))
        val nt = BigInteger(t.getString("target"), 16).multiply(BigInteger.valueOf(actual)).divide(BigInteger.valueOf(expected))
        return target64(nt.min(MAX_TARGET).max(BigInteger.ONE))
    }

    @Synchronized fun medianTimePast(): Long {
        val ts = blocks.takeLast(11).map { it.getLong("timestamp") }.sorted()
        val n = ts.size
        return if (n % 2 == 1) ts[n / 2] else ((ts[n / 2 - 1] + ts[n / 2]) / 2.0).toLong()
    }

    fun reward(height: Long) = rules.blockReward shr (height / rules.halvingInterval).toInt()

    fun effectiveTarget(baseTarget: String, score: Long, baseline: Long): BigInteger {
        val k = rules.bonusExponent
        var cost = score
        if (rules.bonusCapNum > 0)      // ceil(baseline * DEN / NUM), as -(-baseline * DEN // NUM) in Python
            cost = maxOf(cost, Math.floorDiv(baseline * rules.bonusCapDen + rules.bonusCapNum - 1, rules.bonusCapNum))
        val t = BigInteger(baseTarget, 16).multiply(BigInteger.valueOf(baseline).pow(k))
            .divide(BigInteger.valueOf(maxOf(cost, 1)).pow(k))
        return t.min(MAX_TARGET).max(BigInteger.ONE)
    }

    // ---- mining ---------------------------------------------------------

    /** Everything needed to mine the next block, except the useful work and the nonce. */
    class Template(val height: Long, val prev: String, val timestamp: Long, val target: String,
                   val coinbase: String, val txRoot: String, val reward: Long,
                   val miner: String = "", val name: String = "") {
        /** Nebulite scouts cited by this block (Pulsarite solo chains; see Scouts.kt). */
        var scouts: List<Scouts.Info> = emptyList()
    }

    @Synchronized fun blocksSnapshot(): List<JSONObject> = blocks.toList()

    /** Who owns each username on this chain, replaying the coinbase claims as a node does
     *  (claiming a new name releases the address's old one). */
    @Synchronized fun nameOwners(): Map<String, String> {
        val owner = HashMap<String, String>(); val nameOf = HashMap<String, String>()
        for (b in blocks.drop(1)) {
            val cb = b.getJSONArray("txs").getJSONObject(0)
            val nm = cb.optString("name", ""); val to = cb.getString("to")
            if (nm.isEmpty() || (owner[nm] != null && owner[nm] != to)) continue
            nameOf[to]?.let { if (it != nm) owner.remove(it) }
            owner[nm] = to; nameOf[to] = nm
        }
        return owner
    }

    /** [name] (A-Z, 0-9, _; 3-16 chars) is claimed in the coinbase, as on a node. If another address
     *  already owns it on this chain, the block is mined without a claim (a node would refuse it). */
    @Synchronized fun template(miner: String, name: String = "", now: Long = System.currentTimeMillis() / 1000): Template {
        val h = height + 1
        var n = if (Regex("^[A-Z0-9_]{3,16}$").matches(name)) name else ""
        if (n.isNotEmpty() && nameOwners()[n].let { it != null && it != miner }) n = ""
        val cb = coinbaseJson(h, miner, reward(h), n)
        return Template(h, tip.getString("hash"), maxOf(now, medianTimePast() + 1), nextTarget(), cb,
            txRoot(listOf(cb)), reward(h), miner, n)
    }

    /** The same template citing [scouts]: its coinbase also pays each scout's Nebulite miner (on this coin). */
    fun withScouts(t: Template, scouts: List<Scouts.Info>): Template {
        if (scouts.isEmpty() && t.scouts.isEmpty()) return t
        val cb = coinbaseJson(t.height, t.miner, t.reward, t.name, scouts)
        return Template(t.height, t.prev, t.timestamp, t.target, cb, txRoot(listOf(cb)), t.reward, t.miner, t.name)
            .also { it.scouts = scouts }
    }

    /** The header prefix and hash target for a template with a given useful-work value. */
    fun prepare(t: Template, value: Any): Pair<ByteArray, BigInteger> {
        val (score, baseline) = useful.score(t.prev, value, t.scouts.map { it.star })
        val scoutsJson = if (t.scouts.isEmpty()) null else Scouts.proofsJson(t.scouts)
        val prefix = headerPrefix(t.height, t.prev, t.timestamp, t.target, t.txRoot,
            useful.headerText(value) + Scouts.headerPart(scoutsJson))
        val eff = effectiveTarget(t.target, score, baseline)
        for (sc in t.scouts) require(Scouts.workOk(sc, eff)) { "SCOUT_WEAK:${sc.hash}" }
        return prefix to eff
    }

    /** Adds a mined block. Returns null on success, or why it was refused. */
    @Synchronized fun submit(t: Template, value: Any, nonce: Long): String? {
        if (t.prev != tip.getString("hash")) return "stale: the chain moved on"
        val (prefix, target) = try { prepare(t, value) } catch (e: Exception) { return e.message }
        val hash = powHash(prefix, nonce)
        if (BigInteger(hash, 16) > target) return "insufficient proof of work"
        blocks += JSONObject()
            .put("height", t.height).put("prev_hash", t.prev).put("timestamp", t.timestamp)
            .put("target", t.target).put("txs", JSONArray().put(JSONObject(t.coinbase)))
            .put(useful.field, value).put("nonce", nonce).put("tx_root", t.txRoot).put("hash", hash)
            .also { if (t.scouts.isNotEmpty()) it.put("scouts", Scouts.proofsJson(t.scouts)) }
        save()
        return null
    }

    // ---- queries --------------------------------------------------------

    @Synchronized fun balance(address: String): Long = blocks.sumOf { b ->
        val cb = b.getJSONArray("txs").getJSONObject(0)
        var sum = if (cb.optString("to") == address) cb.getLong("amount") else 0L
        cb.optJSONArray("scout_rewards")?.let { r ->           // shares paid to scouts' miners
            for (i in 0 until r.length()) if (r.getJSONObject(i).optString("to") == address) sum += r.getJSONObject(i).getLong("amount")
        }
        sum
    }

    @Synchronized fun toJson(): String = JSONArray().also { a -> blocks.forEach { a.put(it) } }.toString()

    @Synchronized fun reset() { blocks.clear(); blocks += genesis(); save() }

    private fun save() {
        val tmp = File(file.path + ".tmp")
        tmp.writeText(toJson())
        tmp.renameTo(file)
    }
}

// ---- Pulsarite: star routes (same as node/stars.py) ---------------------

class StarRouteRules : UsefulRules {
    override val field = "route"
    override val genesisValue: Any = JSONArray()
    /** "id:speed,id:speed,..." as in chain.header_prefix. */
    override fun headerText(value: Any) = (value as JSONArray).let { a ->
        (0 until a.length()).joinToString(",") { a.getJSONArray(it).let { p -> "${p.getInt(0)}:${p.getInt(1)}" } }
    }

    private val n get() = SoloData.STAR_NAMES.size

    fun problem(prevHash: String): List<Int> {
        val pool = (0 until n).toMutableList()
        val chosen = ArrayList<Int>()
        val seed = bytesOfHex(prevHash)
        var i = 0
        while (chosen.size < SoloData.STARS_PER_PROBLEM) {
            val d = sha256(seed + "stars".toByteArray() + byteArrayOf((i ushr 24).toByte(), (i ushr 16).toByte(), (i ushr 8).toByte(), i.toByte()))
            val r = BigInteger(1, d).mod(BigInteger.valueOf(pool.size.toLong())).toInt()
            chosen += pool.removeAt(r)
            i++
        }
        return chosen.sorted()
    }

    /** The block's survey stars (same as stars.stops): where the probe must come to rest. */
    fun stops(prevHash: String): List<Int> {
        val pool = problem(prevHash).toMutableList()
        val chosen = ArrayList<Int>()
        val seed = bytesOfHex(prevHash)
        var i = 0
        while (chosen.size < SoloData.SURVEY_STOPS) {
            // planet hosts are likelier stops: weight 1 + STOP_WEIGHT_PER_PLANET x planets (as stars.stops)
            val weights = pool.map { 1L + SoloData.STOP_WEIGHT_PER_PLANET * SoloData.STAR_PLANETS[it] }
            val d = sha256(seed + "stops".toByteArray() + byteArrayOf((i ushr 24).toByte(), (i ushr 16).toByte(), (i ushr 8).toByte(), i.toByte()))
            var r = BigInteger(1, d).mod(BigInteger.valueOf(weights.sum())).toLong()
            var k = 0
            while (r >= weights[k]) { r -= weights[k]; k++ }
            chosen += pool.removeAt(k)
            i++
        }
        return chosen.sorted()
    }

    /** A route plan: catalog star ids and each leg's cruise speed (% of c). */
    class Plan(val ids: List<Int>, val speeds: List<Int>) {
        fun toJson() = JSONArray().also { a -> ids.indices.forEach { a.put(JSONArray().put(ids[it]).put(speeds[it])) } }
        companion object {
            fun fromJson(a: JSONArray): Plan {
                val pairs = (0 until a.length()).map { a.getJSONArray(it) }
                require(pairs.all { it.length() == 2 }) { "route must be [star id, cruise speed] pairs" }
                return Plan(pairs.map { it.getInt(0) }, pairs.map { it.getInt(1) })
            }
        }
    }

    private fun field(plan: Plan, stops: List<Int>) = StarField.fromCatalog(plan.ids, stops)
    private fun local(plan: Plan) = IntArray(plan.ids.size) { it }

    /** Mission time (milli-years) of a plan. */
    fun time(plan: Plan, stops: List<Int>): Long = field(plan, stops).time(local(plan), plan.speeds.toIntArray())

    /** Fuel used: total speed change in uly/yr. */
    fun dv(plan: Plan, stops: List<Int>): Long = field(plan, stops).dv(local(plan), plan.speeds.toIntArray())

    /** Distance flown (mly). */
    fun length(plan: Plan, stops: List<Int>): Long = field(plan, stops).length(local(plan), plan.speeds.toIntArray())

    /** The greedy baseline plan for a set of stars. */
    fun baseline(stars: List<Int>, stops: List<Int>): Plan {
        val f = StarField.fromCatalog(stars.sorted(), stops)
        val (order, speeds) = f.baseline()
        return Plan(order.map { f.ids[it] }, speeds.toList())
    }

    private val baselineCache = object : LinkedHashMap<String, Long>(64, 0.75f, true) {
        override fun removeEldestEntry(e: MutableMap.MutableEntry<String, Long>?) = size > 64
    }

    fun baselineTime(prevHash: String): Long = synchronized(baselineCache) {
        baselineCache.getOrPut(prevHash) { val st = stops(prevHash); time(baseline(problem(prevHash), st), st) }
    }

    override fun score(prevHash: String, value: Any, scouted: List<Int>): Pair<Long, Long> {
        val plan = Plan.fromJson(value as JSONArray)
        val prob = problem(prevHash)
        require(plan.ids.sorted() == prob && plan.speeds.all { it in 1..StarField.MAX_PCT }) {
            "route must visit each of the block's stars exactly once, as [star id, cruise speed 1-10] pairs"
        }
        val all = stops(prevHash)
        val st = all.filter { it !in scouted }                  // scouted stops are flown past
        require(dv(plan, st) <= SoloData.DV_BUDGET_PCT_C * SoloData.PROBE_SPEED * 100) { "route needs more fuel than the probe carries" }
        var length = time(plan, st)
        if (st.size < all.size) {    // scouts shorten the scored time by at most 2% (as chain.route_score)
            val unscouted = time(plan, all)
            length = maxOf(length, Math.floorDiv(unscouted * Scouts.TIME_CAP_DEN + Scouts.TIME_CAP_NUM - 1, Scouts.TIME_CAP_NUM))
        }
        return length to baselineTime(prevHash)
    }
}

// ---- Nebulite: trajectories (same as nebulite/trajectory.py) ------------

class TrajectoryRules : UsefulRules {
    override val field = "trajectory"
    override val genesisValue: Any = JSONObject.NULL
    override fun headerText(value: Any): String {
        if (value == JSONObject.NULL) return ""
        val o = value as JSONObject
        val seq = o.getJSONArray("seq"); val days = o.getJSONArray("days")
        val esc = o.optJSONObject("escape")
        val extra = if (esc == null) "" else
            "#" + esc.keys().asSequence().sorted().joinToString(",") { "$it=${esc.getInt(it)}" }
        return (0 until seq.length()).joinToString(",") { seq.getInt(it).toString() } + "@" +
            (0 until days.length()).joinToString(",") { days.getInt(it).toString() } + extra +
            "$" + o.getLong("cost") + "$" + o.getLong("baseline")
    }

    private val rulesJson = JSONObject(SoloData.NEBULITE_MISSION_RULES_JSON)
    private val baselineCache = LinkedHashMap<String, Pair<Double, Pair<IntArray, IntArray>>>()

    private val missionCache = object : LinkedHashMap<String, String>(32, 0.75f, true) {
        override fun removeEldestEntry(e: MutableMap.MutableEntry<String, String>?) = size > 32
    }
    private val escapeGridCache = HashMap<String, Pair<EscapePlan, Double>>()

    /** This block's mission (same as trajectory.problem): out of 8 blocks, 2 escapes toward a star,
     *  1 heliopause run, 1 interstellar-object intercept (each only if a path is known to exist) and
     *  otherwise a planet mission. */
    fun mission(prevHash: String): JSONObject = synchronized(missionCache) {
        missionCache[prevHash]?.let { return JSONObject(it) }
        val m = computeMission(prevHash)
        missionCache[prevHash] = m.toString()
        m
    }

    private fun computeMission(prevHash: String): JSONObject {
        val h = BigInteger(1, sha256(bytesOfHex(prevHash) + "mission".toByteArray()))
        val targets = rulesJson.getJSONArray("targets")
        val target = targets.getInt(h.mod(BigInteger.valueOf(targets.length().toLong())).toInt())
        val start = rulesJson.getInt("window_start_min") +
            h.shiftRight(8).mod(BigInteger.valueOf(rulesJson.getLong("window_start_spread"))).toInt()
        val kinds = rulesJson.getJSONArray("kind_draw")
        val kind = kinds.getString(EscapeMission.hashInt(prevHash, "kind").mod(BigInteger.valueOf(kinds.length().toLong())).toInt())
        if (kind == "escape" || kind == "heliopause") {
            val em = if (kind == "escape") EscapeMission.build(prevHash, start, rulesJson)
                     else EscapeMission.buildHeliopause(prevHash, start, rulesJson)
            val grid = Escape(TrajectoryModel(JSONObject(SoloData.NEBULITE_MODEL_JSON).put("mission", em)), EscapeMission(em)).grid()
            if (grid != null) {
                synchronized(escapeGridCache) { escapeGridCache[prevHash] = grid }
                return em
            }
        } else if (kind == "intercept") {
            val ph = JSONObject(SoloData.NEBULITE_MODEL_JSON).getJSONObject("physics")
            val im = IsoOrbit.build(prevHash, start, rulesJson, ph.getDouble("mu_sun"), ph.getDouble("au_per_day_to_kms"))
            val grid = interceptGrid(TrajectoryModel(JSONObject(SoloData.NEBULITE_MODEL_JSON).put("mission", im)))
            if (grid != null) {
                synchronized(baselineCache) { baselineCache[prevHash] = grid }
                return im
            }
        }
        val flyby = JSONArray().put(1).put(2).put(3)
        for (p in intArrayOf(4, 5)) if (p < target) flyby.put(p)
        val years = rulesJson.getJSONObject("max_tof_years").getInt(target.toString())
        val draw = rulesJson.getJSONArray("mission_draw")
        val th = BigInteger(1, sha256(bytesOfHex(prevHash) + "type".toByteArray()))
        val type = draw.getString(th.mod(BigInteger.valueOf(draw.length().toLong())).toInt())
        val mt = rulesJson.getJSONObject("mission_types").getJSONObject(type)
        return JSONObject().put("type", type)
            .put("time_penalty_mps_per_year", mt.getInt("time_penalty_mps_per_year"))
            .put("target", target).put("window_start", start)
            .put("window_end", start + rulesJson.getInt("window_days"))
            .put("max_tof_days", (years * 365.25 * mt.getDouble("tof_share")).toInt()).put("flyby_bodies", flyby)
            .put("max_flybys", rulesJson.getInt("max_flybys"))
    }

    /** The physics model with this block's mission attached (for scoring and the optimiser). */
    fun model(prevHash: String): TrajectoryModel =
        TrajectoryModel(JSONObject(SoloData.NEBULITE_MODEL_JSON).put("mission", mission(prevHash)))

    /** Best direct Earth-to-object transfer, as trajectory._intercept_grid (null if none works). */
    private fun interceptGrid(m: TrajectoryModel): Pair<Double, Pair<IntArray, IntArray>>? {
        val r = rulesJson.getJSONObject("intercept")
        val nl = r.getInt("grid_launches"); val nt = r.getInt("grid_tofs"); val wd = r.getInt("window_days")
        var best: Pair<Double, Pair<IntArray, IntArray>>? = null
        for (i in 0 until nl) {
            val launch = m.windowStart + Math.rint(i * wd.toDouble() / (nl - 1)).toInt()
            for (j in 0 until nt) {
                val tof = Math.rint(60 + 1740.0 * j / (nt - 1)).toInt()
                val seq = intArrayOf(TrajectoryModel.EARTH, TrajectoryModel.ISO); val days = intArrayOf(launch, launch + tof)
                val ev = m.evaluate(seq, days) ?: continue
                if (best == null || ev.cost < best.first) best = ev.cost to (seq to days)
            }
        }
        return best
    }

    /** Best direct transfer on the same coarse grid as trajectory.baseline (Python rounding: half to even). */
    fun baseline(prevHash: String): Pair<Double, Pair<IntArray, IntArray>> = synchronized(baselineCache) {
        baselineCache[prevHash]?.let { return it }
        val m = model(prevHash)
        if (m.missionType == "intercept") {
            val b = interceptGrid(m)!!
            baselineCache[prevHash] = b
            while (baselineCache.size > 16) baselineCache.remove(baselineCache.keys.first())
            return b
        }
        val t = m.target
        val a = (1 + m.planets[t].el[0]) / 2
        val hoh = Math.PI * Math.sqrt(Math.pow(a, 3.0) / m.muSun)
        val windowDays = rulesJson.getInt("window_days")
        var best: Pair<Double, Pair<IntArray, IntArray>>? = null
        for (i in 0 until 49) {
            val launch = m.windowStart + Math.rint(i * windowDays.toDouble() / 48).toInt()
            for (j in 0 until 32) {
                val tof = Math.rint(hoh * (0.4 + 1.6 * j / 31)).toInt()
                if (tof > m.maxTofDays) continue
                val seq = intArrayOf(TrajectoryModel.EARTH, t); val days = intArrayOf(launch, launch + tof)
                val ev = m.evaluate(seq, days) ?: continue
                if (best == null || ev.cost < best.first) best = ev.cost to (seq to days)
            }
        }
        val b = best!!
        baselineCache[prevHash] = b
        while (baselineCache.size > 16) baselineCache.remove(baselineCache.keys.first())
        b
    }

    /** The escape baseline (as trajectory.escape_baseline): the best textbook plan and its days to 550 AU. */
    fun escapeBaseline(prevHash: String): Pair<EscapePlan, Double> {
        synchronized(escapeGridCache) { escapeGridCache[prevHash]?.let { return it } }
        val m = model(prevHash)
        val g = Escape(m, m.escape ?: throw IllegalStateException("not an escape mission")).grid()!!
        synchronized(escapeGridCache) {
            escapeGridCache[prevHash] = g
            while (escapeGridCache.size > 32) escapeGridCache.remove(escapeGridCache.keys.first())
        }
        return g
    }

    /** Builds an escape block's trajectory value (with claimed costs). */
    fun escapeValue(prevHash: String, plan: EscapePlan): JSONObject {
        val m = model(prevHash)
        val e = Escape(m, m.escape ?: throw IllegalArgumentException("this block's mission isn't an escape mission"))
        require(e.allowed(plan)) { "escape trajectory breaks the mission rules" }
        val ev = e.evaluate(plan) ?: throw IllegalArgumentException("escape trajectory is not possible within the limits")
        return JSONObject().put("seq", JSONArray(plan.seq.toList())).put("days", JSONArray(plan.days.toList()))
            .put("cost", Math.rint(ev.cost).toLong()).put("baseline", Math.rint(escapeBaseline(prevHash).second).toLong())
            .put("escape", plan.escapeJson())
    }

    /** Builds the block's trajectory value (with claimed costs) for a planned mission. */
    fun value(prevHash: String, seq: IntArray, days: IntArray): JSONObject {
        val m = model(prevHash)
        require(m.allowed(seq, days)) { "trajectory breaks the mission rules" }
        val ev = m.evaluate(seq, days) ?: throw IllegalArgumentException("trajectory is not physically possible")
        return JSONObject().put("seq", JSONArray(seq.toList())).put("days", JSONArray(days.toList()))
            .put("cost", Math.rint(ev.cost).toLong()).put("baseline", Math.rint(baseline(prevHash).first).toLong())
    }

    override fun score(prevHash: String, value: Any, scouted: List<Int>): Pair<Long, Long> {
        val o = value as JSONObject
        return o.getLong("cost") to o.getLong("baseline")
    }
}
