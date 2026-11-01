package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.URLEncoder

/**
 * Talks to a Nebulite node. Blocking calls: run off the main thread.
 *
 * Mining a Nebulite block has two halves:
 *  1. useful work: plan a cheap spacecraft trajectory for the block's mission
 *     (TrajectoryOptimizer); the node turns it into a header and a target,
 *     easier for cheaper trajectories
 *  2. hashing: search nonces against that target (MiningEngine)
 * Each refresh for the same block keeps improving the plan it already has.
 */
class NebuliteClient(baseUrl: String, private val address: String, private val name: String = "") : PoolBackend {
    override val unitName = "blocks"
    private val http = NodeClient(baseUrl)

    private var missionKey = ""
    private var model: TrajectoryModel? = null
    private var optimizer: TrajectoryOptimizer? = null
    private var escOpt: EscapeOptimizer? = null

    fun info(): JSONObject = http.info()

    override fun getWork(): Job {
        val (code, work) = http.request("GET", NodeClient.workPath(address, name), null)
        if (code != 200) throw IOException(work.optString("error", "HTTP $code"))
        val jobId = work.getString("job_id")

        // 1. Useful work: plan this block's mission.
        val key = work.getJSONObject("mission").toString()
        if (work.getJSONObject("mission").optString("type") == "escape") return escapeWork(work, jobId, key)
        val fresh = key != missionKey || optimizer == null
        if (fresh) {
            val m = TrajectoryModel(work)
            model = m
            optimizer = TrajectoryOptimizer(m)
            missionKey = key
        }
        val opt = optimizer!!
        opt.improve(if (fresh) FIRST_PLAN_MS else REFINE_PLAN_MS)
        val (seq, days) = if (opt.bestSeq != null) opt.bestSeq!! to opt.bestDays!! else {
            // nothing feasible found yet: fall back to the node's direct baseline
            val b = work.getJSONObject("baseline")
            IntArray(b.getJSONArray("seq").length()) { b.getJSONArray("seq").getInt(it) } to
                IntArray(b.getJSONArray("days").length()) { b.getJSONArray("days").getInt(it) }
        }

        // 2. The node scores the trajectory and gives us the header to hash.
        val (rc, scored) = http.request("POST", "/mining/trajectory", JSONObject()
            .put("job_id", jobId).put("seq", JSONArray(seq.toList())).put("days", JSONArray(days.toList())))
        if (rc != 200) throw IOException(scored.optString("error", "HTTP $rc"))
        return Job(
            id = jobId,
            height = work.getLong("height"),
            prefix = NodeClient.hexToBytes(scored.getString("prefix")),
            target = NodeClient.hexToBytes(scored.getString("target")),
            nonceSize = 8,
            littleEndian = false,
            rewardUnits = work.getLong("reward"),
            unitsPerCoin = work.getLong("units_per_coin"),
            work = TrajectoryInfo(seq.toList(), days.toList(), model!!.pathName(seq),
                scored.getDouble("dv_kms"), scored.getDouble("years"), scored.getDouble("improvement_pct"),
                work.getJSONObject("mission").optString("type", "science")),
        )
    }

    /** An escape block: leave the solar system toward a Pulsarite star (Escape.kt). */
    private fun escapeWork(work: JSONObject, jobId: String, key: String): Job {
        val fresh = key != missionKey || escOpt == null
        val b = work.getJSONObject("baseline")
        val start = EscapePlan.fromJson(IntArray(b.getJSONArray("seq").length()) { b.getJSONArray("seq").getInt(it) },
            IntArray(b.getJSONArray("days").length()) { b.getJSONArray("days").getInt(it) }, b.getJSONObject("escape"))
        if (fresh) {
            val m = TrajectoryModel(work)
            model = m
            escOpt = EscapeOptimizer(Escape(m, m.escape!!), start)
            missionKey = key
        }
        val opt = escOpt!!
        opt.improve(if (fresh) FIRST_PLAN_MS else REFINE_PLAN_MS)
        val plan = opt.bestPlan ?: start
        val (rc, scored) = http.request("POST", "/mining/trajectory", JSONObject()
            .put("job_id", jobId).put("seq", JSONArray(plan.seq.toList())).put("days", JSONArray(plan.days.toList()))
            .put("escape", plan.escapeJson()))
        if (rc != 200) throw IOException(scored.optString("error", "HTTP $rc"))
        return Job(
            id = jobId, height = work.getLong("height"),
            prefix = NodeClient.hexToBytes(scored.getString("prefix")), target = NodeClient.hexToBytes(scored.getString("target")),
            nonceSize = 8, littleEndian = false,
            rewardUnits = work.getLong("reward"), unitsPerCoin = work.getLong("units_per_coin"),
            work = TrajectoryInfo(plan.seq.toList(), plan.days.toList(), model!!.pathName(plan.seq),
                scored.getDouble("dv_kms"), scored.getDouble("years"), scored.getDouble("improvement_pct"),
                "escape", plan.escapeJson(), model!!.escape!!.starName, scored.getDouble("vinf_kms")),
        )
    }

    override fun submit(job: Job, nonce: Long): SubmitResult {
        val t = job.work as TrajectoryInfo
        val payload = JSONObject().put("job_id", job.id).put("seq", JSONArray(t.seq))
            .put("days", JSONArray(t.days)).put("nonce", nonce)
        if (t.escape != null) payload.put("escape", t.escape)
        val (code, body) = http.request("POST", "/mining/submit", payload)
        return if (code == 200 && body.optBoolean("ok")) {
            SubmitResult(true, "Block ${body.optLong("height")} accepted")
        } else {
            SubmitResult(false, body.optString("error", "HTTP $code"))
        }
    }

    override fun hasNewWork() = false
    override fun close() {}

    companion object {
        private const val FIRST_PLAN_MS = 3000L   // plan a new mission this long before hashing
        private const val REFINE_PLAN_MS = 1000L  // then keep refining on each refresh
    }
}
