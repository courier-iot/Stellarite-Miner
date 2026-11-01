package com.example.stellariteminer

import android.app.Activity
import android.view.View
import android.widget.SeekBar
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import kotlin.math.sqrt

/**
 * The MAP tab.
 *  - Pulsarite: 3D map of the (moving) star catalog with recently mined routes and the
 *    route the rig is planning. The time slider flies the probe along the focus route
 *    while the stars drift.
 *  - Nebulite: the planets' real orbits with recently mined missions and the live
 *    plan. The time slider flies the spacecraft from launch to arrival.
 * Tap any star, planet or encounter for details.
 */
class MapPage(
    private val activity: Activity,
    private val view: Map3DView,
    private val title: TextView,
    private val legend: TextView,
    private val info: TextView,
    private val timeRow: View,
    private val timeLabel: TextView,
    private val slider: SeekBar,
) {
    private var loadedFor = ""          // coin id + url (or |solo) the data belongs to
    private var kind = WorkKind.NONE
    private var stars: JSONArray? = null
    private var probe: JSONObject? = null     // probe speed / launch / iterations
    private var routes: JSONArray? = null
    private var model: TrajectoryModel? = null
    private var missions: JSONArray? = null
    private var shownWork: UsefulWork? = null
    private var loading = false
    private var soloHeight = -1L
    private var timeF = 0.0                   // slider position 0..1

    // cached per build
    private var staticLines: List<MapLine> = emptyList()
    private var legendBase = ""

    init {
        view.onPick = { p ->
            if (p?.info == null) info.visibility = View.GONE
            else { info.text = p.info; info.visibility = View.VISIBLE }
        }
        slider.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, progress: Int, fromUser: Boolean) {
                if (!fromUser) return
                timeF = progress / 1000.0
                drawMoving()
            }
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })
    }

    /** Call when the tab is shown, the coin changes, or the user taps refresh. */
    fun load(prefs: Prefs, force: Boolean = false) {
        val coin = prefs.coin
        val url = prefs.url(coin.id).trim().trimEnd('/')
        val key = coin.id + "|" + url
        kind = coin.kind
        title.text = if (coin.kind == WorkKind.STAR_ROUTES) "STAR_MAP" else "ORBIT_MAP"
        if (coin.kind == WorkKind.NONE) {
            title.text = "MAP_OFFLINE"
            showMessage("> The map shows Pulsarite star routes and Nebulite missions.\n> Select PLSR or NBLT on the RIG tab.")
            return
        }
        if (prefs.isSolo) { loadSolo(coin); return }
        if (url.isEmpty()) {
            showMessage("> NO NODE ADDRESS YET.\n> On the RIG tab, start the ${coin.name} node on your computer and tap [FIND NODE].")
            return
        }
        if (!force && key == loadedFor) { refreshLive(); return }
        if (loading) return
        loading = true
        legend.text = "> DOWNLOADING MAP DATA…"
        Thread {
            val http = NodeClient(url)
            val result = try {
                if (coin.kind == WorkKind.STAR_ROUTES) {
                    val s = http.request("GET", "/stars", null).second
                    stars = s.getJSONArray("stars")
                    probe = s
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
                    build()
                }
            }
        }.start()
    }

    private fun showMessage(text: String) {
        legend.text = text
        view.setScene(emptyList(), emptyList(), emptyList(), "")
        info.visibility = View.GONE
        timeRow.visibility = View.GONE
        loadedFor = ""
    }

    /** Solo mode: the map comes from the blockchain on this phone. */
    private fun loadSolo(coin: CoinProfile) {
        val chain = SoloBackend.chainFor(activity, coin)
        if (coin.kind == WorkKind.STAR_ROUTES) {
            stars = JSONArray().also { a ->
                for (i in SoloData.STAR_NAMES.indices) a.put(JSONObject().put("id", i)
                    .put("name", SoloData.STAR_NAMES[i]).put("x", SoloData.STAR_X[i]).put("y", SoloData.STAR_Y[i])
                    .put("z", SoloData.STAR_Z[i]).put("vx", SoloData.STAR_VX[i]).put("vy", SoloData.STAR_VY[i])
                    .put("vz", SoloData.STAR_VZ[i]))
            }
            probe = JSONObject().put("probe_speed_mly_per_year", SoloData.PROBE_SPEED)
                .put("launch_t", SoloData.LAUNCH_T).put("intercept_iterations", SoloData.INTERCEPT_ITERATIONS)
            routes = SoloBackend.routeRows(chain, 12)
        } else {
            model = TrajectoryModel(JSONObject(SoloData.NEBULITE_MODEL_JSON))
            missions = SoloBackend.missionRows(chain, 8)
        }
        loadedFor = coin.id + "|solo"
        soloHeight = chain.height
        build()
    }

    /** Re-draw if the rig's current route or mission changed (or the solo chain grew). */
    fun refreshLive() {
        if (loadedFor.endsWith("|solo")) {
            val coin = CoinProfile.byId(loadedFor.substringBefore("|"))
            if (SoloBackend.chainFor(activity, coin).height != soloHeight) { loadSolo(coin); return }
        }
        if (loadedFor.isEmpty() || MinerService.status.work === shownWork) return
        build()
    }

    private fun fetchArray(http: NodeClient, path: String): JSONArray {
        val (code, text) = http.requestRaw("GET", path, null)
        if (code != 200) throw java.io.IOException("HTTP $code from $path")
        return JSONArray(text)
    }

    private fun build() {
        shownWork = MinerService.status.work
        if (kind == WorkKind.STAR_ROUTES) buildStars() else buildOrbits()
        drawMoving()
    }

    private fun drawMoving() {
        if (kind == WorkKind.STAR_ROUTES) drawStarsAt() else drawOrbitsAt()
    }

    // ---- Pulsarite: moving stars and routes ----------------------------

    private var field: StarField? = null            // whole catalog (for drawing stars at any time)
    private var focusIds: List<Int> = emptyList()   // route being flown by the slider
    private var focusLegs: List<StarField.Leg> = emptyList()
    private var focusLabel = ""

    private fun catalogField(cat: JSONArray, p: JSONObject): StarField {
        val n = cat.length()
        fun col(k: String) = LongArray(n) { cat.getJSONObject(it).optLong(k, 0) }
        return StarField(IntArray(n) { cat.getJSONObject(it).getInt("id") }, col("x"), col("y"), col("z"),
            col("vx"), col("vy"), col("vz"), p.getLong("probe_speed_mly_per_year"), p.getLong("launch_t"),
            p.getInt("intercept_iterations"))
    }

    private fun buildStars() {
        val cat = stars ?: return
        val f = catalogField(cat, probe ?: return)
        field = f
        val index = HashMap<Int, Int>().apply { for (i in 0 until f.size) put(f.ids[i], i) }
        val live = (MinerService.status.work as? RouteInfo)?.starIds
        val rs = routes ?: JSONArray()
        val newest = if (rs.length() > 0) rs.getJSONObject(0) else null
        focusIds = live ?: newest?.optJSONArray("route_ids")?.let { a -> List(a.length()) { a.getInt(it) } } ?: emptyList()
        focusLabel = if (live != null) "LIVE ROUTE" else if (newest != null) "BLOCK ${newest.getInt("height")} ROUTE" else ""
        focusLegs = if (focusIds.isEmpty()) emptyList() else {
            val order = IntArray(focusIds.size) { index[focusIds[it]] ?: 0 }
            f.legs(order)
        }

        // Mined routes, drawn through each flyby's intercept point (where the star was when the probe passed).
        val lines = ArrayList<MapLine>()
        for (i in rs.length() - 1 downTo 0) {
            val ids = rs.getJSONObject(i).optJSONArray("route_ids") ?: continue
            val order = IntArray(ids.length()) { index[ids.getInt(it)] ?: 0 }
            val pts = listOf(doubleArrayOf(0.0, 0.0, 0.0)) + f.legs(order).map { ly(it.at) }
            lines += MapLine(pts, Theme.CRIMSON, if (i == 0 && live == null) 1.6f else 1f, if (i == 0) 170 else 60)
        }
        if (live != null) {
            lines += MapLine(listOf(doubleArrayOf(0.0, 0.0, 0.0)) + focusLegs.map { ly(it.at) }, Theme.AMBER, 2.2f, 255)
        }
        staticLines = lines
        legendBase = buildString {
            append("> ${cat.length()} STARS (MOVING) · ${rs.length()} MINED ROUTES (CRIMSON)")
            if (newest != null) append(String.format(Locale.US, "\n> LATEST: BLOCK %d · %,.0f YR · %.1f%% FASTER%s",
                newest.getInt("height"), newest.optDouble("years", 0.0), newest.getDouble("improvement_pct"),
                newest.optString("miner_name", "").let { if (it.isNotEmpty() && it != "null") " · BY $it" else "" }))
            val w = shownWork as? RouteInfo
            if (live != null && w != null) append(String.format(Locale.US, "\n> LIVE ROUTE (AMBER): %,.0f YR AT 0.1c", w.years))
            if (focusLegs.isNotEmpty()) append("\n> SLIDE TO FLY THE $focusLabel · TAP A STAR FOR DETAILS")
            else append("\n> TAP A STAR FOR DETAILS · DRAG TO ROTATE · PINCH TO ZOOM")
        }
        timeRow.visibility = if (focusLegs.isNotEmpty()) View.VISIBLE else View.GONE
    }

    private fun ly(p: LongArray) = doubleArrayOf(p[0] / 1000.0, p[1] / 1000.0, p[2] / 1000.0)

    private fun drawStarsAt() {
        val f = field ?: return
        val start = f.launchT
        val end = focusLegs.lastOrNull()?.t ?: start
        val t = start + ((end - start) * timeF).toLong()
        val flyby = HashMap<Int, StarField.Leg>().apply { focusLegs.forEach { l -> put(f.ids[l.star], l) } }

        val points = ArrayList<MapPoint>()
        points += MapPoint(0.0, 0.0, 0.0, Theme.AMBER, 4.5f, "SOL", alwaysLabel = true, glow = true,
            info = "SOL\nThe probe launches from here in ${2000 + start / 1000}.", key = "sol")
        val cat = stars!!
        for (i in 0 until f.size) {
            val id = f.ids[i]
            val p = f.pos(i, t)
            val leg = flyby[id]
            val visited = leg != null && leg.t <= t
            val name = cat.getJSONObject(i).getString("name")
            val sp = cat.getJSONObject(i)
            val kms = Math.sqrt(sq(sp.optLong("vx", 0)) + sq(sp.optLong("vy", 0)) + sq(sp.optLong("vz", 0))) / 1e6 * 299_792.458
            val distNow = f.distance(longArrayOf(0, 0, 0), p) / 1000.0
            val details = buildString {
                append(name.uppercase(Locale.US))
                append(String.format(Locale.US, "\nDistance from the Sun in %s: %.2f ly", yearText(t), distNow))
                append(String.format(Locale.US, "\nSpace velocity: %.0f km/s", kms))
                if (leg != null) append(String.format(Locale.US, "\nProbe flyby: %s (stop %d of %d)", yearText(leg.t),
                    focusLegs.indexOf(leg) + 1, focusLegs.size))
            }
            points += MapPoint(p[0] / 1000.0, p[1] / 1000.0, p[2] / 1000.0,
                when { leg == null -> Theme.TEXT; visited -> Theme.AMBER; else -> Theme.CRIMSON_LIGHT },
                if (leg != null) 3.2f else 1.8f, name.uppercase(Locale.US), alwaysLabel = leg != null && timeF > 0 && visited,
                glow = leg != null, info = details, key = "star$id")
        }
        // the probe
        if (focusLegs.isNotEmpty() && timeF > 0) {
            var prevT = start; var prev = longArrayOf(0, 0, 0)
            var at = ly(focusLegs.last().at)
            for (l in focusLegs) {
                if (t <= l.t) {
                    val frac = if (l.t == prevT) 1.0 else (t - prevT).toDouble() / (l.t - prevT)
                    at = doubleArrayOf((prev[0] + (l.at[0] - prev[0]) * frac) / 1000, (prev[1] + (l.at[1] - prev[1]) * frac) / 1000,
                        (prev[2] + (l.at[2] - prev[2]) * frac) / 1000)
                    break
                }
                prevT = l.t; prev = l.at
            }
            val done = focusLegs.count { it.t <= t }
            points += MapPoint(at[0], at[1], at[2], 0xFFFFFFFF.toInt(), 3.5f, "PROBE", alwaysLabel = true, glow = true,
                info = "PROBE\n${yearText(t)} · ${done} of ${focusLegs.size} flybys done\nCruising at 10% of light speed", key = "probe")
        }
        view.setScene(points, staticLines, listOf(10.0, 20.0, 30.0, 40.0), "LY")
        timeLabel.text = yearText(t)
        legend.text = legendBase
    }

    private fun sq(v: Long) = v.toDouble() * v.toDouble()
    private fun yearText(t: Long) = "YEAR " + String.format(Locale.US, "%,d", 2000 + t / 1000)

    // ---- Nebulite: orbits and missions --------------------------------

    private var focusSeq: IntArray? = null
    private var focusDays: IntArray? = null
    private var focusName = ""

    /** Compress distances (r -> sqrt(r)) so inner planets stay visible next to Neptune. */
    private fun squash(p: DoubleArray): DoubleArray {
        val r = sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
        if (r < 1e-9) return doubleArrayOf(0.0, 0.0, 0.0)
        val f = sqrt(r) / r
        return doubleArrayOf(p[0] * f, p[1] * f, p[2] * f)
    }

    private fun buildOrbits() {
        val m = model ?: return
        val live = MinerService.status.work as? TrajectoryInfo
        val ms = missions ?: JSONArray()
        val newest = if (ms.length() > 0) ms.getJSONObject(0) else null
        if (live != null) {
            focusSeq = live.seq.toIntArray(); focusDays = live.days.toIntArray(); focusName = "LIVE PLAN ${live.path}"
        } else if (newest != null && newest.optJSONArray("seq") != null) {
            val s = newest.getJSONArray("seq"); val d = newest.getJSONArray("days")
            focusSeq = IntArray(s.length()) { s.getInt(it) }; focusDays = IntArray(d.length()) { d.getInt(it) }
            focusName = "BLOCK ${newest.getInt("height")} MISSION"
        } else { focusSeq = null; focusDays = null }

        val today = System.currentTimeMillis() / 86_400_000.0 - 10957.5     // days since J2000
        val ref = focusDays?.first()?.toDouble() ?: today
        val lines = ArrayList<MapLine>()
        for (pid in m.planets.indices) lines += MapLine(m.orbitPoints(pid, ref).map { squash(it) }, Theme.MUTED, 1f, 90)
        for (i in ms.length() - 1 downTo 0) {
            val o = ms.getJSONObject(i)
            val seq = o.optJSONArray("seq") ?: continue
            val days = o.getJSONArray("days")
            val path = m.samplePath(IntArray(seq.length()) { seq.getInt(it) }, IntArray(days.length()) { days.getInt(it) }, 40)
            lines += MapLine(path.map { squash(it) }, Theme.CRIMSON, if (i == 0) 1.6f else 1f, if (i == 0) 170 else 60)
        }
        if (live != null) lines += MapLine(m.samplePath(focusSeq!!, focusDays!!, 60).map { squash(it) }, Theme.AMBER, 2.2f, 255)
        staticLines = lines
        legendBase = buildString {
            append("> REAL PLANET ORBITS (JPL ELEMENTS) · DISTANCES COMPRESSED")
            append("\n> ${ms.length()} MINED MISSIONS (CRIMSON)")
            if (newest != null) {
                val path = newest.getJSONArray("path").let { a -> (0 until a.length()).joinToString("-") { a.getString(it).take(2).uppercase(Locale.US) } }
                append(String.format(Locale.US, "\n> LATEST: BLOCK %d · %s · %.2f KM/S · %.1f YR%s",
                    newest.getInt("height"), path, newest.getDouble("dv_kms"), newest.getDouble("years"),
                    newest.optString("miner_name", "").let { if (it.isNotEmpty() && it != "null") " · BY $it" else "" }))
            }
            if (live != null) append("\n> LIVE PLAN (AMBER): ${live.path} · " +
                String.format(Locale.US, "%.2f KM/S · %.1f YR", live.dvKms, live.years))
            append(if (focusSeq != null) "\n> SLIDE TO FLY THE $focusName · TAP A PLANET FOR DETAILS"
                else "\n> TAP A PLANET FOR DETAILS · DRAG TO ROTATE · PINCH TO ZOOM")
        }
        timeRow.visibility = if (focusSeq != null) View.VISIBLE else View.GONE
    }

    private fun drawOrbitsAt() {
        val m = model ?: return
        val seq = focusSeq; val days = focusDays
        val today = System.currentTimeMillis() / 86_400_000.0 - 10957.5
        val day = if (seq != null && days != null) days.first() + (days.last() - days.first()) * timeF else today

        val points = ArrayList<MapPoint>()
        points += MapPoint(0.0, 0.0, 0.0, Theme.AMBER, 5f, "SUN", alwaysLabel = true, glow = true,
            info = "THE SUN\nPlanet positions are shown for ${dateText(day)}.", key = "sun")
        for (pid in m.planets.indices) {
            val st = m.state(pid, day)
            val p = squash(st)
            val pl = m.planets[pid]
            val r = sqrt(st[0] * st[0] + st[1] * st[1] + st[2] * st[2])
            val period = 2 * Math.PI * sqrt(pl.el[0] * pl.el[0] * pl.el[0] / m.muSun) / 365.25
            points += MapPoint(p[0], p[1], p[2], Theme.TEXT, if (pid >= 4) 3f else 2.2f,
                pl.name.uppercase(Locale.US), alwaysLabel = pid >= 2,
                info = String.format(Locale.US, "%s\nDistance from the Sun: %.2f AU on %s\nOrbit: %.2f years · eccentricity %.3f · tilt %.1f°",
                    pl.name.uppercase(Locale.US), r, dateText(day), period, pl.el[1], pl.el[2]),
                key = "planet$pid")
        }
        if (seq != null && days != null) {
            for (k in seq.indices) {
                val p = squash(m.state(seq[k], days[k].toDouble()))
                val what = when (k) { 0 -> "LAUNCH"; seq.size - 1 -> "ARRIVE"; else -> "FLYBY" }
                val name = m.planets[seq[k]].name.uppercase(Locale.US)
                points += MapPoint(p[0], p[1], p[2], if (days[k] <= day) Theme.AMBER else Theme.CRIMSON_LIGHT, 3f,
                    "$what $name ${2000 + ((days[k] + 0.5) / 365.25).toInt()}", alwaysLabel = true, glow = true,
                    info = "$what: $name\n${dateText(days[k].toDouble())} (mission day ${days[k] - days.first()})", key = "enc$k")
            }
            if (timeF > 0) m.positionAt(seq, days, day)?.let { sc ->
                val p = squash(sc)
                val r = sqrt(sc[0] * sc[0] + sc[1] * sc[1] + sc[2] * sc[2])
                points += MapPoint(p[0], p[1], p[2], 0xFFFFFFFF.toInt(), 3.5f, "SPACECRAFT", alwaysLabel = true, glow = true,
                    info = String.format(Locale.US, "SPACECRAFT\n%s · %.2f AU from the Sun\nMission day %d of %d",
                        dateText(day), r, (day - days.first()).toInt(), days.last() - days.first()), key = "craft")
            }
        }
        view.setScene(points, staticLines, emptyList(), "")
        timeLabel.text = dateText(day).substring(0, 7)
        legend.text = legendBase
    }

    /** Day number (from J2000) as "YYYY-MM". */
    private fun dateText(day: Double): String {
        val cal = java.util.Calendar.getInstance(java.util.TimeZone.getTimeZone("UTC"))
        cal.timeInMillis = ((day + 10957.5) * 86_400_000.0).toLong()
        return String.format(Locale.US, "%04d-%02d-%02d", cal.get(java.util.Calendar.YEAR),
            cal.get(java.util.Calendar.MONTH) + 1, cal.get(java.util.Calendar.DAY_OF_MONTH))
    }
}
