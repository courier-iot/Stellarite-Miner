package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger

/**
 * Scouts in solo mode: a Pulsarite solo block can cite escape missions from the
 * phone's own Nebulite solo chain, exactly as node/scouts.py and node/chain.py
 * define it, so a solo chain with scouts is still accepted when pushed to a node.
 *
 * A proof is the Nebulite block's header fields, trajectory and nonce. It is checked
 * here the same way a Pulsarite node checks it: the escape physics, the claimed
 * cost and baseline, and the block's own proof of work.
 */
object Scouts {
    val PROOF_KEYS = listOf("height", "prev_hash", "timestamp", "target", "tx_root", "trajectory", "nonce")
    const val REWARD_PCT = 5                  // each cited scout's Nebulite miner earns 5% of the block reward
    const val MAX_PER_BLOCK = 4
    const val MIN_WORK_DIVISOR = 3L          // a scout carries at least 1/3 of the work the citing block needs
    const val TIME_CAP_NUM = 51L             // scouts shorten the scored time by at most 2%
    const val TIME_CAP_DEN = 50L

    class Info(val hash: String, val star: Int, val starName: String, val effectiveTarget: BigInteger,
               val vinfKms: Double, val proof: JSONObject, val miner: String, val rewardTo: String)

    /** JSON exactly as Python's json.dumps(obj, sort_keys=True, separators=(",", ":")) writes it. */
    fun canonical(v: Any?): String = when (v) {
        null, JSONObject.NULL -> "null"
        is JSONObject -> v.keys().asSequence().sorted().joinToString(",", "{", "}") { quote(it) + ":" + canonical(v.opt(it)) }
        is JSONArray -> (0 until v.length()).joinToString(",", "[", "]") { canonical(v.opt(it)) }
        is String -> quote(v)
        is Boolean -> v.toString()
        is Int, is Long -> v.toString()
        is Number -> if (v.toDouble() == Math.floor(v.toDouble()) && Math.abs(v.toDouble()) < 1e15) v.toLong().toString() else v.toString()
        else -> quote(v.toString())
    }

    private fun quote(s: String) = buildString {
        append('"')
        for (c in s) {
            when {
                c == '"' -> append("\\\"")
                c == '\\' -> append("\\\\")
                c == '\n' -> append("\\n")
                c == '\r' -> append("\\r")
                c == '\t' -> append("\\t")
                c == '\b' -> append("\\b")
                c == '\u000C' -> append("\\f")
                c < ' ' || c.code > 127 -> append("\\u%04x".format(c.code))
                else -> append(c)
            }
        }
        append('"')
    }

    fun txid(tx: JSONObject): String = hexOf(sha256d(canonical(tx).toByteArray()))

    /** The same wallet's Pulsarite address (as scouts.pulsarite_address). */
    fun pulsariteAddress(nebuliteAddress: String) = Coin.ADDRESS_PREFIX + nebuliteAddress.substring(NebuliteCoin.ADDRESS_PREFIX.length)

    private val nebuliteRules = TrajectoryRules()
    private val cache = object : LinkedHashMap<String, Info?>(64, 0.75f, true) {
        override fun removeEldestEntry(e: MutableMap.MutableEntry<String, Info?>?) = size > 256
    }

    /** A Nebulite block (as stored in a solo chain or served by /scouts) reduced to a proof. */
    fun proofOf(block: JSONObject): JSONObject = JSONObject().also { p ->
        PROOF_KEYS.forEach { p.put(it, block.opt(it)) }
        val txs = block.getJSONArray("txs")
        p.put("coinbase", txs.getJSONObject(0))                         // who mined it
        p.put("txids", JSONArray().also { a -> for (i in 0 until txs.length()) a.put(txid(txs.getJSONObject(i))) })
    }

    /** The Nebulite block hash, as nebulite/chain.block_hash. */
    fun nebuliteHash(p: JSONObject): String {
        val prefix = "${SoloData.NEBULITE.coinName}|${p.getLong("height")}|${p.getString("prev_hash")}|" +
            "${p.getLong("timestamp")}|${p.getString("target")}|${p.getString("tx_root")}|" +
            nebuliteRules.headerText(p.getJSONObject("trajectory")) + "|"
        val nonce = p.getLong("nonce")
        return hexOf(sha256d(prefix.toByteArray() + ByteArray(8) { (nonce ushr (56 - 8 * it)).toByte() }))
    }

