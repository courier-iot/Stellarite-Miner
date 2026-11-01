package com.example.stellariteminer

/**
 * A unit of work: find a nonce so that sha256d(prefix + nonce) meets [target].
 *
 * Two layouts are supported:
 *  - Pulsarite: 8-byte big-endian nonce, hash compared as a big-endian number.
 *  - Bitcoin-style (Stratum pools): 80-byte header whose last 4 bytes are a
 *    little-endian nonce, hash compared as a little-endian number.
 */
class Job(
    val id: String,
    val height: Long,           // -1 when the pool doesn't say
    val prefix: ByteArray,      // everything before the nonce
    val target: ByteArray,      // 32 bytes, big-endian
    val nonceSize: Int,         // 8 (Pulsarite) or 4 (Bitcoin header)
    val littleEndian: Boolean,  // nonce byte order AND hash comparison order
    val rewardUnits: Long = 0,  // known reward if this job solves a block (own node only)
    val unitsPerCoin: Long = 100_000_000,
    val extra: Any? = null,     // backend-specific data needed to submit (e.g. Stratum extranonce2)
    val route: RouteInfo? = null,  // Pulsarite only: the star route this job's header commits to
)

/** The useful-work half of a Pulsarite job: the route through this block's stars. */
data class RouteInfo(
    val starIds: List<Int>,
    val lengthLy: Double,
    val baselineLy: Double,
    val improvementPct: Double,
)

class SubmitResult(val accepted: Boolean, val message: String)

/** Somewhere to get work from and send solutions to: your own node, or a Stratum pool. */
interface PoolBackend {
    /** "blocks" for your own node, "shares" for pools. */
    val unitName: String

    /** Blocking: returns fresh work. */
    fun getWork(): Job

    /** Blocking: sends a solution. */
    fun submit(job: Job, nonce: Long): SubmitResult

    /** True when the backend has received newer work than the last getWork() returned. */
    fun hasNewWork(): Boolean

    fun close()
}
