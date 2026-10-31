package com.example.stellariteminer

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** A unit of work from the node: find a nonce so sha256d(prefix + nonce) <= target. */
class Job(
    val id: String,
    val height: Long,
    val prefix: ByteArray,
    val target: ByteArray,   // 32 bytes, big-endian
    val rewardUnits: Long,
    val unitsPerCoin: Long,
)

class SubmitResult(val accepted: Boolean, val message: String)

/** Talks to the Pulsarite node's HTTP API. Blocking calls: run off the main thread. */
class NodeClient(baseUrl: String) {
    private val base = baseUrl.trim().trimEnd('/')

    fun info(): JSONObject = request("GET", "/info", null).second

    fun getWork(address: String): Job {
        val (code, body) = request("GET", "/mining/work?address=" + URLEncoder.encode(address, "UTF-8"), null)
        if (code != 200) throw IOException(body.optString("error", "HTTP $code"))
        return Job(
            id = body.getString("job_id"),
            height = body.getLong("height"),
            prefix = hexToBytes(body.getString("prefix")),
            target = hexToBytes(body.getString("target")),
            rewardUnits = body.getLong("reward"),
            unitsPerCoin = body.getLong("units_per_coin"),
        )
    }

    /** [nonce] is kept in 0..Long.MAX_VALUE so it survives JSON as a plain number. */
    fun submit(jobId: String, nonce: Long): SubmitResult {
        val payload = JSONObject().put("job_id", jobId).put("nonce", nonce)
        val (code, body) = request("POST", "/mining/submit", payload)
        return if (code == 200 && body.optBoolean("ok")) {
            SubmitResult(true, "Block ${body.optLong("height")} accepted")
        } else {
            SubmitResult(false, body.optString("error", "HTTP $code"))
        }
    }

    private fun request(method: String, path: String, payload: JSONObject?): Pair<Int, JSONObject> {
        val conn = URL(base + path).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = 8000
            conn.readTimeout = 15000
            conn.setRequestProperty("Accept", "application/json")
            if (payload != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(payload.toString().toByteArray()) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: "{}"
            val json = try { JSONObject(text) } catch (e: Exception) { JSONObject().put("error", "HTTP $code") }
            return code to json
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        fun hexToBytes(hex: String): ByteArray {
            require(hex.length % 2 == 0) { "odd-length hex" }
            return ByteArray(hex.length / 2) { i ->
                ((Character.digit(hex[2 * i], 16) shl 4) or Character.digit(hex[2 * i + 1], 16)).toByte()
            }
        }
    }
}