    /** As nebulite/chain.effective_target (with its 1.6x bonus cap). */
    fun nebuliteEffectiveTarget(target: String, cost: Long, baseline: Long): BigInteger {
        val r = SoloData.NEBULITE
        val k = r.bonusExponent
        val c = maxOf(cost, Math.floorDiv(baseline * r.bonusCapDen + r.bonusCapNum - 1, r.bonusCapNum))
        val t = BigInteger(target, 16).multiply(BigInteger.valueOf(baseline).pow(k)).divide(BigInteger.valueOf(maxOf(c, 1)).pow(k))
        return t.min(BigInteger.ONE.shiftLeft(256).subtract(BigInteger.ONE)).max(BigInteger.ONE)
    }

    /** Checks a proof on its own merits (as scouts.verify); null if it isn't a valid scout. */
    fun verify(proof: JSONObject): Info? {
        val key = proof.toString()
        synchronized(cache) { if (cache.containsKey(key)) return cache[key] }
        val info = try { check(proof) } catch (e: Exception) { null }
        synchronized(cache) { cache[key] = info }
        return info
    }

    private fun check(p: JSONObject): Info? {
        if ((PROOF_KEYS + listOf("coinbase", "txids")).any { !p.has(it) }) return null
        // who mined it: the coinbase's txid comes first, and all txids reproduce the block's tx_root
        val cb = p.getJSONObject("coinbase")
        val ids = p.getJSONArray("txids")
        val to = cb.optString("to", "")
        if (cb.opt("coinbase") != true || ids.length() < 1 || !Wallet.isValidAddress(to, NebuliteCoin.ADDRESS_PREFIX)) return null
        if (txid(cb) != ids.getString(0)) return null
        val root = hexOf(sha256d((0 until ids.length()).fold(ByteArray(0)) { acc, i -> acc + bytesOfHex(ids.getString(i)) }))
        if (root != p.getString("tx_root")) return null
        val tr = p.getJSONObject("trajectory")
        val esc = tr.optJSONObject("escape") ?: return null
        val prev = p.getString("prev_hash")
        val mission = nebuliteRules.mission(prev)
        if (mission.optString("type") != "escape") return null
        val seq = tr.getJSONArray("seq").let { a -> IntArray(a.length()) { a.getInt(it) } }
        val days = tr.getJSONArray("days").let { a -> IntArray(a.length()) { a.getInt(it) } }
        val value = nebuliteRules.escapeValue(prev, EscapePlan.fromJson(seq, days, esc))   // rules + physics
        if (Math.abs(value.getLong("cost") - tr.getLong("cost")) > 1 || Math.abs(value.getLong("baseline") - tr.getLong("baseline")) > 1)
            return null
        val h = nebuliteHash(p)
        val eff = nebuliteEffectiveTarget(p.getString("target"), tr.getLong("cost"), tr.getLong("baseline"))
        if (BigInteger(h, 16) > eff) return null
        val star = mission.getJSONObject("target_star")
        return Info(h, star.getInt("id"), star.getString("name"), eff, esc.getInt("vinf_ms") / 1000.0, p, to, pulsariteAddress(to))
    }

    /** As chain.scout_work_ok. */
    fun workOk(s: Info, blockEffectiveTarget: BigInteger) =
        s.effectiveTarget <= blockEffectiveTarget.multiply(BigInteger.valueOf(MIN_WORK_DIVISOR))

    /** Nebulite block hashes already cited on a Pulsarite chain. */
    fun usedOn(pulsariteBlocks: List<JSONObject>): Set<String> = buildSet {
        for (b in pulsariteBlocks) b.optJSONArray("scouts")?.let { a ->
            for (i in 0 until a.length()) add(nebuliteHash(a.getJSONObject(i)))
        }
    }

    /** The best (most work) valid, uncited scout for each of a block's survey stops, from Nebulite blocks. */
    fun choose(stops: List<Int>, nebuliteBlocks: List<JSONObject>, used: Set<String>, exclude: Set<String>): List<Info> {
        val best = HashMap<Int, Info>()
        for (b in nebuliteBlocks.asReversed()) {
            if (b.optJSONObject("trajectory")?.has("escape") != true) continue
            val info = verify(proofOf(b)) ?: continue
            if (info.star !in stops || info.hash in used || info.hash in exclude) continue
            val cur = best[info.star]
            if (cur == null || info.effectiveTarget < cur.effectiveTarget) best[info.star] = info
        }
        return best.keys.sorted().map { best[it]!! }.take(MAX_PER_BLOCK)
    }

    fun proofsJson(scouts: List<Info>): JSONArray = JSONArray().also { a -> scouts.forEach { a.put(it.proof) } }

    /** The header part a block's scouts add, as chain.header_prefix: "|S:hash1,hash2". */
    fun headerPart(scouts: JSONArray?): String =
        if (scouts == null || scouts.length() == 0) "" else
            "|S:" + (0 until scouts.length()).joinToString(",") { nebuliteHash(scouts.getJSONObject(it)) }
}
