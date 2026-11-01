package com.example.stellariteminer

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import java.util.Locale

class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var hashrate: TextView
    private lateinit var hashUnit: TextView
    private lateinit var state: TextView
    private lateinit var block: TextView
    private lateinit var route: TextView
    private lateinit var sysStatus: TextView
    private lateinit var foundLabel: TextView
    private lateinit var found: TextView
    private lateinit var rejected: TextView
    private lateinit var thirdLabel: TextView
    private lateinit var third: TextView
    private lateinit var toggle: Button
    private lateinit var toggleBg: ChamferDrawable
    private lateinit var rings: PulseRingView
    private lateinit var coinChips: LinearLayout
    private lateinit var coinNote: TextView
    private lateinit var urlLabel: TextView
    private lateinit var url: EditText
    private lateinit var userLabel: TextView
    private lateinit var user: EditText
    private lateinit var passGroup: View
    private lateinit var pass: EditText
    private lateinit var threads: SeekBar
    private lateinit var threadsLabel: TextView
    private lateinit var chargingOnly: CheckBox
    private lateinit var testResult: TextView
    private lateinit var rigPage: ScrollView
    private lateinit var ledgerPage: ScrollView
    private lateinit var ledger: LedgerPage
    private lateinit var tabRig: Button
    private lateinit var tabLedger: Button
    private lateinit var tabMap: Button
    private lateinit var mapPage: View
    private lateinit var map: MapPage

    private var page = PAGE_RIG
    private val showingLedger get() = page == PAGE_LEDGER
    private var lastLedgerRender = 0L
    private val chips = mutableMapOf<String, TextView>()

    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            render(MinerService.status)
            if (showingLedger && System.currentTimeMillis() - lastLedgerRender > 5000) renderLedger()
            if (page == PAGE_MAP) map.refreshLive()
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        hashrate = findViewById(R.id.hashrate)
        hashUnit = findViewById(R.id.hashUnit)
        state = findViewById(R.id.state)
        block = findViewById(R.id.block)
        route = findViewById(R.id.route)
        sysStatus = findViewById(R.id.sysStatus)
        foundLabel = findViewById(R.id.foundLabel)
        found = findViewById(R.id.found)
        rejected = findViewById(R.id.rejected)
        thirdLabel = findViewById(R.id.thirdLabel)
        third = findViewById(R.id.third)
        toggle = findViewById(R.id.toggle)
        rings = findViewById(R.id.rings)
        coinChips = findViewById(R.id.coinChips)
        coinNote = findViewById(R.id.coinNote)
        urlLabel = findViewById(R.id.urlLabel)
        url = findViewById(R.id.url)
        userLabel = findViewById(R.id.userLabel)
        user = findViewById(R.id.user)
        passGroup = findViewById(R.id.passGroup)
        pass = findViewById(R.id.pass)
        threads = findViewById(R.id.threads)
        threadsLabel = findViewById(R.id.threadsLabel)
        chargingOnly = findViewById(R.id.chargingOnly)
        testResult = findViewById(R.id.testResult)
        rigPage = findViewById(R.id.rigPage)
        ledgerPage = findViewById(R.id.ledgerPage)
        tabRig = findViewById(R.id.tabRig)
        tabLedger = findViewById(R.id.tabLedger)
        tabMap = findViewById(R.id.tabMap)
        mapPage = findViewById(R.id.mapPage)
        map = MapPage(this, findViewById(R.id.map3d), findViewById(R.id.mapTitle), findViewById(R.id.mapLegend))
        ledger = LedgerPage(findViewById(R.id.ledgerContent), Ledger.get(filesDir))

        Theme.applyFonts(window.decorView)
        findViewById<Map3DView>(R.id.map3d).setTypeface(Theme.monoTypeface(this))
        Theme.glow(findViewById(R.id.title), 12f)
        Theme.glow(hashrate, 18f)

        toggleBg = ChamferDrawable(resources.displayMetrics.density, filled = true)
        toggle.background = toggleBg
        if (Build.VERSION.SDK_INT >= 28) {
            toggle.outlineSpotShadowColor = Theme.CRIMSON
            toggle.outlineAmbientShadowColor = Theme.CRIMSON
        }

        buildCoinChips()
        loadCoinFields()
        chargingOnly.isChecked = prefs.chargingOnly
        threads.max = Prefs.maxThreads() - 1
        threads.progress = prefs.threads - 1
        updateThreadsLabel()
        threads.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, fromUser: Boolean) = updateThreadsLabel()
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })

        toggle.setOnClickListener { if (MinerService.status.running) stopMiner() else startMiner() }
        findViewById<Button>(R.id.test).setOnClickListener { testConnection() }
        tabRig.setOnClickListener { showPage(PAGE_RIG) }
        tabMap.setOnClickListener { showPage(PAGE_MAP) }
        tabLedger.setOnClickListener { showPage(PAGE_LEDGER) }
        findViewById<Button>(R.id.mapRefresh).setOnClickListener { saveSettings(); map.load(prefs, force = true) }
        showPage(PAGE_RIG)
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        saveSettings()
        super.onPause()
    }

    // ---- coins --------------------------------------------------------

    private fun buildCoinChips() {
        val d = resources.displayMetrics.density
        CoinProfile.ALL.forEach { c ->
            val chip = TextView(this).apply {
                text = c.ticker
                textSize = 13f
                letterSpacing = 0.15f
                tag = "display"
                minHeight = (44 * d).toInt()
                gravity = android.view.Gravity.CENTER
                setPadding((16 * d).toInt(), 0, (16 * d).toInt(), 0)
                contentDescription = c.name
                isClickable = true
                isFocusable = true
                setOnClickListener { selectCoin(c.id) }
            }
            chips[c.id] = chip
            coinChips.addView(chip, LinearLayout.LayoutParams(-2, -2).apply { marginEnd = (8 * d).toInt() })
        }
        Theme.applyFonts(coinChips)
        styleChips()
    }

    private fun styleChips() {
        val d = resources.displayMetrics.density
        chips.forEach { (id, chip) ->
            val selected = id == prefs.coinId
            chip.background = GradientDrawable().apply {
                setColor(if (selected) Theme.CRIMSON else Theme.PANEL)
                setStroke((1 * d).toInt(), if (selected) Theme.CRIMSON else Theme.CRIMSON_DIM)
            }
            chip.setTextColor(if (selected) 0xFFFFFFFF.toInt() else Theme.MUTED)
            chip.isSelected = selected
        }
    }

    private fun selectCoin(id: String) {
        if (MinerService.status.running || id == prefs.coinId) return
        saveSettings()
        prefs.coinId = id
        styleChips()
        loadCoinFields()
    }

    private fun loadCoinFields() {
        val c = prefs.coin
        val stratum = c.protocol == Protocol.STRATUM
        urlLabel.text = if (stratum) "POOL_URI" else "NODE_URI"
        url.hint = c.urlHint
        url.setText(prefs.url(c.id))
        userLabel.text = c.userLabel
        user.hint = c.userHint
        user.setText(prefs.user(c.id))
        pass.setText(prefs.password(c.id))
        passGroup.visibility = if (stratum) View.VISIBLE else View.GONE
        val algo = when (c.kind) {
            WorkKind.STAR_ROUTES -> "STAR ROUTES + SHA-256d"
            WorkKind.TRAJECTORIES -> "TRAJECTORIES + SHA-256d"
            WorkKind.NONE -> "SHA-256d"
        }
        coinNote.text = "> ${c.name.uppercase(Locale.US)} · $algo\n${c.note}"
        foundLabel.text = if (stratum) "SHARES" else "BLOCKS"
        thirdLabel.text = if (stratum) "UPTIME" else c.ticker
    }

    private fun saveSettings() {
        val id = prefs.coinId
        prefs.setUrl(id, url.text.toString())
        prefs.setUser(id, user.text.toString())
        prefs.setPassword(id, pass.text.toString())
        prefs.threads = threads.progress + 1
        prefs.chargingOnly = chargingOnly.isChecked
    }

    private fun updateThreadsLabel() {
        threadsLabel.text = "CORES [${threads.progress + 1}/${Prefs.maxThreads()}]"
    }

    // ---- mining -------------------------------------------------------

    private fun startMiner() {
        saveSettings()
        val c = prefs.coin
        when {
            prefs.url(c.id).isBlank() -> { url.error = "Enter the ${if (c.protocol == Protocol.STRATUM) "pool" else "node"} address"; return }
            c.protocol == Protocol.STRATUM && !prefs.url(c.id).startsWith("stratum+") -> {
                url.error = "Pool addresses look like stratum+tcp://host:port"; return
            }
            c.protocol == Protocol.NODE && (!prefs.user(c.id).startsWith(c.addressPrefix) ||
                prefs.user(c.id).length != c.addressLength) -> {
                user.error = "Paste the ${c.addressPrefix}… address printed by: python wallet.py new"; return
            }
            prefs.user(c.id).isBlank() -> { user.error = "Enter your worker name"; return }
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            // The status notification is how you see and stop mining while the app is closed.
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        startForegroundService(Intent(this, MinerService::class.java).setAction(MinerService.ACTION_START))
        setEditable(false)
    }

    private fun stopMiner() {
        startService(Intent(this, MinerService::class.java).setAction(MinerService.ACTION_STOP))
        setEditable(true)
    }

    private fun setEditable(editable: Boolean) {
        listOf<View>(url, user, pass, threads, chargingOnly).forEach { it.isEnabled = editable }
        chips.values.forEach { it.alpha = if (editable || it.isSelected) 1f else 0.4f }
    }

    private fun testConnection() {
        saveSettings()
        testResult.text = "> PINGING…"
        val c = prefs.coin
        val backend = prefs.backend()
        Thread {
            val text = try {
                if (backend is NodeClient || backend is NebuliteClient) {
                    val info = if (backend is NodeClient) backend.info() else (backend as NebuliteClient).info()
                    "> LINK OK · ${info.optString("coin")} node · height ${info.optLong("height")}"
                } else {
                    val job = backend.getWork()
                    "> LINK OK · pool sent work" + if (job.height > 0) " for block ${job.height}" else ""
                }
            } catch (e: Exception) {
                "> LINK FAILED · ${e.message ?: e.javaClass.simpleName}"
            } finally {
                backend.close()
            }
            runOnUiThread { testResult.text = text }
        }.start()
    }

    // ---- pages --------------------------------------------------------

    private fun showPage(p: Int) {
        page = p
        rigPage.visibility = if (p == PAGE_RIG) View.VISIBLE else View.GONE
        mapPage.visibility = if (p == PAGE_MAP) View.VISIBLE else View.GONE
        ledgerPage.visibility = if (p == PAGE_LEDGER) View.VISIBLE else View.GONE
        tabRig.setTextColor(if (p == PAGE_RIG) Theme.CRIMSON_LIGHT else Theme.MUTED)
        tabMap.setTextColor(if (p == PAGE_MAP) Theme.CRIMSON_LIGHT else Theme.MUTED)
        tabLedger.setTextColor(if (p == PAGE_LEDGER) Theme.CRIMSON_LIGHT else Theme.MUTED)
        if (p == PAGE_LEDGER) renderLedger()
        if (p == PAGE_MAP) { saveSettings(); map.load(prefs) }
    }

    private fun renderLedger() {
        lastLedgerRender = System.currentTimeMillis()
        ledger.render()
    }

    private fun render(s: MinerStatus) {
        val running = s.running
        toggle.text = getString(if (running) R.string.stop else R.string.start)
        toggleBg.filled = !running
        toggle.invalidate()
        toggle.elevation = if (running) 0f else Theme.dp(this, 8f)
        setEditable(!running)
        rings.active = running && s.pausedReason == null

        val (num, unit) = Format.rateParts(s.hashrate)
        hashrate.text = num
        hashUnit.text = unit
        state.text = "> " + when {
            !running -> "RIG_IDLE"
            s.pausedReason != null -> "PAUSED: ${s.pausedReason}"
            else -> s.message
        }
        val w = s.work
        if (running && w != null && prefs.coin.protocol == Protocol.NODE) {
            route.visibility = View.VISIBLE
            route.text = w.summary
        } else {
            route.visibility = View.GONE
        }
        block.text = if (s.height > 0) "BLK#%05d".format(s.height % 100_000) else "BLK#—"
        sysStatus.text = if (running) "SYS.OK\nLINK ▲ ${s.ticker}" else "SYS.OK\nLINK —"
        found.text = "%02d".format(s.accepted)
        rejected.text = "%02d".format(s.rejected)
        if (prefs.coin.protocol == Protocol.STRATUM) {
            val up = if (running && s.startedAt > 0) (System.currentTimeMillis() - s.startedAt) / 1000 else 0
            // HH:MM once past an hour, MM:SS before that
            third.text = if (up >= 3600) Format.clock(up).substring(0, 5) else Format.clock(up).substring(3)
        } else {
            third.text = Format.coins(s.earnedUnits, s.unitsPerCoin, 1)
        }
    }

    companion object {
        private const val PAGE_RIG = 0
        private const val PAGE_MAP = 1
        private const val PAGE_LEDGER = 2
    }
}
