package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URI
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import javax.net.ssl.SSLSocketFactory

/**
 * Stratum v1 client for SHA-256d pools (Bitcoin, Bitcoin Cash, and similar).
 *
 * url:      stratum+tcp://host:port  (or stratum+ssl:// / stratum+tls:// for TLS)
 * user:     usually "<your payout address>.<worker name>"; check your pool's docs
 * password: often "x"; many pools read options like "d=0.01" (requested difficulty) from it
 */
class StratumClient(
    private val url: String,
    private val user: String,
    private val password: String,
    private val agent: String = "StellariteMiner/1.0",
) : PoolBackend {

    override val unitName = "shares"

    private class Notify(
        val jobId: String, val prevHash: String, val coinb1: String, val coinb2: String,
        val branch: List<String>, val version: String, val nbits: String, val ntime: String,
    )

    /** What submit() needs to report a share for a job. */
    class Extra(val extranonce2: String, val ntime: String)

    private val lock = Object()
    private var socket: Socket? = null
    private var out: OutputStream? = null
    private var reader: Thread? = null
    private val nextId = AtomicInteger(1)
    private val pending = ConcurrentHashMap<Int, ArrayBlockingQueue<JSONObject>>()

    @Volatile private var extranonce1 = ""
    @Volatile private var extranonce2Size = 4
    @Volatile private var difficulty = 1.0
    @Volatile private var notify: Notify? = null
    @Volatile private var failure: String? = null
    private val generation = AtomicLong(0)
    @Volatile private var served = -1L
    private val extranonce2Counter = AtomicLong(0)

    /** Pool-reported difficulty, for display. */
    val currentDifficulty get() = difficulty

    // ---- PoolBackend --------------------------------------------------

    override fun getWork(): Job {
        ensureConnected()
        val deadline = System.currentTimeMillis() + 30_000
        while (notify == null) {
            failure?.let { throw IOException(it) }
            if (System.currentTimeMillis() > deadline) throw IOException("pool sent no work")
            Thread.sleep(100)
        }
        val n = notify!!
        served = generation.get()
        val en2 = extranonce2Counter.getAndIncrement()
            .toString(16).padStart(extranonce2Size * 2, '0').takeLast(extranonce2Size * 2)
        val coinbase = StratumMath.unhex(n.coinb1 + extranonce1 + en2 + n.coinb2)
        val root = StratumMath.merkleRoot(coinbase, n.branch)
        return Job(
            id = n.jobId,
            height = heightFromCoinbase(n.coinb1),
            prefix = StratumMath.headerPrefix(n.version, n.prevHash, root, n.ntime, n.nbits),
            target = StratumMath.targetForDifficulty(difficulty),
            nonceSize = 4,
            littleEndian = true,
            extra = Extra(en2, n.ntime),
        )
    }

    override fun submit(job: Job, nonce: Long): SubmitResult {
        val extra = job.extra as Extra
        val nonceHex = String.format("%08x", nonce and 0xFFFF_FFFFL)  // big-endian hex, per Stratum
        val params = JSONArray().put(user).put(job.id).put(extra.extranonce2).put(extra.ntime).put(nonceHex)
        val reply = call("mining.submit", params, 15)
            ?: return SubmitResult(false, "pool did not answer")
        return if (reply.optBoolean("result", false)) {
            SubmitResult(true, "Share accepted")
        } else {
            SubmitResult(false, errorText(reply))
        }
    }

    override fun hasNewWork() = generation.get() != served

    override fun close() {
        synchronized(lock) {
            runCatching { socket?.close() }
            socket = null
            out = null
        }
        reader?.interrupt()
    }

    // ---- connection ---------------------------------------------------

    private fun ensureConnected() {
        synchronized(lock) {
            if (socket?.isConnected == true && failure == null) return
            runCatching { socket?.close() }
            failure = null
            notify = null
            val uri = URI(url.trim().replace(" ", ""))
            val host = uri.host ?: throw IOException("bad pool URL (use stratum+tcp://host:port)")
            val port = if (uri.port > 0) uri.port else throw IOException("pool URL needs a port")
            val tls = uri.scheme?.endsWith("ssl") == true || uri.scheme?.endsWith("tls") == true
            val s = if (tls) SSLSocketFactory.getDefault().createSocket() else Socket()
            s.connect(InetSocketAddress(host, port), 10_000)
            s.keepAlive = true
            socket = s
            out = s.getOutputStream()
            reader = Thread({ readLoop(s) }, "stratum-reader").apply { isDaemon = true; start() }
        }

        val sub = call("mining.subscribe", JSONArray().put(agent), 15)
            ?: throw IOException("pool did not answer subscribe")
        val result = sub.optJSONArray("result") ?: throw IOException("subscribe failed: ${errorText(sub)}")
        extranonce1 = result.getString(1)
        extranonce2Size = result.getInt(2)

        val auth = call("mining.authorize", JSONArray().put(user).put(password), 15)
            ?: throw IOException("pool did not answer authorize")
        if (!auth.optBoolean("result", false)) {
            close()
            throw IOException("pool rejected worker login: ${errorText(auth)}")
        }
    }

    private fun readLoop(s: Socket) {
        try {
            val br = BufferedReader(InputStreamReader(s.getInputStream()))
            while (true) {
                val line = br.readLine() ?: throw IOException("pool closed the connection")
                if (line.isBlank()) continue
                val msg = try { JSONObject(line) } catch (e: Exception) { continue }
                handle(msg)
            }
        } catch (e: Exception) {
            failure = e.message ?: "connection lost"
            generation.incrementAndGet()
            pending.values.forEach { it.offer(JSONObject().put("error", failure)) }
        }
    }

    private fun handle(msg: JSONObject) {
        val method = msg.optString("method", "")
        if (method.isEmpty()) {
            val id = msg.optInt("id", -1)
            pending.remove(id)?.offer(msg)
            return
        }
        val params = msg.optJSONArray("params") ?: JSONArray()
        when (method) {
            "mining.set_difficulty" -> {
                difficulty = params.optDouble(0, difficulty)
                generation.incrementAndGet()
            }
            "mining.set_extranonce" -> {
                extranonce1 = params.optString(0, extranonce1)
                extranonce2Size = params.optInt(1, extranonce2Size)
                generation.incrementAndGet()
            }
            "mining.notify" -> {
                val branch = params.getJSONArray(4)
                notify = Notify(
                    jobId = params.getString(0), prevHash = params.getString(1),
                    coinb1 = params.getString(2), coinb2 = params.getString(3),
                    branch = List(branch.length()) { branch.getString(it) },
                    version = params.getString(5), nbits = params.getString(6), ntime = params.getString(7),
                )
                generation.incrementAndGet()
            }
        }
    }

    private fun call(method: String, params: JSONArray, timeoutSeconds: Long): JSONObject? {
        val id = nextId.getAndIncrement()
        val q = ArrayBlockingQueue<JSONObject>(1)
        pending[id] = q
        val line = JSONObject().put("id", id).put("method", method).put("params", params).toString() + "\n"
        synchronized(lock) {
            val o = out ?: throw IOException("not connected")
            o.write(line.toByteArray())
            o.flush()
        }
        return q.poll(timeoutSeconds, TimeUnit.SECONDS).also { pending.remove(id) }
    }

    private fun errorText(reply: JSONObject): String {
        val err = reply.opt("error")
        return when (err) {
            is JSONArray -> err.optString(1, err.toString())
            null, JSONObject.NULL -> "rejected"
            else -> err.toString()
        }
    }

    /** BIP34 puts the block height at the start of the coinbase script; -1 if it can't be read. */
    private fun heightFromCoinbase(coinb1: String): Long = try {
        val b = StratumMath.unhex(coinb1)
        val len = b[42].toInt() and 0xff        // after version(4) + count(1) + prevout(36) + script length(1)
        if (len !in 1..8) -1 else {
            var h = 0L
            for (i in 0 until len) h = h or ((b[43 + i].toLong() and 0xff) shl (8 * i))
            h
        }
    } catch (e: Exception) { -1 }
}
