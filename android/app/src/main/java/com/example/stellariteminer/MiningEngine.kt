package com.example.stellariteminer

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.ThreadFactory
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/**
 * Multi-threaded SHA-256d nonce search. Pure JVM code, no Android APIs.
 *
 *   hash = sha256(sha256(prefix + nonce))
 *   Pulsarite: nonce is 8 bytes big-endian, hash read big-endian, must be <= target
 *   Bitcoin:   nonce is 4 bytes little-endian, hash read little-endian, must be <= target
 */
class MiningEngine(
    private val threadCount: Int,
    private val threadFactory: ThreadFactory,
    private val onFound: (job: Job, nonce: Long) -> Unit,
) {
    private val current = AtomicReference<Job?>(null)
    private val workers = mutableListOf<Thread>()
    @Volatile private var running = false
    @Volatile var paused = false

    /** Set when every thread has run out of nonces for the current job (4-byte nonces only). */
    @Volatile var exhausted: Job? = null
        private set

    /** Total hashes computed since start; the caller derives a hashrate from it. */
    val hashes = AtomicLong(0)

    var job: Job?
        get() = current.get()
        set(value) = current.set(value)

    fun start() {
        if (running) return
        running = true
        repeat(threadCount) { i ->
            val t = threadFactory.newThread { work(i) }
            t.name = "miner-$i"
            t.isDaemon = true
            workers += t
            t.start()
        }
    }

    fun stop() {
        running = false
        workers.forEach { it.interrupt() }
        workers.forEach { runCatching { it.join(2000) } }
        workers.clear()
    }

    private fun work(index: Int) {
        val outer = MessageDigest.getInstance("SHA-256")
        val inner = MessageDigest.getInstance("SHA-256")
        val random = SecureRandom()
        var lastJob: Job? = null

        while (running) {
            val j = current.get()
            if (j == null || paused || j === lastJob) {
                // Nothing to do, paused, or we already finished this job's nonce range.
                try { Thread.sleep(200) } catch (e: InterruptedException) { /* re-check running */ }
                continue
            }
            lastJob = j

            // Hash the fixed prefix once and clone that state per nonce ("midstate").
            val midstate = MessageDigest.getInstance("SHA-256").apply { update(j.prefix) }
            val canClone = try { midstate.clone(); true } catch (e: CloneNotSupportedException) { false }
            val nonceBytes = ByteArray(j.nonceSize)
            val step = threadCount.toLong()
            val maxNonce = if (j.nonceSize == 4) 0xFFFF_FFFFL else Long.MAX_VALUE
            // 8-byte nonces start at a random point; 4-byte ranges are walked from 0.
            var nonce = if (j.nonceSize == 4) index.toLong() else (random.nextLong() ushr 2) + index

            searching@ while (running && !paused && current.get() === j) {
                var done = 0L
                for (n in 0 until BATCH) {
                    writeNonce(nonce, nonceBytes, j.littleEndian)
                    val md = if (canClone) {
                        midstate.clone() as MessageDigest
                    } else {
                        outer.reset(); outer.update(j.prefix); outer
                    }
                    md.update(nonceBytes)
                    val hash = inner.digest(md.digest())
                    done++
                    if (meetsTarget(hash, j.target, j.littleEndian)) {
                        // Pools accept many shares per job; our own node takes one block per job.
                        if (j.nonceSize == 4) {
                            onFound(j, nonce)
                        } else if (current.compareAndSet(j, null)) {
                            onFound(j, nonce)
                            break
                        }
                    }
                    nonce += step
                    if (nonce > maxNonce || nonce < 0) {
                        hashes.addAndGet(done)
                        if (j.nonceSize == 4) exhausted = j else nonce = index.toLong()
                        break@searching
                    }
                }
                hashes.addAndGet(done)
                if (current.get() !== j) break
            }
            if (current.get() !== j) lastJob = null
        }
    }

    companion object {
        private const val BATCH = 4096

        fun writeNonce(value: Long, out: ByteArray, littleEndian: Boolean) {
            val n = out.size
            for (i in 0 until n) {
                val shift = if (littleEndian) 8 * i else 8 * (n - 1 - i)
                out[i] = (value ushr shift).toByte()
            }
        }

        /** hash <= target, both 32 bytes; target is big-endian, hash read in [littleEndian] order. */
        fun meetsTarget(hash: ByteArray, target: ByteArray, littleEndian: Boolean = false): Boolean {
            for (i in 0 until 32) {
                val a = (if (littleEndian) hash[31 - i] else hash[i]).toInt() and 0xff
                val b = target[i].toInt() and 0xff
                if (a != b) return a < b
            }
            return true
        }
    }
}
