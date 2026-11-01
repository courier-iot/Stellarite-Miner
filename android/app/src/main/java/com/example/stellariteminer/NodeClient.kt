package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Talks to the Pulsarite node's HTTP API. Blocking calls: run off the main thread.
 *
 * Mining a Pulsarite block has two halves:
 *  1. useful work: optimise a route through the block's 24 stars (RouteOptimizer);
 *     the node turns that route into a header and a target, easier for shorter routes
 *  2. hashing: search nonces against that target (MiningEngine)
 * Each time fresh work is fetched for the same block, the optimiser keeps improving
 * the route it already has, so the target keeps getting easier.
 */
class NodeClient(baseUrl: String, private val address: String = "") : PoolBackend {
    override val unitName = "blocks"
    private val base = baseUrl.trim().trimEnd('/')

    // One optimiser per star problem, so improvement carries over between refreshes.
    private var problemKey = ""
    private var optimizer: RouteOptimizer? = null

    fun info(): JSONObject = request("GET", "/info", null).second

    override fun getWork(): Job {
        val (code, work) = request("GET", "/mining/work?address=" + URLEncoder.encode(address, "UTF-8"), null)
        if (code != 200) throw IOException(work.optString("error", "HTTP $code"))
        val jobId = work.getString("job_id")
        val stars = work.getJSONArray("stars")
        val n = stars.length()
        val ids = IntArray(n) { stars.getJSONObject(it).getInt("id") }

        // 1. Useful work: route through this block's stars.
        val key = ids.joinToString(",")
        val fresh = key != problemKey || optimizer == null
        if (fresh) {
            optimizer = RouteOptimizer(
                DoubleArray(n) { stars.getJSONObject(it).getDouble("x") },
                DoubleArray(n) { stars.getJSONObject(it).getDouble("y") },
                DoubleArray(n) { stars.getJSONObject(it).getDouble("z") },
            )
            problemKey = key
        }
        val opt = optimizer!!
        opt.improve(if (fresh) FIRST_ROUTE_MS else REFINE_ROUTE_MS)
        val route = opt.best.map { ids[it] }

        // 2. The node scores the route and gives us the header to hash.
        val (rc, scored) = request("POST", "/mining/route",
            JSONObject().put("job_id", jobId).put("route", JSONArray(route)))
        if (rc != 200) throw IOException(scored.optString("error", "HTTP $rc"))
        return Job(
            id = jobId,
            height = work.getLong("height"),
            prefix = hexToBytes(scored.getString("prefix")),
            target = hexToBytes(scored.getString("target")),
            nonceSize = 8,
            littleEndian = false,
            rewardUnits = work.getLong("reward"),
            unitsPerCoin = work.getLong("units_per_coin"),
            work = RouteInfo(route, scored.getDouble("length_ly"), scored.getDouble("baseline_ly"),
                scored.getDouble("improvement_pct")),
        )
    }

    /** [nonce] is kept in 0..Long.MAX_VALUE so it survives JSON as a plain number. */
    override fun submit(job: Job, nonce: Long): SubmitResult {
        val route = JSONArray((job.work as? RouteInfo)?.starIds ?: emptyList<Int>())
        val payload = JSONObject().put("job_id", job.id).put("route", route).put("nonce", nonce)
        val (code, body) = request("POST", "/mining/submit", payload)
        return if (code == 200 && body.optBoolean("ok")) {
            SubmitResult(true, "Block ${body.optLong("height")} accepted")
        } else {
            SubmitResult(false, body.optString("error", "HTTP $code"))
        }
    }

    override fun hasNewWork() = false
    override fun close() {}

    internal fun request(method: String, path: String, payload: JSONObject?, rawBody: String? = null): Pair<Int, JSONObject> {
        val (code, text) = requestRaw(method, path, payload, rawBody)
        val json = try { JSONObject(text) } catch (e: Exception) { JSONObject().put("error", "HTTP $code") }
        return code to json
    }

    /** Raw response text, for endpoints that return JSON arrays (/routes, /missions). */
    internal fun requestRaw(method: String, path: String, payload: JSONObject?, rawBody: String? = null): Pair<Int, String> {
        val conn = URL(base + path).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = 8000
            conn.readTimeout = if (rawBody != null) 60000 else 15000
            conn.setRequestProperty("Accept", "application/json")
            val body = rawBody ?: payload?.toString()
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            return code to (stream?.bufferedReader()?.use { it.readText() } ?: "{}")
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        private const val FIRST_ROUTE_MS = 2500L   // optimise a new block's route this long
        private const val REFINE_ROUTE_MS = 1000L  // then keep refining on each refresh

        fun hexToBytes(hex: String): ByteArray {
            require(hex.length % 2 == 0) { "odd-length hex" }
            return ByteArray(hex.length / 2) { i ->
                ((Character.digit(hex[2 * i], 16) shl 4) or Character.digit(hex[2 * i + 1], 16)).toByte()
            }
        }
    }
}
