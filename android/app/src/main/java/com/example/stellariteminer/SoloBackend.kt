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
class SoloBackend(private val chain: SoloChain, private val address: String, private val name: String = "") : PoolBackend {
    override val unitName = "blocks"

    private class Extra(val template: SoloChain.Template, val value: Any)

    private var problemKey = ""
    private var routePlanner: MovingRoutePlanner? = null
    private var routeField: StarField? = null
    private var trajOpt: TrajectoryOptimizer? = null
    private var trajModel: TrajectoryModel? = null

    override fun getWork(): Job {
        val t = chain.template(address, name)
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
        if (fresh || routePlanner == null) {
            val f = StarField.fromCatalog(u.problem(t.prev), u.stops(t.prev))
            routeField = f
            routePlanner = MovingRoutePlanner(f)
        }
        val f = routeField!!
        val opt = routePlanner!!
        opt.improve(ms)
        val plan = StarRouteRules.Plan(opt.best.map { f.ids[it] }, opt.bestSpeeds.toList())
        val time = opt.bestTime
        val base = opt.baselineTime
        val dv = f.dv(opt.best, opt.bestSpeeds)
        return plan.toJson() to RouteInfo(plan.ids, time / 1000.0, base / 1000.0,
            Math.round(10000.0 * (1 - time.toDouble() / base)) / 100.0, f.length(opt.best, opt.bestSpeeds) / 1000.0,
            u.stops(t.prev), plan.speeds, Math.round(1000.0 * dv / f.dvBudget) / 10.0)
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
        return value to TrajectoryInfo(seq.toList(), days.toList(), m.pathName(seq), ev.dvKms, ev.years, gain, m.missionType)
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
                val plan = StarRouteRules.Plan.fromJson(b.getJSONArray("route"))
                val st = u.stops(b.getString("prev_hash"))
                val t = u.time(plan, st); val base = u.baselineTime(b.getString("prev_hash"))
                val budget = SoloData.DV_BUDGET_PCT_C * SoloData.PROBE_SPEED * 100
                out.put(JSONObject().put("height", b.getLong("height")).put("route_ids", JSONArray(plan.ids))
                    .put("speeds_pct_c", JSONArray(plan.speeds)).put("stop_ids", JSONArray(st))
                    .put("fuel_used_pct", Math.round(1000.0 * u.dv(plan, st) / budget) / 10.0)
                    .put("years", t / 1000.0).put("baseline_years", base / 1000.0)
                    .put("length_ly", u.length(plan, st) / 1000.0)
                    .put("miner_name", b.getJSONArray("txs").getJSONObject(0).optString("name", ""))
                    .put("improvement_pct", Math.round(10000.0 * (1 - t.toDouble() / base)) / 100.0))
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
                    .put("mission_type", m.missionType)
                    .put("launch_date", TrajectoryModel.dateOf(days.first())).put("arrival_date", TrajectoryModel.dateOf(days.last()))
                    .put("improvement_pct", Math.round(10000.0 * (1 - tr.getLong("cost").toDouble() / tr.getLong("baseline"))) / 100.0))
            }
            return out
        }
    }
}
