package com.example.stellariteminer

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.SeekBar
import android.widget.TextView
import java.util.Locale

class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var hashrate: TextView
    private lateinit var state: TextView
    private lateinit var stats: TextView
    private lateinit var toggle: Button
    private lateinit var nodeUrl: EditText
    private lateinit var address: EditText
    private lateinit var threads: SeekBar
    private lateinit var threadsLabel: TextView
    private lateinit var chargingOnly: CheckBox
    private lateinit var testResult: TextView

    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            render(MinerService.status)
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        hashrate = findViewById(R.id.hashrate)
        state = findViewById(R.id.state)
        stats = findViewById(R.id.stats)
        toggle = findViewById(R.id.toggle)
        nodeUrl = findViewById(R.id.nodeUrl)
        address = findViewById(R.id.address)
        threads = findViewById(R.id.threads)
        threadsLabel = findViewById(R.id.threadsLabel)
        chargingOnly = findViewById(R.id.chargingOnly)
        testResult = findViewById(R.id.testResult)

        nodeUrl.setText(prefs.nodeUrl)
        address.setText(prefs.address)
        chargingOnly.isChecked = prefs.chargingOnly
        threads.max = Prefs.maxThreads() - 1
        threads.progress = prefs.threads - 1
        updateThreadsLabel()
        threads.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, fromUser: Boolean) = updateThreadsLabel()
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })

        toggle.setOnClickListener {
            if (MinerService.status.running) stopMiner() else startMiner()
        }
        findViewById<Button>(R.id.test).setOnClickListener { testConnection() }
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

    private fun updateThreadsLabel() {
        threadsLabel.text = getString(R.string.threads) + ": ${threads.progress + 1} of ${Prefs.maxThreads()}"
    }

    private fun saveSettings() {
        prefs.nodeUrl = nodeUrl.text.toString()
        prefs.address = address.text.toString()
        prefs.threads = threads.progress + 1
        prefs.chargingOnly = chargingOnly.isChecked
    }

    private fun startMiner() {
        saveSettings()
        if (!prefs.address.startsWith(Coin.ADDRESS_PREFIX) || prefs.address.length != Coin.ADDRESS_LENGTH) {
            address.error = "Paste the address printed by: python wallet.py new"
            return
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
        listOf(nodeUrl, address, threads, chargingOnly).forEach { it.isEnabled = editable }
    }

    private fun testConnection() {
        saveSettings()
        testResult.text = "Connecting…"
        val url = prefs.nodeUrl
        Thread {
            val text = try {
                val info = NodeClient(url).info()
                "Connected to ${info.optString("coin")} node · height ${info.optLong("height")} · " +
                    "${info.optInt("mempool")} pending tx"
            } catch (e: Exception) {
                "Could not reach node: ${e.message ?: e.javaClass.simpleName}"
            }
            runOnUiThread { testResult.text = text }
        }.start()
    }

    private fun render(s: MinerStatus) {
        toggle.text = getString(if (s.running) R.string.stop else R.string.start)
        setEditable(!s.running)
        hashrate.text = formatRate(s.hashrate)
        state.text = when {
            !s.running -> s.message
            s.pausedReason != null -> "Paused: ${s.pausedReason}"
            else -> s.message
        }
        val earned = s.earnedUnits.toDouble() / s.unitsPerCoin
        stats.text = String.format(Locale.US,
            "Height %d · Blocks found %d · Rejected %d\nEarned this session: %.4f %s",
            s.height, s.accepted, s.rejected, earned, Coin.TICKER)
    }
}
