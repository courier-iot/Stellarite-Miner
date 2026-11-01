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
    val work: UsefulWork? = null,  // the useful work this job's header commits to (own coins)
)

/** The useful-work half of a job, shown on the HUD and recorded in the ledger. */
interface UsefulWork {
    val summary: String      // one HUD line
    val gainPct: Double      // how much better than the network's baseline
}

/** Pulsarite: the probe's route through this block's moving stars. */
data class RouteInfo(
    val starIds: List<Int>,
    val years: Double,           // mission time: launch from rest, cruise at 0.1c, brake at survey stops
    val baselineYears: Double,   // the greedy route's mission time
    val improvementPct: Double,
    val lightYears: Double,      // distance flown
    val stopIds: List<Int> = emptyList(),   // survey stars where the probe stops
    val speedsPct: List<Int> = emptyList(), // each leg's cruise speed, % of light speed
    val fuelUsedPct: Double = 0.0,          // share of the fuel budget the plan burns
    val scoutedIds: List<Int> = emptyList(), // survey stars already imaged by Nebulite scouts: flown past
) : UsefulWork {
    override val summary get() = String.format(java.util.Locale.US,
        "ROUTE %d★ · %d STOPS%s · %,.0f YR · %.0f LY · FUEL %.0f%% · %.1f%% FASTER THAN GREEDY",
        starIds.size, stopIds.size, if (scoutedIds.isEmpty()) "" else " + ${scoutedIds.size} SCOUTED",
        years, lightYears, fuelUsedPct, improvementPct)
    override val gainPct get() = improvementPct
}

/** Nebulite: the spacecraft trajectory for this block's mission. */
data class TrajectoryInfo(
    val seq: List<Int>,
    val days: List<Int>,
    val path: String,          // e.g. "E-J-S"
    val dvKms: Double,
    val years: Double,
    val improvementPct: Double,
    val missionType: String = "science",
    /** Escape missions: the departure choices ({vinf_ms[, rp_mau]}), target star and speed. */
    val escape: org.json.JSONObject? = null,
    val starName: String = "",
    val vinfKms: Double = 0.0,
    /** Interstellar-object intercepts: the speed of the flyby past the object (km/s). */
    val encounterKms: Double = 0.0,
    /** Interstellar-object intercepts: the object's orbit (the mission's "iso" block), for the map. */
    val iso: org.json.JSONObject? = null,
) : UsefulWork {
    /** Planet missions and intercepts: arrival at the target. Escape missions: passing 550 AU (120 AU for heliopause runs). */
    val arrivalDate get() = if (escape != null) TrajectoryModel.dateOf(days.first() + years * 365.25)
        else TrajectoryModel.dateOf(days.last())
    override val summary get() = if (escape != null && missionType == "heliopause") String.format(java.util.Locale.US,
        "HELIOPAUSE RUN · %s · %.1f KM/S (%.2f AU/YR) · 120 AU IN %.1f YR · %.1f%% FASTER THAN BASELINE",
        path, vinfKms, vinfKms / Escape.KM_S_PER_AU_YEAR, years, improvementPct)
    else if (escape != null) String.format(java.util.Locale.US,
        "ESCAPE → %s · %s · %.1f KM/S (%.2f AU/YR) · 550 AU IN %.0f YR · %.1f%% FASTER THAN BASELINE",
        starName.uppercase(java.util.Locale.US), path, vinfKms, vinfKms / Escape.KM_S_PER_AU_YEAR, years, improvementPct)
    else if (missionType == "intercept") String.format(java.util.Locale.US,
        "INTERCEPT · INTERSTELLAR OBJECT · %s · %.2f KM/S · MEETS IT AT %.1f KM/S ON %s · %.1f%% CHEAPER THAN DIRECT",
        path, dvKms, encounterKms, arrivalDate, improvementPct)
    else String.format(java.util.Locale.US,
        "%s MISSION %s · %.2f KM/S · %.1f YR · ARRIVES %s · %.1f%% CHEAPER THAN DIRECT",
        missionType.uppercase(java.util.Locale.US), path, dvKms, years, arrivalDate, improvementPct)
    override val gainPct get() = improvementPct
}

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
