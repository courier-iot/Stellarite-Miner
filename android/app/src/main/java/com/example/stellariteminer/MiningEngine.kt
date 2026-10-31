package com.example.stellariteminer

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.ThreadFactory
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/**
 * Multi-threaded SHA-256d nonce search. Pure JVM code, no Android APIs.
 *
 * Proof-of-work rule (must match the node's chain.py):
 *   sha256(sha256(prefix + nonce as 8 bytes big-endian)) <= target
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
        val nonceBytes = ByteArray(8)
        val random = SecureRandom()

        while (running) {
            val j = current.get()
            if (j == null || paused) {
                try { Thread.sleep(250) } catch (e: InterruptedException) { /* re-check running */ }
                continue
            }

            // Hash the fixed prefix once, then clone that state for every nonce
            // ("midstate"), which skips re-hashing the prefix each time.
            val midstate = MessageDigest.getInstance("SHA-256").apply { update(j.prefix) }
            val canClone = try { midstate.clone(); true } catch (e: CloneNotSupportedException) { false }

            // Each thread walks its own stripe of nonces from a random start in 0..2^62.
            var nonce = (random.nextLong() ushr 2) + index
            val step = threadCount.toLong()

            searching@ while (running && !paused && current.get() === j) {
                for (n in 0 until BATCH) {
                    writeBigEndian(nonce, nonceBytes)
                    val md = if (canClone) {
                        midstate.clone() as MessageDigest
                    } else {
                        outer.reset(); outer.update(j.prefix); outer
                    }
                    md.update(nonceBytes)
                    val hash = inner.digest(md.digest())
                    if (meetsTarget(hash, j.target)) {
                        hashes.addAndGet(n + 1L)
                        // Only the first thread to find a nonce for this job reports it.
                        if (current.compareAndSet(j, null)) onFound(j, nonce)
                        break@searching
                    }
                    nonce += step
                    if (nonce < 0) nonce = index.toLong()  // wrapped past Long.MAX_VALUE
                }
                hashes.addAndGet(BATCH.toLong())
            }
        }
    }

    companion object {
        private const val BATCH = 4096

        fun writeBigEndian(value: Long, out: ByteArray) {
            for (i in 0 until 8) out[i] = (value ushr (56 - 8 * i)).toByte()
        }

        /** Compare two 32-byte big-endian unsigned numbers: hash <= target. */
        fun meetsTarget(hash: ByteArray, target: ByteArray): Boolean {
            for (i in hash.indices) {
                val a = hash[i].toInt() and 0xff
                val b = target[i].toInt() and 0xff
                if (a != b) return a < b
            }
            return true
        }
    }
}
