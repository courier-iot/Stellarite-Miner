package com.example.stellariteminer

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** One mining session: from tapping Start to Stop (saved periodically while running). */
data class Session(
    val start: Long,            // epoch millis, also the session's id
    val end: Long,
    val coinId: String,
    val ticker: String,
    val unit: String,           // "blocks" or "shares"
    val hashes: Long,
    val accepted: Int,
    val rejected: Int,
    val earnedUnits: Long,      // only known for your own coin
    val unitsPerCoin: Long,
    val bestGainPct: Double = 0.0,  // Pulsarite: best route improvement over the greedy baseline
) {
    val seconds get() = ((end - start) / 1000).coerceAtLeast(0)

    fun toJson(): JSONObject = JSONObject()
        .put("start", start).put("end", end).put("coin", coinId).put("ticker", ticker)
        .put("unit", unit).put("hashes", hashes).put("accepted", accepted).put("rejected", rejected)
        .put("earned", earnedUnits).put("upc", unitsPerCoin).put("gain", bestGainPct)

    companion object {
        fun fromJson(o: JSONObject) = Session(
            o.getLong("start"), o.getLong("end"), o.getString("coin"), o.getString("ticker"),
            o.getString("unit"), o.getLong("hashes"), o.getInt("accepted"), o.getInt("rejected"),
            o.getLong("earned"), o.getLong("upc"), o.optDouble("gain", 0.0),
        )
    }
}

/** Lifetime totals for one coin. */
data class CoinTotals(
    val coinId: String,
    val ticker: String,
    val unit: String,
    val seconds: Long = 0,
    val hashes: Long = 0,
    val accepted: Long = 0,
    val rejected: Long = 0,
    val earnedUnits: Long = 0,
    val unitsPerCoin: Long = 100_000_000,
    val sessions: Int = 0,
    val bestGainPct: Double = 0.0,
)

/**
 * Persistent record of what was mined, stored as JSON in the app's private storage.
 * Totals are kept separately from the session list, so trimming old sessions
 * never changes lifetime numbers.
 */
class Ledger(private val file: File) {
    private val sessions = ArrayList<Session>()
    private val totals = LinkedHashMap<String, CoinTotals>()

    init { load() }

    @Synchronized fun sessions(): List<Session> = sessions.sortedByDescending { it.start }
    @Synchronized fun totals(): List<CoinTotals> = totals.values.sortedByDescending { it.seconds }

    /** Add or update a session (matched by start time) and fold the change into totals. */
    @Synchronized fun upsert(s: Session) {
        val idx = sessions.indexOfFirst { it.start == s.start }
        val prev = if (idx >= 0) sessions[idx] else null
        if (idx >= 0) sessions[idx] = s else sessions += s
        val t = totals[s.coinId] ?: CoinTotals(s.coinId, s.ticker, s.unit, unitsPerCoin = s.unitsPerCoin)
        totals[s.coinId] = t.copy(
            seconds = t.seconds + s.seconds - (prev?.seconds ?: 0),
            hashes = t.hashes + s.hashes - (prev?.hashes ?: 0),
            accepted = t.accepted + s.accepted - (prev?.accepted ?: 0),
            rejected = t.rejected + s.rejected - (prev?.rejected ?: 0),
            earnedUnits = t.earnedUnits + s.earnedUnits - (prev?.earnedUnits ?: 0),
            sessions = t.sessions + if (prev == null) 1 else 0,
            bestGainPct = maxOf(t.bestGainPct, s.bestGainPct),
        )
        while (sessions.size > MAX_SESSIONS) sessions.removeAt(sessions.indexOf(sessions.minByOrNull { it.start }!!))
        save()
    }

    @Synchronized fun clear() {
        sessions.clear(); totals.clear(); save()
    }

    private fun load() {
        if (!file.exists()) return
        try {
            val root = JSONObject(file.readText())
            val arr = root.getJSONArray("sessions")
            for (i in 0 until arr.length()) sessions += Session.fromJson(arr.getJSONObject(i))
            val tot = root.getJSONObject("totals")
            for (k in tot.keys()) {
                val o = tot.getJSONObject(k)
                totals[k] = CoinTotals(k, o.getString("ticker"), o.getString("unit"), o.getLong("seconds"),
                    o.getLong("hashes"), o.getLong("accepted"), o.getLong("rejected"),
                    o.getLong("earned"), o.getLong("upc"), o.getInt("sessions"), o.optDouble("gain", 0.0))
            }
        } catch (e: Exception) {
            // A damaged ledger file shouldn't stop the app; keep it aside and start fresh.
            file.renameTo(File(file.path + ".bad"))
            sessions.clear(); totals.clear()
        }
    }

    private fun save() {
        val arr = JSONArray()
        sessions.forEach { arr.put(it.toJson()) }
        val tot = JSONObject()
        totals.forEach { (k, t) ->
            tot.put(k, JSONObject().put("ticker", t.ticker).put("unit", t.unit).put("seconds", t.seconds)
                .put("hashes", t.hashes).put("accepted", t.accepted).put("rejected", t.rejected)
                .put("earned", t.earnedUnits).put("upc", t.unitsPerCoin).put("sessions", t.sessions)
                .put("gain", t.bestGainPct))
        }
        val tmp = File(file.path + ".tmp")
        tmp.writeText(JSONObject().put("sessions", arr).put("totals", tot).toString())
        tmp.renameTo(file)
    }

    companion object {
        private const val MAX_SESSIONS = 200
        @Volatile private var instance: Ledger? = null

        fun get(dir: File): Ledger = instance ?: synchronized(this) {
            instance ?: Ledger(File(dir, "ledger.json")).also { instance = it }
        }
    }
}
