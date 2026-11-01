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
class SoloBackend(private val chain: SoloChain, private val address: String, private val name: String = "",
                  /** Pulsarite: blocks of the phone's own Nebulite solo chain, whose escape missions can scout routes. */
                  private val scoutSource: (() -> List<JSONObject>)? = null) : PoolBackend {
    override val unitName = "blocks"

    private class Extra(val template: SoloChain.Template, val value: Any)

    private var problemKey = ""
    private var routePlanner: MovingRoutePlanner? = null
    private var routeField: StarField? = null
    private var trajOpt: TrajectoryOptimizer? = null
    private var trajModel: TrajectoryModel? = null

    private var scouts: List<Scouts.Info> = emptyList()
    private val weakScouts = HashSet<String>()     // scouts that lacked work for our route on this block

    override fun getWork(): Job = try { buildWork() } catch (e: IllegalArgumentException) {
        // a cited scout lacks work for the route we found: drop it and plan again without it
        val m = e.message ?: ""
        if (!m.startsWith("SCOUT_WEAK:")) throw e
        weakScouts += m.removePrefix("SCOUT_WEAK:")
        routePlanner = null
        buildWork()
    }

    private fun buildWork(): Job {
        var t = chain.template(address, name)
        val fresh = t.prev != problemKey
        if (fresh) weakScouts.clear()
        problemKey = t.prev
        val budget = if (fresh) FIRST_MS else REFINE_MS
        val (value, work) = when (val u = chain.useful) {
            is StarRouteRules -> routeWork(u, t, fresh, budget)
            is TrajectoryRules -> trajectoryWork(u, t, fresh, budget)
            else -> error("unknown useful work")
        }
        if (chain.useful is StarRouteRules) t = chain.withScouts(t, scouts)    // cite the scouts and pay their miners
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
            // Nebulite escapes aimed at this block's survey stars turn those stops into flybys
            scouts = scoutSource?.let { src ->
                try { Scouts.choose(u.stops(t.prev), src(), Scouts.usedOn(chain.blocksSnapshot()), weakScouts) }
                catch (e: Exception) { emptyList() }
            } ?: emptyList()
            val scouted = scouts.map { it.star }
            val f = StarField.fromCatalog(u.problem(t.prev), u.stops(t.prev).filter { it !in scouted })
            routeField = f
            routePlanner = MovingRoutePlanner(f)
        }
        val f = routeField!!
        val opt = routePlanner!!
        opt.improve(ms)
        val plan = StarRouteRules.Plan(opt.best.map { f.ids[it] }, opt.bestSpeeds.toList())
        val time = opt.bestTime
        val base = u.baselineTime(t.prev)          // the block's baseline (all stops), as the node uses
        val dv = f.dv(opt.best, opt.bestSpeeds)
        val scouted = scouts.map { it.star }
        return plan.toJson() to RouteInfo(plan.ids, time / 1000.0, base / 1000.0,
            Math.round(10000.0 * (1 - time.toDouble() / base)) / 100.0, f.length(opt.best, opt.bestSpeeds) / 1000.0,
            u.stops(t.prev).filter { it !in scouted }, plan.speeds, Math.round(1000.0 * dv / f.dvBudget) / 10.0, scouted)
    }

    private var escOpt: EscapeOptimizer? = null

    private fun trajectoryWork(u: TrajectoryRules, t: SoloChain.Template, fresh: Boolean, ms: Long): Pair<Any, UsefulWork> {
        val mission = u.mission(t.prev)
        if (mission.optString("type") == "escape" || mission.optString("type") == "heliopause") {
            if (fresh || escOpt == null) {
                trajModel = u.model(t.prev)
                escOpt = EscapeOptimizer(Escape(trajModel!!, trajModel!!.escape!!), u.escapeBaseline(t.prev).first)
            }
            val m = trajModel!!
            val opt = escOpt!!
            opt.improve(ms)
            val plan = opt.bestPlan ?: u.escapeBaseline(t.prev).first
            val value = u.escapeValue(t.prev, plan)
            val ev = Escape(m, m.escape!!).evaluate(plan)!!
            val gain = Math.round(10000.0 * (1 - value.getLong("cost").toDouble() / value.getLong("baseline"))) / 100.0
            return value to TrajectoryInfo(plan.seq.toList(), plan.days.toList(), m.pathName(plan.seq),
                ev.launchKms + ev.burnsKms, ev.years, gain, m.missionType, plan.escapeJson(), m.escape!!.starName, ev.vinfKms)
        }
        if (fresh || trajOpt == null) {
            trajModel = u.model(t.prev)
            trajOpt = TrajectoryOptimizer(trajModel!!, u.baseline(t.prev).second)
        }
        val m = trajModel!!
        val opt = trajOpt!!
        opt.improve(ms)
        val (seq, days) = if (opt.bestSeq != null) opt.bestSeq!! to opt.bestDays!! else u.baseline(t.prev).second
        val value = u.value(t.prev, seq, days)
        val ev = m.evaluate(seq, days)!!
        val gain = Math.round(10000.0 * (1 - value.getLong("cost").toDouble() / value.getLong("baseline"))) / 100.0
        if (m.missionType == "intercept")      // a flyby: the burns, and the encounter speed on its own
            return value to TrajectoryInfo(seq.toList(), days.toList(), m.pathName(seq), ev.launchKms + ev.flybyKms,
                ev.years, gain, m.missionType, encounterKms = ev.arrivalKms, iso = mission.optJSONObject("iso"))
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

        /** Deletes a coin's solo chain from this phone (and from memory). Mining for it must be stopped first. */
        fun delete(context: Context, coin: CoinProfile) = synchronized(this) {
            chains.remove(coin.id)
            File(context.filesDir, "solo-${coin.id}.json").delete()
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
                val cited = b.optJSONArray("scouts")?.let { a -> (0 until a.length()).mapNotNull { Scouts.verify(a.getJSONObject(it)) } } ?: emptyList()
                val st = u.stops(b.getString("prev_hash")).filter { s -> cited.none { it.star == s } }
                val t = u.time(plan, st); val base = u.baselineTime(b.getString("prev_hash"))
                val budget = SoloData.DV_BUDGET_PCT_C * SoloData.PROBE_SPEED * 100
                out.put(JSONObject().put("height", b.getLong("height")).put("route_ids", JSONArray(plan.ids))
                    .put("speeds_pct_c", JSONArray(plan.speeds)).put("stop_ids", JSONArray(st))
                    .put("scouted_ids", JSONArray(cited.map { it.star })).put("scouted", JSONArray(cited.map { it.starName }))
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
                val gain = Math.round(10000.0 * (1 - tr.getLong("cost").toDouble() / tr.getLong("baseline"))) / 100.0
                val em = m.escape
                if (em != null) {
                    val plan = EscapePlan.fromJson(seq, days, tr.getJSONObject("escape"))
                    val ev = Escape(m, em).evaluate(plan) ?: continue
                    out.put(JSONObject().put("height", b.getLong("height")).put("mission_type", m.missionType)
                        .put("goal_au", em.goalAu.toInt())
                        .put("target_star", em.starName).put("target_star_id", em.starId)
                        .put("star_dir", JSONArray(em.dir.toList()))
                        .put("path", JSONArray(seq.map { if (it == TrajectoryModel.SUN) "Sun" else m.planets[it].name } + "${em.goalAu.toInt()} AU"))
                        .put("seq", JSONArray(seq.toList())).put("days", JSONArray(days.toList()))
                        .put("escape", tr.getJSONObject("escape"))
                        .put("dv_kms", ev.launchKms + ev.burnsKms).put("vinf_kms", ev.vinfKms).put("au_per_year", ev.auPerYear)
                        .put("years", ev.years).put("launch_date", TrajectoryModel.dateOf(days.first()))
                        .put("arrival_date", TrajectoryModel.dateOf(days.first() + ev.cost)).put("improvement_pct", gain))
                    continue
                }
                val ev = m.evaluate(seq, days) ?: continue
                val row = JSONObject()
                if (m.missionType == "intercept") {
                    val iso = m.iso!!
                    row.put("iso", u.mission(b.getString("prev_hash")).getJSONObject("iso")).put("encounter_kms", ev.arrivalKms).put("iso_vinf_kms", iso.vinfKms).put("iso_q_au", iso.q)
                        .put("iso_perihelion_date", TrajectoryModel.dateOf(iso.tPeri))
                }
                out.put(row.put("height", b.getLong("height"))
                    .put("path", JSONArray(seq.map { if (it == TrajectoryModel.ISO) "Interstellar object" else m.planets[it].name }))
                    .put("seq", JSONArray(seq.toList()))
                    .put("days", JSONArray(days.toList()))
                    .put("dv_kms", if (m.missionType == "intercept") ev.launchKms + ev.flybyKms else ev.dvKms).put("years", ev.years)
                    .put("mission_type", m.missionType)
                    .put("launch_date", TrajectoryModel.dateOf(days.first())).put("arrival_date", TrajectoryModel.dateOf(days.last()))
                    .put("improvement_pct", Math.round(10000.0 * (1 - tr.getLong("cost").toDouble() / tr.getLong("baseline"))) / 100.0))
            }
            return out
        }
    }
}
