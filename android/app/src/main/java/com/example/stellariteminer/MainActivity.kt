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
    private lateinit var alert: TextView
    private lateinit var setupGuide: TextView
    private lateinit var findNodeBtn: Button
    private var scanning = false
    private lateinit var soloMode: CheckBox
    private lateinit var walletRow: View
    private lateinit var balance: TextView
    private lateinit var soloRow: View
    private var lastBalanceCheck = 0L
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
            if (page == PAGE_RIG) refreshBalance()
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        if (!prefs.setupDone) {          // first run: the setup flow comes first
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }
        setContentView(R.layout.activity_main)
        actionBar?.hide()   // belt and braces: the theme already has no title bar

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
        alert = findViewById(R.id.alert)
        setupGuide = findViewById(R.id.setupGuide)
        findNodeBtn = findViewById(R.id.findNode)
        soloMode = findViewById(R.id.soloMode)
        walletRow = findViewById(R.id.walletRow)
        balance = findViewById(R.id.balance)
        soloRow = findViewById(R.id.soloRow)
        rigPage = findViewById(R.id.rigPage)
        ledgerPage = findViewById(R.id.ledgerPage)
        tabRig = findViewById(R.id.tabRig)
        tabLedger = findViewById(R.id.tabLedger)
        tabMap = findViewById(R.id.tabMap)
        mapPage = findViewById(R.id.mapPage)
        map = MapPage(this, findViewById(R.id.map3d), findViewById(R.id.mapTitle), findViewById(R.id.mapLegend),
            findViewById(R.id.mapInfo), findViewById(R.id.timeRow), findViewById(R.id.timeLabel), findViewById(R.id.timeSlider))
        ledger = LedgerPage(findViewById(R.id.ledgerContent), Ledger.get(filesDir)) {
            startActivity(Intent(this, SetupActivity::class.java))
        }

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
        findNodeBtn.setOnClickListener { findNode() }
        soloMode.setOnCheckedChangeListener { _, checked ->
            prefs.setSolo(prefs.coinId, checked)
            alert.visibility = View.GONE
            updateSoloUi()
            refreshBalance(force = true)
        }
        findViewById<Button>(R.id.newWallet).setOnClickListener { newWallet() }
        findViewById<Button>(R.id.sendCoins).setOnClickListener { sendCoins() }
        findViewById<Button>(R.id.backupKey).setOnClickListener { backupKey() }
        findViewById<Button>(R.id.importKey).setOnClickListener { importKey() }
        findViewById<Button>(R.id.pushChain).setOnClickListener { pushChain() }
        findViewById<Button>(R.id.resetSolo).setOnClickListener { resetSolo() }
        tabRig.setOnClickListener { showPage(PAGE_RIG) }
        tabMap.setOnClickListener { showPage(PAGE_MAP) }
        tabLedger.setOnClickListener { showPage(PAGE_LEDGER) }
        findViewById<Button>(R.id.mapRefresh).setOnClickListener { saveSettings(); map.load(prefs, force = true) }
        showPage(PAGE_RIG)
    }

    override fun onResume() {
        super.onResume()
        if (!::toggle.isInitialized) return   // finishing on first run (setup shown instead)
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        if (!::toggle.isInitialized) { super.onPause(); return }
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
        findNodeBtn.visibility = if (stratum) View.GONE else View.VISIBLE
        alert.visibility = View.GONE
        testResult.text = ""
        val own = c.kind != WorkKind.NONE
        soloMode.visibility = if (own) View.VISIBLE else View.GONE
        walletRow.visibility = if (own) View.VISIBLE else View.GONE
        soloMode.isChecked = prefs.solo(c.id)
        // fill in the app wallet's address if the field is empty
        if (own && user.text.isBlank()) prefs.wallet.address(c.addressPrefix)?.let { user.setText(it) }
        balance.text = ""
        updateSoloUi()
        refreshBalance(force = true)
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

    /** Shows a problem right under the ENGAGE button and jumps to the field that needs fixing. */
    private fun showAlert(message: String, field: View? = null) {
        alert.text = "> $message"
        alert.visibility = View.VISIBLE
        if (field is EditText) field.error = "!"
        field?.let { f ->
            f.requestFocus()
            rigPage.post { rigPage.smoothScrollTo(0, maxOf(0, alert.top - Theme.dp(this, 40f).toInt())) }
        }
    }

    private fun startMiner() {
        saveSettings()
        val c = prefs.coin
        val u = prefs.url(c.id)
        val who = prefs.user(c.id)
        val solo = prefs.isSolo
        when {
            solo && (!who.startsWith(c.addressPrefix) || who.length != c.addressLength) -> {
                showAlert("SOLO MODE needs your ${c.addressPrefix}… address in WALLET_ADDR. " +
                    "Tap [NEW WALLET] to make one on this phone.", user); return
            }
            solo -> {}
            u.isBlank() && c.protocol == Protocol.NODE -> {
                showAlert("NODE_URI is empty. Start the ${c.name} node on your computer " +
                    "(${c.nodeFolder}/node.py), then tap [FIND NODE] or type its address, " +
                    "e.g. http://192.168.40.10:${c.defaultPort}", url); return
            }
            u.isBlank() -> { showAlert("POOL_URI is empty. Copy it from your pool's setup page.", url); return }
            c.protocol == Protocol.STRATUM && !u.startsWith("stratum+") -> {
                showAlert("Pool addresses look like stratum+tcp://host:port", url); return
            }
            c.protocol == Protocol.NODE && !u.startsWith("http://") && !u.startsWith("https://") -> {
                showAlert("NODE_URI must start with http://, e.g. http://192.168.40.10:${c.defaultPort}", url); return
            }
            c.protocol == Protocol.NODE && (!who.startsWith(c.addressPrefix) || who.length != c.addressLength) -> {
                val got = if (who.isEmpty()) "is empty" else "has ${who.length} characters"
                showAlert("WALLET_ADDR $got. It needs a full ${c.addressPrefix}… address " +
                    "(${c.addressLength} characters). On your computer, in the ${c.nodeFolder} folder, run:\n" +
                    "python wallet.py new\nand paste the address it prints.", user); return
            }
            who.isBlank() -> { showAlert("WORKER is empty. Use yourPayoutAddress.workerName (see your pool's docs).", user); return }
        }
        alert.visibility = View.GONE
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
        listOf<View>(url, user, pass, threads, chargingOnly, soloMode).forEach { it.isEnabled = editable }
        chips.values.forEach { it.alpha = if (editable || it.isSelected) 1f else 0.4f }
    }

    private fun testConnection() {
        saveSettings()
        val c = prefs.coin
        if (prefs.isSolo) {
            val chain = SoloBackend.chainFor(this, c)
            testResult.text = "> SOLO CHAIN ON THIS PHONE · height ${chain.height} · nothing to ping"
            return
        }
        testResult.text = "> PINGING…"
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
                "> LINK FAILED · ${friendlyError(e, prefs.url(c.id))}"
            } finally {
                backend.close()
            }
            runOnUiThread { testResult.text = text }
        }.start()
    }

    // ---- solo mode and wallet ---------------------------------------------

    private fun updateSoloUi() {
        val c = prefs.coin
        if (c.kind == WorkKind.NONE) { soloRow.visibility = View.GONE; return }
        val solo = prefs.isSolo
        soloRow.visibility = if (solo) View.VISIBLE else View.GONE
        urlLabel.text = if (solo) "NODE_URI (optional: where [PUSH CHAIN] sends your solo chain)" else "NODE_URI"
    }

    /** Shows the balance for the address in WALLET_ADDR: from the solo chain, or from the node. */
    private fun refreshBalance(force: Boolean = false) {
        val c = prefs.coin
        val addr = user.text.toString().trim()
        if (c.kind == WorkKind.NONE || !addr.startsWith(c.addressPrefix) || addr.length != c.addressLength) {
            balance.text = ""; return
        }
        val now = System.currentTimeMillis()
        if (prefs.isSolo) {
            if (!force && now - lastBalanceCheck < 2000) return
            lastBalanceCheck = now
            val chain = SoloBackend.chainFor(this, c)
            balance.text = "> BALANCE ${Format.coins(chain.balance(addr), chain.rules.unitsPerCoin, 2)} ${c.ticker} " +
                "· solo chain height ${chain.height}"
            return
        }
        val nodeUrl = url.text.toString().trim()
        if (nodeUrl.isEmpty() || (!force && now - lastBalanceCheck < 15000)) return
        lastBalanceCheck = now
        Thread {
            val text = try {
                val (code, body) = NodeClient(nodeUrl).request("GET", "/balance/$addr", null)
                if (code == 200) "> BALANCE ${Format.coins(body.getLong("balance"), body.optLong("units_per_coin", 100_000_000L), 2)} ${c.ticker} · on node"
                else ""
            } catch (e: Exception) { "" }
            runOnUiThread { if (prefs.coin.id == c.id) balance.text = text }
        }.start()
    }

    private fun newWallet() {
        val create = {
            prefs.wallet.create()
            val c = prefs.coin
            user.setText(prefs.wallet.address(c.addressPrefix))
            user.error = null
            saveSettings()
            refreshBalance(force = true)
            backupKey(justCreated = true)
        }
        if (!prefs.wallet.hasKey()) { create(); return }
        android.app.AlertDialog.Builder(this)
            .setTitle("Replace your wallet?")
            .setMessage("This phone already has a wallet key. A new key means coins sent to the old addresses " +
                "can only be spent with the old key. Back it up first with [BACKUP KEY].")
            .setPositiveButton("Make new wallet") { _, _ -> create() }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun backupKey(justCreated: Boolean = false) {
        val key = prefs.wallet.privateKeyHex
        if (key == null) { showAlert("No wallet on this phone yet. Tap [NEW WALLET].", user); return }
        val c = prefs.coin
        val msg = (if (justCreated) "Your wallet is ready. Write this key down or store it somewhere safe: " +
            "anyone with it can spend your coins, and if you lose it the coins are gone.\n\n" else "") +
            "PRIVATE KEY\n$key\n\nPulsarite: ${Wallet.addressFor(key, Coin.ADDRESS_PREFIX)}\n" +
            "Nebulite: ${Wallet.addressFor(key, NebuliteCoin.ADDRESS_PREFIX)}\n\n" +
            "To use it on a computer, save this as wallet.json in the ${c.nodeFolder.ifEmpty { "node" }} folder:\n" +
            Wallet.walletJson(key)
        android.app.AlertDialog.Builder(this)
            .setTitle(if (justCreated) "Back up your wallet" else "Wallet key")
            .setMessage(msg)
            .setPositiveButton("Copy key") { _, _ ->
                val cm = getSystemService(android.content.ClipboardManager::class.java)
                cm.setPrimaryClip(android.content.ClipData.newPlainText("wallet key", key))
            }
            .setNegativeButton("Done", null)
            .show()
    }

    private fun importKey() {
        val input = EditText(this).apply { hint = "64 hex characters from wallet.json" }
        android.app.AlertDialog.Builder(this)
            .setTitle("Import wallet key")
            .setMessage("Paste the private_key from a wallet.json made by wallet.py. It replaces this phone's current key.")
            .setView(input)
            .setPositiveButton("Import") { _, _ ->
                if (prefs.wallet.import(input.text.toString())) {
                    user.setText(prefs.wallet.address(prefs.coin.addressPrefix))
                    saveSettings()
                    refreshBalance(force = true)
                    testResult.text = "> WALLET IMPORTED"
                } else {
                    showAlert("That isn't a valid key: it should be 64 characters of 0-9 and a-f.", user)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** Send coins to an address or a username, signed on this phone and submitted to the node. */
    private fun sendCoins() {
        saveSettings()
        val c = prefs.coin
        if (!prefs.wallet.hasKey()) { showAlert("Make or import a wallet first ([NEW WALLET] or [IMPORT KEY]).", user); return }
        if (prefs.isSolo) {
            showAlert("Solo chains only hold mined blocks. To send ${c.ticker}, push your solo chain to a node " +
                "([PUSH CHAIN TO NODE]), turn SOLO MODE off, then send.", soloMode); return
        }
        val nodeUrl = prefs.url(c.id)
        if (nodeUrl.isBlank()) { showAlert("Sending needs a node: set NODE_URI first.", url); return }
        val me = prefs.wallet.address(c.addressPrefix)!!
        val d = resources.displayMetrics.density
        val form = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((20 * d).toInt(), (8 * d).toInt(), (20 * d).toInt(), 0)
        }
        val to = EditText(this).apply { hint = "Username or ${c.addressPrefix}… address" }
        val amount = EditText(this).apply { hint = "Amount (${c.ticker})"; inputType = 0x2002 }  // decimal number
        val fee = EditText(this).apply { setText("0.00001"); hint = "Fee (${c.ticker})"; inputType = 0x2002 }
        listOf(to, amount, fee).forEach { form.addView(it) }
        android.app.AlertDialog.Builder(this)
            .setTitle("Send ${c.ticker}")
            .setMessage("From $me")
            .setView(form)
            .setPositiveButton("Send") { _, _ ->
                val amt = toUnits(amount.text.toString()); val f = toUnits(fee.text.toString())
                val dest = to.text.toString().trim()
                if (amt == null || amt <= 0 || f == null || f < 1000 || dest.isEmpty()) {
                    showAlert("Check the send form: a recipient, an amount above 0 and a fee of at least 0.00001.", user)
                    return@setPositiveButton
                }
                testResult.text = "> SENDING…"
                Thread {
                    val msg = try { submitTransfer(nodeUrl, c, me, dest, amt, f) } catch (e: Exception) {
                        "SEND FAILED · ${friendlyError(e, nodeUrl)}"
                    }
                    runOnUiThread { testResult.text = "> $msg"; refreshBalance(force = true) }
                }.start()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun toUnits(text: String): Long? = try {
        java.math.BigDecimal(text.trim()).movePointRight(8).longValueExact()
    } catch (e: Exception) { null }

    /** Resolves the recipient, signs, and posts the transaction. Runs off the main thread. */
    private fun submitTransfer(nodeUrl: String, c: CoinProfile, me: String, dest: String, amt: Long, fee: Long): String {
        val http = NodeClient(nodeUrl)
        val toAddr = if (Wallet.isValidAddress(dest, c.addressPrefix)) dest else {
            val (code, body) = http.request("GET", "/name/" + java.net.URLEncoder.encode(dest.uppercase(Locale.US), "UTF-8"), null)
            if (code != 200) return "SEND FAILED · ${body.optString("error", "unknown recipient $dest")}"
            body.getString("address")
        }
        val (bc, bal) = http.request("GET", "/balance/$me", null)
        if (bc != 200) return "SEND FAILED · couldn't read your balance from the node"
        if (bal.getLong("balance") < amt + fee) {
            return "SEND FAILED · not enough ${c.ticker}: you have ${Format.coins(bal.getLong("balance"), 100_000_000L, 8)}"
        }
        val tx = prefs.wallet.signTransaction(toAddr, amt, fee, bal.getLong("next_nonce"))
        val (code, body) = http.request("POST", "/tx", tx)
        return if (code == 200 && body.optBoolean("ok")) {
            "SENT ${Format.coins(amt, 100_000_000L, 8)} ${c.ticker} to ${if (toAddr == dest) dest.take(14) + "…" else dest.uppercase(Locale.US)}. " +
                "It's final once the next block is mined. txid ${body.optString("txid").take(12)}…"
        } else "SEND FAILED · ${body.optString("error", "HTTP $code")}"
    }

    private fun pushChain() {
        saveSettings()
        val c = prefs.coin
        val nodeUrl = prefs.url(c.id)
        if (nodeUrl.isBlank()) {
            showAlert("Set NODE_URI to the node that should receive your solo chain (tap [FIND NODE] " +
                "or use your cloud address), then tap [PUSH CHAIN] again.", url); return
        }
        val chain = SoloBackend.chainFor(this, c)
        testResult.text = "> PUSHING ${chain.height} BLOCKS TO $nodeUrl…"
        Thread {
            val text = try { "> " + SoloBackend.push(chain, nodeUrl) } catch (e: Exception) { "> PUSH FAILED · ${friendlyError(e, nodeUrl)}" }
            runOnUiThread { testResult.text = text }
        }.start()
    }

    private fun resetSolo() {
        val c = prefs.coin
        android.app.AlertDialog.Builder(this)
            .setTitle("Reset solo chain?")
            .setMessage("This deletes the ${c.name} blocks mined in solo mode on this phone, and the coins in them. " +
                "Push the chain to a node first if you want to keep them.")
            .setPositiveButton("Reset") { _, _ ->
                SoloBackend.chainFor(this, c).reset()
                refreshBalance(force = true)
                testResult.text = "> SOLO CHAIN RESET"
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** Scans the phone's Wi-Fi network for the selected coin's node and fills in NODE_URI. */
    private fun findNode() {
        val c = prefs.coin
        if (scanning || c.protocol != Protocol.NODE) return
        val mine = NodeFinder.localAddresses()
        if (mine.isEmpty()) {
            testResult.text = "> NO WI-FI ADDRESS. Connect the phone to the same Wi-Fi as the computer running the node."
            return
        }
        scanning = true
        findNodeBtn.isEnabled = false
        val port = NodeFinder.port(url.text.toString(), c.defaultPort)
        testResult.text = "> SCANNING FOR ${c.name.uppercase(Locale.US)} NODES ON PORT $port…"
        Thread {
            val found = NodeFinder.scan(c.name, port) { net ->
                runOnUiThread { testResult.text = "> SCANNING $net FOR ${c.name.uppercase(Locale.US)} NODES ON PORT $port…" }
            }
            runOnUiThread {
                scanning = false
                findNodeBtn.isEnabled = true
                if (found.isNotEmpty()) {
                    url.setText(found[0])
                    url.error = null
                    saveSettings()
                    alert.visibility = View.GONE
                    testResult.text = "> FOUND ${found.size} NODE${if (found.size > 1) "S" else ""} · using ${found[0]}"
                } else {
                    testResult.text = "> NO ${c.name.uppercase(Locale.US)} NODE FOUND on your Wi-Fi (phone is ${mine.joinToString()}).\n" +
                        "> On the computer: cd ${c.nodeFolder} && python node.py. It prints the address to use.\n" +
                        "> Windows may ask to allow Python through the firewall: allow it on private networks."
                }
            }
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

    /** Step-by-step help until the selected own coin has a node address and wallet. */
    private fun updateSetupGuide(running: Boolean) {
        val c = prefs.coin
        if (running || c.protocol != Protocol.NODE) { setupGuide.visibility = View.GONE; return }
        val haveUrl = url.text.isNotBlank()
        val haveAddr = user.text.startsWith(c.addressPrefix) && user.text.length == c.addressLength
        if (prefs.isSolo) {
            if (haveAddr) { setupGuide.visibility = View.GONE; return }
            setupGuide.text = "// SOLO SETUP ${c.name.uppercase(Locale.US)}\n[✓] SOLO MODE on: the blockchain runs on this phone\n" +
                "[ ] Tap [NEW WALLET] below to create your address\n[ ] Tap ENGAGE RIG"
            setupGuide.visibility = View.VISIBLE
            return
        }
        if (haveUrl && haveAddr) { setupGuide.visibility = View.GONE; return }
        fun step(done: Boolean, text: String) = (if (done) "[✓] " else "[ ] ") + text
        setupGuide.text = "// SETUP ${c.name.uppercase(Locale.US)} · or tick SOLO MODE to skip the computer\n" +
            step(haveUrl, "On your computer: cd ${c.nodeFolder} && python node.py") + "\n" +
            step(haveUrl, "Tap [FIND NODE] below (same Wi-Fi), or type the address node.py prints") + "\n" +
            step(haveAddr, "Tap [NEW WALLET] (or paste an address from wallet.py)") + "\n" +
            "[ ] Tap ENGAGE RIG"
        setupGuide.visibility = View.VISIBLE
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
        val problem = running && (s.pausedReason != null || s.message.startsWith("LINK_ERROR") ||
            s.message.startsWith("REJECTED"))
        state.text = "> " + when {
            !running -> "RIG_IDLE"
            s.pausedReason == "NOT_CHARGING" -> "PAUSED: NOT CHARGING. Plug in, or untick CHARGING ONLY."
            s.pausedReason == "BATTERY_LOW" -> "PAUSED: BATTERY BELOW 20%. Plug in to continue."
            s.pausedReason == "THERMAL_LIMIT" -> "PAUSED: PHONE TOO HOT. Resumes when it cools."
            s.pausedReason != null -> "PAUSED: ${s.pausedReason}"
            else -> s.message
        }
        state.setTextColor(if (problem) Theme.CRIMSON_LIGHT else Theme.AMBER)
        updateSetupGuide(running)
        val w = s.work
        if (running && w != null && prefs.coin.protocol == Protocol.NODE) {
            route.visibility = View.VISIBLE
            route.text = w.summary
        } else {
            route.visibility = View.GONE
        }
        block.text = if (s.height > 0) "BLK#%05d".format(s.height % 100_000) else "BLK#—"
        val op = prefs.username.ifEmpty { "—" }
        sysStatus.text = if (running) "OP $op\nLINK ▲ ${s.ticker}" else "OP $op\nLINK —"
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
