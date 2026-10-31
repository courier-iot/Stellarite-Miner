package com.example.stellariteminer

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.Process
import java.util.Locale
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ThreadFactory
import java.util.concurrent.TimeUnit

/** Snapshot of miner state, read by the UI. */
data class MinerStatus(
    val running: Boolean = false,
    val pausedReason: String? = null,
    val hashrate: Double = 0.0,
    val height: Long = 0,
    val accepted: Int = 0,
    val rejected: Int = 0,
    val earnedUnits: Long = 0,
    val unitsPerCoin: Long = 100_000_000,
    val message: String = "Idle",
)

/**
 * Foreground service that owns the mining threads. It is only ever started by the
 * user tapping Start, shows a persistent notification with a Stop action, and
 * pauses itself on low battery, overheating, or (optionally) when unplugged.
 */
class MinerService : Service() {

    companion object {
        const val ACTION_START = "com.example.stellariteminer.START"
        const val ACTION_STOP = "com.example.stellariteminer.STOP"
        private const val CHANNEL_ID = "mining"
        private const val NOTIFICATION_ID = 1
        private const val WORK_REFRESH_MS = 10_000L
        private const val MIN_BATTERY_PERCENT = 20

        @Volatile var status = MinerStatus()
            private set
    }

    private var engine: MiningEngine? = null
    private var controller: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    @Volatile private var running = false
    private val found = LinkedBlockingQueue<Pair<Job, Long>>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { stopMining(); stopSelf() }
            ACTION_START -> startMining()
            else -> stopSelf()  // restarted by the system without an explicit start: stay off
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        stopMining()
        super.onDestroy()
    }

    private fun startMining() {
        if (running) return
        val prefs = Prefs(this)
        createChannel()
        val notification = buildNotification("Starting…")
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "StellariteMiner:mining")
            .apply { acquire(12 * 60 * 60 * 1000L) }

        val lowPriority = ThreadFactory { r ->
            Thread {
                Process.setThreadPriority(Process.THREAD_PRIORITY_BACKGROUND)
                r.run()
            }
        }
        val eng = MiningEngine(prefs.threads, lowPriority) { job, nonce -> found.offer(job to nonce) }
        engine = eng
        running = true
        status = MinerStatus(running = true, message = "Connecting to node…")
        eng.start()
        controller = Thread({ controlLoop(eng, NodeClient(prefs.nodeUrl), prefs) }, "miner-control")
            .apply { start() }
    }

    private fun stopMining() {
        if (!running && engine == null) return
        running = false
        controller?.interrupt()
        engine?.stop()
        engine = null
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        status = status.copy(running = false, hashrate = 0.0, pausedReason = null, message = "Stopped")
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    /** Fetches work, submits solutions, measures hashrate, and enforces safety pauses. */
    private fun controlLoop(eng: MiningEngine, node: NodeClient, prefs: Prefs) {
        var lastFetch = 0L
        var lastHashes = 0L
        var lastTick = System.nanoTime()
        var rate = 0.0
        var lastNotify = 0L

        while (running) {
            val reason = pauseReason(prefs.chargingOnly)
            eng.paused = reason != null

            try {
                val solution = found.poll(1, TimeUnit.SECONDS)
                if (!running) break
                if (solution != null) {
                    val (job, nonce) = solution
                    val result = node.submit(job.id, nonce)
                    status = if (result.accepted) status.copy(
                        accepted = status.accepted + 1,
                        earnedUnits = status.earnedUnits + job.rewardUnits,
                        message = "${result.message} 🎉",
                    ) else status.copy(rejected = status.rejected + 1, message = "Rejected: ${result.message}")
                    lastFetch = 0  // get fresh work right away
                }
                val now = System.currentTimeMillis()
                if (reason == null && (eng.job == null || now - lastFetch > WORK_REFRESH_MS)) {
                    val job = node.getWork(prefs.address)
                    eng.job = job
                    lastFetch = now
                    status = status.copy(height = job.height, unitsPerCoin = job.unitsPerCoin,
                        message = if (solution == null) "Mining block ${job.height}" else status.message)
                }
            } catch (e: InterruptedException) {
                break
            } catch (e: Exception) {
                status = status.copy(message = "Node error: ${e.message ?: e.javaClass.simpleName}")
                eng.job = null
                try { Thread.sleep(5000) } catch (ie: InterruptedException) { break }
            }

            // Hashrate as a smoothed average.
            val t = System.nanoTime()
            val total = eng.hashes.get()
            val seconds = (t - lastTick) / 1e9
            if (seconds > 0) {
                val instant = (total - lastHashes) / seconds
                rate = if (rate == 0.0) instant else rate * 0.7 + instant * 0.3
            }
            lastHashes = total; lastTick = t
            status = status.copy(hashrate = if (reason != null) 0.0 else rate, pausedReason = reason)

            if (System.currentTimeMillis() - lastNotify > 5000) {
                lastNotify = System.currentTimeMillis()
                val text = reason?.let { "Paused: $it" }
                    ?: "${formatRate(rate)} · ${status.accepted} blocks found"
                getSystemService(NotificationManager::class.java)
                    .notify(NOTIFICATION_ID, buildNotification(text))
            }
        }
    }

    private fun pauseReason(chargingOnly: Boolean): String? {
        val battery = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val plugged = (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0
        val percent = if (level >= 0 && scale > 0) level * 100 / scale else 100

        if (Build.VERSION.SDK_INT >= 29) {
            val pm = getSystemService(PowerManager::class.java)
            if (pm.currentThermalStatus >= PowerManager.THERMAL_STATUS_SEVERE) return "phone is too hot"
        }
        if (chargingOnly && !plugged) return "not charging"
        if (!plugged && percent < MIN_BATTERY_PERCENT) return "battery below $MIN_BATTERY_PERCENT%"
        return null
    }

    private fun createChannel() {
        val channel = NotificationChannel(CHANNEL_ID, getString(R.string.channel_name),
            NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1,
            Intent(this, MinerService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_miner)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(
                Icon.createWithResource(this, R.drawable.ic_stat_miner), getString(R.string.stop), stop).build())
            .build()
    }
}

fun formatRate(hashesPerSecond: Double): String = when {
    hashesPerSecond >= 1e6 -> String.format(Locale.US, "%.2f MH/s", hashesPerSecond / 1e6)
    hashesPerSecond >= 1e3 -> String.format(Locale.US, "%.1f kH/s", hashesPerSecond / 1e3)
    else -> String.format(Locale.US, "%.0f H/s", hashesPerSecond)
}
