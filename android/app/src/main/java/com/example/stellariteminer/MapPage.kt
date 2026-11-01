package com.example.stellariteminer

import android.app.Activity
import android.widget.TextView
import org.json.JSONArray
import java.util.Locale
import kotlin.math.sqrt

/**
 * The MAP tab. For Pulsarite: a 3D map of the star catalog with recently mined
 * routes, and the route the rig is optimising right now. For Nebulite: the
 * planets' real orbits with recently mined missions and the live mission plan.
 */
class MapPage(
    private val activity: Activity,
    private val view: Map3DView,
    private val title: TextView,
    private val legend: TextView,
) {
    private var loadedFor = ""          // coin id + url the data belongs to
    private var stars: JSONArray? = null
    private var routes: JSONArray? = null
    private var model: TrajectoryModel? = null
    private var missions: JSONArray? = null
    private var shownWork: UsefulWork? = null
    private var loading = false

    /** Call when the tab is shown, the coin changes, or the user taps refresh. */
    fun load(prefs: Prefs, force: Boolean = false) {
        val coin = prefs.coin
        val url = prefs.url(coin.id).trim().trimEnd('/')
        val key = coin.id + "|" + url
        if (coin.kind == WorkKind.NONE) {
            title.text = "MAP_OFFLINE"
            legend.text = "> The map shows Pulsarite star routes and Nebulite missions.\n> Select PLSR or NBLT on the RIG tab."
            view.setScene(emptyList(), emptyList(), emptyList(), "")
            loadedFor = ""
            return
        }
        if (prefs.isSolo) { loadSolo(coin); return }
        if (url.isEmpty()) {
            title.text = if (coin.kind == WorkKind.STAR_ROUTES) "STAR_MAP" else "ORBIT_MAP"
            legend.text = "> NO NODE ADDRESS YET.\n> On the RIG tab, start the ${coin.name} node on your computer and tap [FIND NODE]."
            view.setScene(emptyList(), emptyList(), emptyList(), "")
            loadedFor = ""
            return
        }
        if (!force && key == loadedFor) { refreshLive(); return }
        if (loading) return
        loading = true
        title.text = if (coin.kind == WorkKind.STAR_ROUTES) "STAR_MAP" else "ORBIT_MAP"
        legend.text = "> DOWNLOADING MAP DATA…"
        Thread {
            val http = NodeClient(url)
            val result = try {
                if (coin.kind == WorkKind.STAR_ROUTES) {
                    stars = http.request("GET", "/stars", null).second.getJSONArray("stars")
                    routes = fetchArray(http, "/routes?limit=12")
                } else {
                    model = TrajectoryModel(http.request("GET", "/planets", null).second)
                    missions = fetchArray(http, "/missions?limit=8")
                }
                null
            } catch (e: Exception) {
                friendlyError(e, url)
            }
            activity.runOnUiThread {
                loading = false
                if (result != null) {
                    legend.text = "> MAP LINK FAILED · $result\n> Fix NODE_URI on the RIG tab ([FIND NODE] can locate it), then tap [REFRESH]."
                } else {
                    loadedFor = key
                    shownWork = null
                    build(coin.kind)
                }
            }
        }.start()
    }

    private var soloHeight = -1L

    /** Solo mode: the map comes from the blockchain on this phone. */
    private fun loadSolo(coin: CoinProfile) {
        val chain = SoloBackend.chainFor(activity, coin)
        title.text = if (coin.kind == WorkKind.STAR_ROUTES) "STAR_MAP" else "ORBIT_MAP"
        if (coin.kind == WorkKind.STAR_ROUTES) {
            stars = JSONArray().also { a ->
                for (i in SoloData.STAR_NAMES.indices) a.put(org.json.JSONObject().put("id", i)
                    .put("name", SoloData.STAR_NAMES[i]).put("x", SoloData.STAR_X[i]).put("y", SoloData.STAR_Y[i])
                    .put("z", SoloData.STAR_Z[i]))
            }
            routes = SoloBackend.routeRows(chain, 12)
        } else {
            model = TrajectoryModel(org.json.JSONObject(SoloData.NEBULITE_MODEL_JSON))
            missions = SoloBackend.missionRows(chain, 8)
        }
        loadedFor = coin.id + "|solo"
        soloHeight = chain.height
        shownWork = null
        build(coin.kind)
        legend.text = "> SOLO CHAIN ON THIS PHONE · height ${chain.height}\n" + legend.text
    }

    /** Re-draw if the rig's current route or mission changed (or the solo chain grew). */
    fun refreshLive() {
        if (loadedFor.endsWith("|solo")) {
            val coin = CoinProfile.byId(loadedFor.substringBefore("|"))
            if (SoloBackend.chainFor(activity, coin).height != soloHeight) { loadSolo(coin); return }
        }
        if (loadedFor.isEmpty() || MinerService.status.work === shownWork) return
        build(if (loadedFor.startsWith("nblt|")) WorkKind.TRAJECTORIES else WorkKind.STAR_ROUTES)
    }

    private fun fetchArray(http: NodeClient, path: String): JSONArray {
        val (code, text) = http.requestRaw("GET", path, null)
        if (code != 200) throw java.io.IOException("HTTP $code from $path")
        return JSONArray(text)
    }

    private fun build(kind: WorkKind) {
        shownWork = MinerService.status.work
        if (kind == WorkKind.STAR_ROUTES) buildStars() else buildOrbits()
    }

    // ---- Pulsarite: stars and routes ---------------------------------

    private fun buildStars() {
        val cat = stars ?: return
        val pos = HashMap<Int, DoubleArray>()
        for (i in 0 until cat.length()) {
            val s = cat.getJSONObject(i)
            pos[s.getInt("id")] = doubleArrayOf(s.getDouble("x") / 1000, s.getDouble("y") / 1000, s.getDouble("z") / 1000)
        }
        val live = (MinerService.status.work as? RouteInfo)?.starIds
        val liveSet = live?.toSet() ?: emptySet()

        val points = ArrayList<MapPoint>()
        points += MapPoint(0.0, 0.0, 0.0, Theme.AMBER, 4.5f, "SOL", alwaysLabel = true, glow = true)
        for (i in 0 until cat.length()) {
            val s = cat.getJSONObject(i)
            val id = s.getInt("id")
            val p = pos[id]!!
            val inLive = id in liveSet
            points += MapPoint(p[0], p[1], p[2], if (inLive) Theme.CRIMSON_LIGHT else Theme.TEXT,
                if (inLive) 3.2f else 1.8f, s.getString("name").uppercase(Locale.US), alwaysLabel = inLive, glow = inLive)
        }

        val lines = ArrayList<MapLine>()
        val rs = routes ?: JSONArray()
        for (i in rs.length() - 1 downTo 0) {          // oldest first so the newest draws on top
            val ids = rs.getJSONObject(i).optJSONArray("route_ids") ?: continue
            val pts = ArrayList<DoubleArray>().apply { add(doubleArrayOf(0.0, 0.0, 0.0)) }
            for (k in 0 until ids.length()) pos[ids.getInt(k)]?.let { pts += it }
            lines += MapLine(pts, Theme.CRIMSON, if (i == 0) 1.6f else 1f, if (i == 0) 200 else 70)
        }
        if (live != null) {
            val pts = ArrayList<DoubleArray>().apply { add(doubleArrayOf(0.0, 0.0, 0.0)) }
            live.forEach { id -> pos[id]?.let { pts += it } }
            lines += MapLine(pts, Theme.AMBER, 2.2f, 255)
        }
        view.setScene(points, lines, listOf(10.0, 20.0, 30.0, 40.0), "LY")

        val newest = if (rs.length() > 0) rs.getJSONObject(0) else null
        legend.text = buildString {
            append("> ${cat.length()} STARS · ${rs.length()} MINED ROUTES (CRIMSON)")
            if (newest != null) append(String.format(Locale.US, "\n> LATEST: BLOCK %d · %.1f LY · %.1f%% SHORTER",
                newest.getInt("height"), newest.getDouble("length_ly"), newest.getDouble("improvement_pct")))
            val w = MinerService.status.work as? RouteInfo
            if (w != null) append(String.format(Locale.US, "\n> LIVE ROUTE (AMBER): %.1f LY", w.lengthLy))
            append("\n> DRAG TO ROTATE · PINCH TO ZOOM IN FOR NAMES · DOUBLE-TAP TO RESET")
        }
    }

    // ---- Nebulite: orbits and missions -------------------------------

    /** Compress distances (r -> sqrt(r)) so inner planets stay visible next to Neptune. */
    private fun squash(p: DoubleArray): DoubleArray {
        val r = sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
        if (r < 1e-9) return doubleArrayOf(0.0, 0.0, 0.0)
        val f = sqrt(r) / r
        return doubleArrayOf(p[0] * f, p[1] * f, p[2] * f)
    }

    private fun buildOrbits() {
        val m = model ?: return
        val today = System.currentTimeMillis() / 86_400_000.0 - 10957.5     // days since J2000
        val live = MinerService.status.work as? TrajectoryInfo
        val ref = live?.days?.firstOrNull()?.toDouble() ?: today

        val points = ArrayList<MapPoint>()
        val lines = ArrayList<MapLine>()
        points += MapPoint(0.0, 0.0, 0.0, Theme.AMBER, 5f, "SUN", alwaysLabel = true, glow = true)
        for (pid in m.planets.indices) {
            lines += MapLine(m.orbitPoints(pid, ref).map { squash(it) }, Theme.MUTED, 1f, 90)
            val p = squash(m.state(pid, ref))
            points += MapPoint(p[0], p[1], p[2], Theme.TEXT, if (pid >= 4) 3f else 2.2f,
                m.planets[pid].name.uppercase(Locale.US), alwaysLabel = pid >= 2)   // inner two only when zoomed
        }

        val ms = missions ?: JSONArray()
        for (i in ms.length() - 1 downTo 0) {
            val o = ms.getJSONObject(i)
            val seq = o.optJSONArray("seq") ?: continue
            val days = o.getJSONArray("days")
            val path = m.samplePath(IntArray(seq.length()) { seq.getInt(it) }, IntArray(days.length()) { days.getInt(it) }, 40)
            lines += MapLine(path.map { squash(it) }, Theme.CRIMSON, if (i == 0) 1.6f else 1f, if (i == 0) 200 else 70)
        }
        if (live != null) {
            val seq = live.seq.toIntArray(); val days = live.days.toIntArray()
            lines += MapLine(m.samplePath(seq, days, 60).map { squash(it) }, Theme.AMBER, 2.2f, 255)
            for (k in seq.indices) {                       // where the spacecraft meets each planet, and when
                val p = squash(m.state(seq[k], days[k].toDouble()))
                val year = 2000 + ((days[k] + 0.5) / 365.25).toInt()
                val what = when (k) { 0 -> "LAUNCH"; seq.size - 1 -> "ARRIVE"; else -> "FLYBY" }
                points += MapPoint(p[0], p[1], p[2], Theme.CRIMSON_LIGHT, 3f,
                    "$what ${m.planets[seq[k]].name.uppercase(Locale.US)} $year", alwaysLabel = true, glow = true)
            }
        }
        view.setScene(points, lines, emptyList(), "")

        val newest = if (ms.length() > 0) ms.getJSONObject(0) else null
        legend.text = buildString {
            val yr = 2000 + ((ref + 0.5) / 365.25).toInt()
            append("> REAL PLANET ORBITS (JPL ELEMENTS) · PLANETS SHOWN IN $yr · DISTANCES COMPRESSED")
            append("\n> ${ms.length()} MINED MISSIONS (CRIMSON)")
            if (newest != null) {
                val path = newest.getJSONArray("path").let { a -> (0 until a.length()).joinToString("-") { a.getString(it).take(2).uppercase(Locale.US) } }
                append(String.format(Locale.US, "\n> LATEST: BLOCK %d · %s · %.2f KM/S · %.1f YR",
                    newest.getInt("height"), path, newest.getDouble("dv_kms"), newest.getDouble("years")))
            }
            if (live != null) append("\n> LIVE PLAN (AMBER): ${live.path} · " +
                String.format(Locale.US, "%.2f KM/S · %.1f YR", live.dvKms, live.years))
            append("\n> DRAG TO ROTATE · PINCH TO ZOOM · DOUBLE-TAP TO RESET")
        }
    }
}
