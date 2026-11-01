package com.example.stellariteminer

import android.app.AlertDialog
import android.content.Context
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Builds the LEDGER screen: lifetime totals per coin, then recent sessions. */
class LedgerPage(private val container: LinearLayout, private val ledger: Ledger) {
    private val ctx: Context = container.context
    private val dateFmt = SimpleDateFormat("MMM dd HH:mm", Locale.US)

    private fun dp(v: Float) = Theme.dp(ctx, v).toInt()

    fun render() {
        container.removeAllViews()
        container.addView(text("// MINING LEDGER", 10f, Theme.AMBER, spacing = 0.3f))
        container.addView(text("WHAT_YOU_MINED", 22f, Theme.CRIMSON_LIGHT, tag = "heavy", top = 4f).also { Theme.glow(it, 12f) })

        val totals = ledger.totals()
        if (totals.isEmpty()) {
            container.addView(text("> NO SESSIONS ON RECORD.\n> ENGAGE THE RIG TO START YOUR LEDGER.",
                13f, Theme.MUTED, top = 28f))
            Theme.applyFonts(container)
            return
        }

        container.addView(text("LIFETIME TOTALS", 11f, Theme.MUTED, spacing = 0.15f, top = 22f))
        totals.forEach { container.addView(coinCard(it)) }

        container.addView(text("RECENT SESSIONS", 11f, Theme.MUTED, spacing = 0.15f, top = 22f))
        ledger.sessions().take(30).forEach { container.addView(sessionRow(it)) }

        val reset = Button(ctx, null, android.R.attr.borderlessButtonStyle).apply {
            text = "[WIPE LEDGER]"
            setTextColor(Theme.CRIMSON_LIGHT)
            textSize = 12f
            letterSpacing = 0.15f
            setOnClickListener { confirmWipe() }
        }
        container.addView(reset, LinearLayout.LayoutParams(-2, dp(48f)).apply { topMargin = dp(16f) })
        Theme.applyFonts(container)
    }

    private fun coinCard(t: CoinTotals): View {
        val card = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundResource(R.drawable.cell_bg)
            setPadding(dp(14f), dp(12f), dp(14f), dp(12f))
        }
        val name = CoinProfile.byId(t.coinId).name.uppercase(Locale.US)
        val head = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        head.addView(text(name, 16f, Theme.TEXT, tag = "display"), LinearLayout.LayoutParams(0, -2, 1f))
        head.addView(text(t.ticker, 12f, Theme.AMBER, spacing = 0.15f))
        card.addView(head)

        val earned = if (t.coinId == "plsr") "${Format.coins(t.earnedUnits, t.unitsPerCoin)} ${t.ticker}"
            else "paid by your pool"
        val rows = mutableListOf(
            "TIME_MINED" to Format.duration(t.seconds),
            "HASHES" to Format.count(t.hashes),
            (if (t.coinId == "plsr") "ROUTES_MAPPED" else t.unit.uppercase(Locale.US)) to t.accepted.toString(),
            "REJECTED" to t.rejected.toString(),
            "SESSIONS" to t.sessions.toString(),
            "EARNED" to earned,
        )
        if (t.coinId == "plsr" && t.bestGainPct > 0) {
            rows.add(3, "BEST_ROUTE" to String.format(Locale.US, "%.1f%% shorter than greedy", t.bestGainPct))
        }
        rows.forEach { (k, v) -> card.addView(statRow(k, v, k == "EARNED")) }

        return card.also {
            it.layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(10f) }
        }
    }

    private fun statRow(label: String, value: String, highlight: Boolean): View =
        LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6f), 0, 0)
            addView(text(label, 11f, Theme.MUTED, spacing = 0.12f), LinearLayout.LayoutParams(0, -2, 1f))
            addView(text(value, 13f, if (highlight) Theme.AMBER else Theme.TEXT))
        }

    private fun sessionRow(s: Session): View = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(0, dp(10f), 0, dp(10f))
        val left = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            addView(text("${s.ticker}  ${dateFmt.format(Date(s.start)).uppercase(Locale.US)}", 13f, Theme.TEXT))
            addView(text("${Format.duration(s.seconds)} · ${Format.count(s.hashes)} hashes", 11f, Theme.MUTED, top = 2f))
        }
        addView(left, LinearLayout.LayoutParams(0, -2, 1f))
        val right = if (s.coinId == "plsr" && s.earnedUnits > 0)
            "+${Format.coins(s.earnedUnits, s.unitsPerCoin, 2)}" else "${s.accepted} ${s.unit}"
        addView(text(right, 13f, if (s.accepted > 0) Theme.AMBER else Theme.MUTED))
        layoutParams = LinearLayout.LayoutParams(-1, -2)
    }

    private fun confirmWipe() {
        AlertDialog.Builder(ctx)
            .setTitle("Wipe ledger?")
            .setMessage("This deletes every session and lifetime total on this phone. It doesn't affect any coins you earned.")
            .setPositiveButton("Wipe") { _, _ -> ledger.clear(); render() }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun text(s: String, size: Float, color: Int, tag: String? = null,
                     spacing: Float = 0f, top: Float = 0f): TextView =
        TextView(ctx).apply {
            text = s
            textSize = size
            setTextColor(color)
            letterSpacing = spacing
            this.tag = tag
            setLineSpacing(Theme.dp(ctx, 2f), 1f)
            if (top > 0) layoutParams = LinearLayout.LayoutParams(-2, -2).apply { topMargin = dp(top) }
        }
}
