package com.example.stellariteminer

import java.math.BigInteger
import java.security.MessageDigest

/** Bitcoin block-header math used by Stratum pool mining. Pure JVM, no Android APIs. */
object StratumMath {

    /** Share difficulty 1 target: 0x00000000FFFF0000...0000 */
    private val DIFF1: BigInteger = BigInteger("FFFF", 16).shiftLeft(208)

    fun sha256d(data: ByteArray): ByteArray {
        val md = MessageDigest.getInstance("SHA-256")
        return md.digest(md.digest(data))
    }

    fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it.toInt() and 0xff) }

    fun unhex(s: String): ByteArray {
        require(s.length % 2 == 0) { "odd-length hex" }
        return ByteArray(s.length / 2) { i -> s.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
    }

    fun reversed(b: ByteArray): ByteArray = b.reversedArray()

    /** Stratum sends prevhash with each 4-byte word byte-swapped; undo that for the header. */
    fun swapWords(b: ByteArray): ByteArray {
        require(b.size % 4 == 0)
        val out = ByteArray(b.size)
        for (w in 0 until b.size / 4) for (i in 0 until 4) out[4 * w + i] = b[4 * w + 3 - i]
        return out
    }

    /** Merkle root (raw header byte order) from the coinbase transaction and the pool's branch. */
    fun merkleRoot(coinbase: ByteArray, branch: List<String>): ByteArray {
        var root = sha256d(coinbase)
        for (h in branch) root = sha256d(root + unhex(h))
        return root
    }

    /**
     * The first 76 bytes of the 80-byte header (everything but the nonce).
     * [versionHex], [nbitsHex], [ntimeHex] are big-endian hex as sent in mining.notify.
     */
    fun headerPrefix(versionHex: String, prevHashStratum: String, merkleRoot: ByteArray,
                     ntimeHex: String, nbitsHex: String): ByteArray =
        reversed(unhex(versionHex)) +
            swapWords(unhex(prevHashStratum)) +
            merkleRoot +
            reversed(unhex(ntimeHex)) +
            reversed(unhex(nbitsHex))

    /** Share target for a pool difficulty, as 32 big-endian bytes. */
    fun targetForDifficulty(difficulty: Double): ByteArray {
        require(difficulty > 0) { "difficulty must be positive" }
        // Scale to keep precision for fractional difficulties (e.g. 0.001).
        val scale = 1_000_000_000L
        val diff = BigInteger.valueOf(Math.round(difficulty * scale).coerceAtLeast(1))
        var t = DIFF1.multiply(BigInteger.valueOf(scale)).divide(diff)
        val max = BigInteger.ONE.shiftLeft(256).subtract(BigInteger.ONE)
        if (t > max) t = max
        val raw = t.toByteArray()
        val out = ByteArray(32)
        val src = if (raw.size > 32) raw.copyOfRange(raw.size - 32, raw.size) else raw
        System.arraycopy(src, 0, out, 32 - src.size, src.size)
        return out
    }
}
