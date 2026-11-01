package com.example.stellariteminer

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Solo mode: mines against a blockchain stored on this phone instead of a node.
 * Uses the same useful-work optimisers as node mining and the same block rules,
 * so the chain can later be pushed to a computer or cloud node.
 */
class SoloBackend(private val chain: SoloChain, private val address: String) : PoolBackend {
    override val unitName = "blocks"

    private class Extra(val template: SoloChain.Template, val value: Any)

    private var problemKey = ""
    private var routeOpt: RouteOptimizer? = null
    private var routeIds: IntArray = IntArray(0)
    private var trajOpt: TrajectoryOptimizer? = null
    private var trajModel: TrajectoryModel? = null

    override fun getWork(): Job {
        val t = chain.template(address)
        val fresh = t.prev != problemKey
        problemKey = t.prev
        val budget = if (fresh) FIRST_MS else REFINE_MS
        val (value, work) = when (val u = chain.useful) {
            is StarRouteRules -> routeWork(u, t, fresh, budget)
            is TrajectoryRules -> trajectoryWork(u, t, fresh, budget)
            else -> error("unknown useful work")
        }
        val (prefix, target) = chain.prepare(t, value)
        return Job(
            id = "solo-${t.height}", height = t.height, prefix = prefix,
            target = NodeClient.hexToBytes(target64(target)), nonceSize = 8, littleEndian = false,
            rewardUnits = t.reward, unitsPerCoin = chain.rules.unitsPerCoin,
            extra = Extra(t, value), work = work,
        )
    }

    private fun routeWork(u: StarRouteRules, t: SoloChain.Template, fresh: Boolean, ms: Long): Pair<Any, UsefulWork> {
        if (fresh || routeOpt == null) {
            routeIds = u.problem(t.prev).toIntArray()
            routeOpt = RouteOptimizer(
                DoubleArray(routeIds.size) { SoloData.STAR_X[routeIds[it]].toDouble() },
                DoubleArray(routeIds.size) { SoloData.STAR_Y[routeIds[it]].toDouble() },
                DoubleArray(routeIds.size) { SoloData.STAR_Z[routeIds[it]].toDouble() },
            )
        }
        val opt = routeOpt!!
        opt.improve(ms)
        val route = opt.best.map { routeIds[it] }
        val length = u.length(route)
        val base = u.length(u.baseline(routeIds.toList()))
        return JSONArray(route) to RouteInfo(route, length / 1000.0, base / 1000.0,
            Math.round(10000.0 * (1 - length.toDouble() / base)) / 100.0)
    }

    private fun trajectoryWork(u: TrajectoryRules, t: SoloChain.Template, fresh: Boolean, ms: Long): Pair<Any, UsefulWork> {
        if (fresh || trajOpt == null) {
            trajModel = u.model(t.prev)
            trajOpt = TrajectoryOptimizer(trajModel!!)
        }
        val m = trajModel!!
        val opt = trajOpt!!
        opt.improve(ms)
        val (seq, days) = if (opt.bestSeq != null) opt.bestSeq!! to opt.bestDays!! else u.baseline(t.prev).second
        val value = u.value(t.prev, seq, days)
        val ev = m.evaluate(seq, days)!!
        val gain = Math.round(10000.0 * (1 - value.getLong("cost").toDouble() / value.getLong("baseline"))) / 100.0
        return value to TrajectoryInfo(seq.toList(), days.toList(), m.pathName(seq), ev.dvKms, ev.years, gain)
    }

    override fun submit(job: Job, nonce: Long): SubmitResult {
        val e = job.extra as Extra
        val err = chain.submit(e.template, e.value, nonce)
        return if (err == null) SubmitResult(true, "Block ${e.template.height} added to solo chain")
            else SubmitResult(false, err)
    }

    override fun hasNewWork() = false
    override fun close() {}

    companion object {
        private const val FIRST_MS = 2500L
        private const val REFINE_MS = 1000L

        @Volatile private var chains = HashMap<String, SoloChain>()

        /** The solo chain for a coin, loaded once per process. */
        fun chainFor(context: Context, coin: CoinProfile): SoloChain = synchronized(this) {
            chains.getOrPut(coin.id) {
                val (rules, useful) = when (coin.kind) {
                    WorkKind.STAR_ROUTES -> SoloData.PULSARITE to StarRouteRules()
                    WorkKind.TRAJECTORIES -> SoloData.NEBULITE to TrajectoryRules()
                    WorkKind.NONE -> throw IllegalArgumentException("solo mode is only for Pulsarite and Nebulite")
                }
                SoloChain(File(context.filesDir, "solo-${coin.id}.json"), rules, useful)
            }
        }

        /** Push a solo chain to a node (POST /chain/import). Returns a message for the person. */
        fun push(chain: SoloChain, nodeUrl: String): String {
            val http = NodeClient(nodeUrl)
            val (code, body) = http.request("POST", "/chain/import", null, chain.toJson())
            return when {
                code != 200 -> "node refused: ${body.optString("error", "HTTP $code")}"
                body.optBoolean("adopted") -> "pushed: the node adopted your solo chain (height ${body.optLong("height")})"
                else -> "${body.optString("reason")}. Node height ${body.optLong("height")}, yours ${chain.height}."
            }
        }

        /** Route map rows in the same shape as the node's /routes. */
        fun routeRows(chain: SoloChain, limit: Int): JSONArray {
            val u = chain.useful as StarRouteRules
            val out = JSONArray()
            for (b in chain.blocks.drop(1).takeLast(limit).reversed()) {
                val r = b.getJSONArray("route")
                val ids = List(r.length()) { r.getInt(it) }
                val len = u.length(ids); val base = u.length(u.baseline(ids))
                out.put(JSONObject().put("height", b.getLong("height")).put("route_ids", JSONArray(ids))
                    .put("length_ly", len / 1000.0).put("baseline_ly", base / 1000.0)
                    .put("improvement_pct", Math.round(10000.0 * (1 - len.toDouble() / base)) / 100.0))
            }
            return out
        }

        /** Mission log rows in the same shape as the node's /missions. */
        fun missionRows(chain: SoloChain, limit: Int): JSONArray {
            val u = chain.useful as TrajectoryRules
            val out = JSONArray()
            for (b in chain.blocks.drop(1).takeLast(limit).reversed()) {
                val tr = b.getJSONObject("trajectory")
                val seqA = tr.getJSONArray("seq"); val daysA = tr.getJSONArray("days")
                val seq = IntArray(seqA.length()) { seqA.getInt(it) }; val days = IntArray(daysA.length()) { daysA.getInt(it) }
                val m = u.model(b.getString("prev_hash"))
                val ev = m.evaluate(seq, days) ?: continue
                out.put(JSONObject().put("height", b.getLong("height"))
                    .put("path", JSONArray(seq.map { m.planets[it].name })).put("seq", JSONArray(seq.toList()))
                    .put("days", JSONArray(days.toList())).put("dv_kms", ev.dvKms).put("years", ev.years)
                    .put("improvement_pct", Math.round(10000.0 * (1 - tr.getLong("cost").toDouble() / tr.getLong("baseline"))) / 100.0))
            }
            return out
        }
    }
}
