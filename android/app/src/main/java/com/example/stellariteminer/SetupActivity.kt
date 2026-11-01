package com.example.stellariteminer

import android.app.Activity
import android.content.Intent
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.Locale

/**
 * First-run setup: welcome → username → wallet (with a backup check) → where to
 * mine → done. Can be run again from the LEDGER tab.
 */
class SetupActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var body: LinearLayout
    private var step = 0
    private var mode = "solo"                 // solo | computer | cloud
    private var cloudUrl = ""

    private val d get() = resources.displayMetrics.density
    private fun dp(v: Float) = (v * d).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        actionBar?.hide()
        prefs = Prefs(this)
        val root = FrameLayout(this).apply { setBackgroundColor(Theme.BLACK); fitsSystemWindows = true }
        val scroll = ScrollView(this)
        body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24f), dp(28f), dp(24f), dp(28f))
        }
        scroll.addView(body)
        root.addView(scroll)
        root.addView(ScanlineView(this))
        setContentView(root)
        show(0)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (step > 0) show(step - 1) else super.onBackPressed()
    }

    // ---- building blocks ------------------------------------------------

    private fun text(s: String, size: Float, color: Int = Theme.TEXT, tag: String? = null, top: Float = 0f) =
        TextView(this).apply {
            text = s; textSize = size; setTextColor(color); this.tag = tag
            setLineSpacing(dp(3f).toFloat(), 1f)
            layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(top) }
        }

    private fun header(kicker: String, title: String) {
        body.addView(text("// $kicker", 10f, Theme.AMBER).apply { letterSpacing = 0.3f })
        body.addView(text(title, 26f, Theme.CRIMSON_LIGHT, "heavy", 6f).apply { Theme.glow(this, 12f) })
        body.addView(text("STEP ${step + 1} OF 5", 10f, Theme.MUTED, top = 4f).apply { letterSpacing = 0.2f })
    }

    private fun primary(label: String, enabled: Boolean = true, onClick: () -> Unit) = Button(this).apply {
        text = label; tag = "display"; textSize = 15f; letterSpacing = 0.18f
        setTextColor(0xFFFFFFFF.toInt())
        background = ChamferDrawable(d, filled = true)
        isEnabled = enabled; alpha = if (enabled) 1f else 0.4f
        stateListAnimator = null
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(-1, dp(56f)).apply { topMargin = dp(24f) }
    }

    private fun secondary(label: String, onClick: () -> Unit) =
        Button(this, null, android.R.attr.borderlessButtonStyle).apply {
            text = label; textSize = 12f; letterSpacing = 0.15f; setTextColor(Theme.AMBER)
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(-1, dp(48f)).apply { topMargin = dp(6f) }
        }

    private fun field(hint: String, initial: String = "") = EditText(this).apply {
        this.hint = hint; setText(initial); textSize = 16f; setTextColor(Theme.TEXT)
        setBackgroundResource(R.drawable.field_bg); setPadding(dp(6f), 0, dp(6f), 0)
        layoutParams = LinearLayout.LayoutParams(-1, dp(52f)).apply { topMargin = dp(16f) }
    }

    private fun card(title: String, detail: String, selected: Boolean, onClick: () -> Unit) =
        LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14f), dp(12f), dp(14f), dp(12f))
            background = GradientDrawable().apply {
                setColor(if (selected) 0xFF1A0509.toInt() else Theme.PANEL)
                setStroke(dp(if (selected) 2f else 1f), if (selected) Theme.CRIMSON else Theme.CRIMSON_DIM)
            }
            isClickable = true; isFocusable = true
            setOnClickListener { onClick() }
            addView(text((if (selected) "◉ " else "○ ") + title, 15f, if (selected) Theme.CRIMSON_LIGHT else Theme.TEXT, "display"))
            addView(text(detail, 12f, Theme.MUTED, top = 4f))
            layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12f) }
        }

    private fun show(s: Int) {
        step = s
        body.removeAllViews()
        when (s) {
            0 -> welcome()
            1 -> username()
            2 -> wallet()
            3 -> whereToMine()
            else -> done()
        }
        Theme.applyFonts(body)
        (body.parent as? ScrollView)?.scrollTo(0, 0)
    }

    // ---- steps ----------------------------------------------------------

    private fun welcome() {
        header("STELLARITE CORP", "WELCOME,\nOPERATOR")
        body.addView(text("Stellarite Miner mines two coins whose mining does useful space work:", 14f, top = 20f))
        body.addView(text("◆ PULSARITE: plot probe routes between real, moving nearby stars.\n" +
            "◆ NEBULITE: plan gravity-assist missions to the outer planets.", 14f, Theme.TEXT, top = 10f))
        body.addView(text("Setup takes about a minute: a username, a wallet, and where your blockchain runs.", 13f, Theme.MUTED, top = 14f))
        body.addView(primary("BEGIN") { show(1) })
    }

    private fun username() {
        header("IDENTITY", "PICK A\nUSERNAME")
        body.addView(text("Your username is written into the blocks you mine. The first block you mine claims it " +
            "on that network, and nobody else can use it there. People can send you coins by name.", 13f, top = 16f))
        val status = text("", 12f, Theme.MUTED, top = 8f)
        val next = primary("NEXT", false) {}
        val input = field("NOVA_7", prefs.username)
        input.inputType = 0x00001001   // text, all caps
        fun check() {
            val v = input.text.toString().trim().uppercase(Locale.US)
            val ok = Regex("^[A-Z0-9_]{3,16}$").matches(v)
            status.text = if (v.isEmpty()) "3-16 characters: A-Z, 0-9 and _"
                else if (ok) "✓ $v looks good" else "Use 3-16 characters: A-Z, 0-9 and _ (no spaces)"
            status.setTextColor(if (ok) Theme.AMBER else Theme.MUTED)
            next.isEnabled = ok; next.alpha = if (ok) 1f else 0.4f
        }
        input.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun afterTextChanged(e: Editable?) = check()
        })
        next.setOnClickListener { prefs.username = input.text.toString(); show(2) }
        body.addView(input); body.addView(status); body.addView(next)
        body.addView(secondary("[SKIP FOR NOW]") { prefs.username = ""; show(2) })
        check()
    }

    private fun wallet() {
        header("WALLET", "SECURE YOUR\nCOINS")
        val key = prefs.wallet.privateKeyHex
        if (key == null) {
            body.addView(text("Your wallet is a secret key on this phone. One key gives you a Pulsarite " +
                "address and a Nebulite address.", 13f, top = 16f))
            body.addView(primary("CREATE NEW WALLET") { prefs.wallet.create(); walletBackup() })
            body.addView(secondary("[I HAVE A KEY: IMPORT IT]") { walletImport() })
            return
        }
        body.addView(text("This phone already has a wallet:", 13f, top = 16f))
        body.addView(text("PLSR  ${Wallet.addressFor(key, Coin.ADDRESS_PREFIX)}\nNBLT  ${Wallet.addressFor(key, NebuliteCoin.ADDRESS_PREFIX)}",
            11f, Theme.AMBER, top = 8f))
        body.addView(primary("KEEP THIS WALLET") { walletBackup() })
        body.addView(secondary("[IMPORT A DIFFERENT KEY]") { walletImport() })
    }

    private fun walletImport() {
        body.removeAllViews()
        header("WALLET", "IMPORT\nYOUR KEY")
        body.addView(text("Paste the private_key from a wallet.json made by wallet.py, or a key backed up from this app.", 13f, top = 16f))
        val input = field("64 characters, 0-9 and a-f")
        val status = text("", 12f, Theme.CRIMSON_LIGHT, top = 8f)
        body.addView(input); body.addView(status)
        body.addView(primary("IMPORT") {
            if (prefs.wallet.import(input.text.toString())) walletBackup(skipCheck = true)
            else status.text = "That isn't a valid key: it should be 64 characters of 0-9 and a-f."
        })
        body.addView(secondary("[BACK]") { show(2) })
        Theme.applyFonts(body)
    }

    private fun walletBackup(skipCheck: Boolean = false) {
        body.removeAllViews()
        header("WALLET", "BACK UP\nYOUR KEY")
        val key = prefs.wallet.privateKeyHex!!
        body.addView(text("Write this key down or store it in a password manager. Anyone with it can spend your " +
            "coins; if you lose it, the coins are gone. It also restores your username, since names belong to your address.", 13f, top = 16f))
        body.addView(text(key.chunked(16).joinToString("\n"), 16f, Theme.AMBER, top = 14f).apply {
            setBackgroundResource(R.drawable.cell_bg); setPadding(dp(12f), dp(12f), dp(12f), dp(12f))
            setTextIsSelectable(true)
        })
        body.addView(secondary("[COPY KEY]") {
            getSystemService(android.content.ClipboardManager::class.java)
                .setPrimaryClip(android.content.ClipData.newPlainText("wallet key", key))
        })
        if (skipCheck) {
            body.addView(primary("NEXT") { show(3) })
        } else {
            body.addView(text("To confirm you saved it, type the LAST 4 characters of your key:", 13f, top = 10f))
            val next = primary("NEXT", false) { show(3) }
            val input = field("last 4 characters")
            input.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun afterTextChanged(e: Editable?) {
                    val ok = e.toString().trim().lowercase(Locale.US) == key.takeLast(4)
                    next.isEnabled = ok; next.alpha = if (ok) 1f else 0.4f
                }
            })
            body.addView(input); body.addView(next)
        }
        Theme.applyFonts(body)
    }

    private fun whereToMine() {
        header("NETWORK", "WHERE DOES YOUR\nBLOCKCHAIN RUN?")
        body.addView(text("Your phone does the mining. The blockchain (the record of who owns what) has to live somewhere:", 13f, top = 16f))
        val cloudField = field("https://your-domain (optional)", cloudUrl)
        fun render() = show(3)
        body.addView(card("SOLO: ON THIS PHONE", "No computer needed. Best for trying it out. Push your chain to a node later.",
            mode == "solo") { mode = "solo"; render() })
        body.addView(card("MY COMPUTER", "Run start-nebulite / start-pulsarite on a computer on your Wi-Fi, then tap [FIND NODE].",
            mode == "computer") { mode = "computer"; render() })
        body.addView(card("CLOUD SERVER", "Mine from anywhere and invite friends. See DEPLOY.md to set one up.",
            mode == "cloud") { mode = "cloud"; render() })
        if (mode == "cloud") {
            body.addView(text("Your server's address (we'll use /pulsarite and /nebulite on it):", 12f, Theme.MUTED, top = 12f))
            body.addView(cloudField)
        }
        body.addView(primary("NEXT") {
            cloudUrl = cloudField.text.toString().trim().trimEnd('/')
            show(4)
        })
    }

    private fun done() {
        header("READY", "SETUP\nCOMPLETE")
        val key = prefs.wallet.privateKeyHex
        val name = prefs.username.ifEmpty { "(none yet)" }
        val where = when (mode) {
            "solo" -> "Solo mode on this phone"
            "computer" -> "Your computer (tap [FIND NODE] on the RIG tab)"
            else -> if (cloudUrl.isNotEmpty()) "Cloud: $cloudUrl" else "Cloud (set NODE_URI on the RIG tab)"
        }
        body.addView(text("OPERATOR  $name\nNETWORK   $where", 13f, Theme.TEXT, top = 18f))
        if (key != null) body.addView(text("PLSR  ${Wallet.addressFor(key, Coin.ADDRESS_PREFIX)}\nNBLT  " +
            Wallet.addressFor(key, NebuliteCoin.ADDRESS_PREFIX), 11f, Theme.AMBER, top = 10f))
        body.addView(text("Tap ENGAGE RIG to start. Your username is claimed when your first block is mined.", 13f, Theme.MUTED, top = 14f))
        body.addView(primary("ENTER THE RIG") { finishSetup() })
    }

    private fun finishSetup() {
        val key = prefs.wallet.privateKeyHex
        for (c in CoinProfile.ALL.filter { it.kind != WorkKind.NONE }) {
            if (key != null) prefs.setUser(c.id, Wallet.addressFor(key, c.addressPrefix))
            prefs.setSolo(c.id, mode == "solo")
            if (mode == "cloud" && cloudUrl.isNotEmpty()) {
                prefs.setUrl(c.id, cloudUrl + if (c.kind == WorkKind.STAR_ROUTES) "/pulsarite" else "/nebulite")
            }
        }
        prefs.setupDone = true
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
        finish()
    }
}
