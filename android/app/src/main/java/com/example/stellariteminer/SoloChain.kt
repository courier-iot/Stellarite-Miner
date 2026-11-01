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
)

/** A block's useful work: problem, scoring and how it appears in the header. */
interface UsefulRules {
    val field: String                       // "route" or "trajectory"
    val genesisValue: Any                   // [] or null
    fun headerText(value: Any): String      // the part of the header prefix after tx_root
    /** Returns (score, baseline) as whole numbers; lower score is better. Throws if invalid. */
    fun score(prevHash: String, value: Any): Pair<Long, Long>
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

    private fun coinbaseJson(height: Long, to: String, amount: Long, name: String) =
        if (name.isEmpty()) "{\"amount\":$amount,\"coinbase\":true,\"height\":$height,\"to\":\"$to\"}"
        else "{\"amount\":$amount,\"coinbase\":true,\"height\":$height,\"name\":\"$name\",\"to\":\"$to\"}"

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
        val t = BigInteger(baseTarget, 16).multiply(BigInteger.valueOf(baseline).pow(k))
            .divide(BigInteger.valueOf(maxOf(score, 1)).pow(k))
        return t.min(MAX_TARGET).max(BigInteger.ONE)
    }

    // ---- mining ---------------------------------------------------------

    /** Everything needed to mine the next block, except the useful work and the nonce. */
    class Template(val height: Long, val prev: String, val timestamp: Long, val target: String,
                   val coinbase: String, val txRoot: String, val reward: Long)

    /** [name] (A-Z, 0-9, _; 3-16 chars) is claimed in the coinbase, as on a node. */
    @Synchronized fun template(miner: String, name: String = "", now: Long = System.currentTimeMillis() / 1000): Template {
        val h = height + 1
        val n = if (Regex("^[A-Z0-9_]{3,16}$").matches(name)) name else ""
        val cb = coinbaseJson(h, miner, reward(h), n)
        return Template(h, tip.getString("hash"), maxOf(now, medianTimePast() + 1), nextTarget(), cb,
            txRoot(listOf(cb)), reward(h))
    }

    /** The header prefix and hash target for a template with a given useful-work value. */
    fun prepare(t: Template, value: Any): Pair<ByteArray, BigInteger> {
        val (score, baseline) = useful.score(t.prev, value)
        val prefix = headerPrefix(t.height, t.prev, t.timestamp, t.target, t.txRoot, useful.headerText(value))
        return prefix to effectiveTarget(t.target, score, baseline)
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
        save()
        return null
    }

    // ---- queries --------------------------------------------------------

    @Synchronized fun balance(address: String): Long = blocks.sumOf { b ->
        val cb = b.getJSONArray("txs").getJSONObject(0)
        if (cb.optString("to") == address) cb.getLong("amount") else 0L
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
    override fun headerText(value: Any) = (value as JSONArray).let { a -> (0 until a.length()).joinToString(",") { a.getInt(it).toString() } }

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

    /** Mission time (milli-years) of a route given as catalog star ids. */
    fun time(route: List<Int>): Long {
        val f = StarField.fromCatalog(route)
        return f.time(IntArray(route.size) { it })
    }

    /** Distance flown (mly) for a route given as catalog star ids. */
    fun length(route: List<Int>): Long {
        val f = StarField.fromCatalog(route)
        return f.length(IntArray(route.size) { it })
    }

    /** The greedy baseline route (catalog star ids) for a set of stars. */
    fun baseline(stars: List<Int>): List<Int> {
        val f = StarField.fromCatalog(stars.sorted())
        return f.baseline().map { f.ids[it] }
    }

    override fun score(prevHash: String, value: Any): Pair<Long, Long> {
        val a = value as JSONArray
        val route = List(a.length()) { a.getInt(it) }
        val prob = problem(prevHash)
        require(route.sorted() == prob) { "route must visit each of the block's stars exactly once" }
        return time(route) to time(baseline(prob))
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
        return (0 until seq.length()).joinToString(",") { seq.getInt(it).toString() } + "@" +
            (0 until days.length()).joinToString(",") { days.getInt(it).toString() } +
            "$" + o.getLong("cost") + "$" + o.getLong("baseline")
    }

    private val rulesJson = JSONObject(SoloData.NEBULITE_MISSION_RULES_JSON)
    private val baselineCache = LinkedHashMap<String, Pair<Double, Pair<IntArray, IntArray>>>()

    /** This block's mission (same as trajectory.problem). */
    fun mission(prevHash: String): JSONObject {
        val h = BigInteger(1, sha256(bytesOfHex(prevHash) + "mission".toByteArray()))
        val targets = rulesJson.getJSONArray("targets")
        val target = targets.getInt(h.mod(BigInteger.valueOf(targets.length().toLong())).toInt())
        val start = rulesJson.getInt("window_start_min") +
            h.shiftRight(8).mod(BigInteger.valueOf(rulesJson.getLong("window_start_spread"))).toInt()
        val flyby = JSONArray().put(1).put(2).put(3)
        for (p in intArrayOf(4, 5)) if (p < target) flyby.put(p)
        val years = rulesJson.getJSONObject("max_tof_years").getInt(target.toString())
        return JSONObject().put("target", target).put("window_start", start)
            .put("window_end", start + rulesJson.getInt("window_days"))
            .put("max_tof_days", (years * 365.25).toInt()).put("flyby_bodies", flyby)
            .put("max_flybys", rulesJson.getInt("max_flybys"))
    }

    /** The physics model with this block's mission attached (for scoring and the optimiser). */
    fun model(prevHash: String): TrajectoryModel =
        TrajectoryModel(JSONObject(SoloData.NEBULITE_MODEL_JSON).put("mission", mission(prevHash)))

    /** Best direct transfer on the same coarse grid as trajectory.baseline (Python rounding: half to even). */
    fun baseline(prevHash: String): Pair<Double, Pair<IntArray, IntArray>> = synchronized(baselineCache) {
        baselineCache[prevHash]?.let { return it }
        val m = model(prevHash)
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

    /** Builds the block's trajectory value (with claimed costs) for a planned mission. */
    fun value(prevHash: String, seq: IntArray, days: IntArray): JSONObject {
        val m = model(prevHash)
        require(m.allowed(seq, days)) { "trajectory breaks the mission rules" }
        val ev = m.evaluate(seq, days) ?: throw IllegalArgumentException("trajectory is not physically possible")
        return JSONObject().put("seq", JSONArray(seq.toList())).put("days", JSONArray(days.toList()))
            .put("cost", Math.rint(ev.cost).toLong()).put("baseline", Math.rint(baseline(prevHash).first).toLong())
    }

    override fun score(prevHash: String, value: Any): Pair<Long, Long> {
        val o = value as JSONObject
        return o.getLong("cost") to o.getLong("baseline")
    }
}
