package com.example.stellariteminer

import org.json.JSONObject
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Finds a coin's node on the local network: scans every address on the phone's
 * Wi-Fi subnet (e.g. 192.168.40.1–254) for a node answering /info on the coin's port.
 */
object NodeFinder {

    /** The phone's own IPv4 addresses on local networks, e.g. ["192.168.40.42"]. */
    fun localAddresses(): List<String> = try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }
            .filterIsInstance<Inet4Address>()
            .filter { it.isSiteLocalAddress }
            .map { it.hostAddress ?: "" }
            .filter { it.isNotEmpty() }
    } catch (e: Exception) { emptyList() }

    /**
     * Returns base URLs of nodes for [coinName] (e.g. "Nebulite") listening on [port].
     * [progress] receives the subnet being scanned. Takes a few seconds.
     */
    fun scan(
        coinName: String, port: Int,
        subnets: List<String> = localAddresses().map { it.substringBeforeLast('.') }.distinct(),
        progress: (String) -> Unit,
    ): List<String> {
        if (subnets.isEmpty()) return emptyList()
        val pool = Executors.newFixedThreadPool(48)
        try {
            val found = ArrayList<String>()
            for (net in subnets) {
                progress("$net.0/24")
                val tasks = (1..254).map { host ->
                    Callable {
                        val url = "http://$net.$host:$port"
                        if (isNode(url, coinName)) url else null
                    }
                }
                pool.invokeAll(tasks, 20, TimeUnit.SECONDS).forEach { f ->
                    runCatching { f.get() }.getOrNull()?.let { found += it }
                }
            }
            return found
        } finally {
            pool.shutdownNow()
        }
    }

    private fun isNode(url: String, coinName: String): Boolean = try {
        val c = URL("$url/info").openConnection() as HttpURLConnection
        c.connectTimeout = 600
        c.readTimeout = 1500
        try {
            c.responseCode == 200 &&
                JSONObject(c.inputStream.bufferedReader().use { it.readText() }).optString("coin") == coinName
        } finally { c.disconnect() }
    } catch (e: Exception) { false }

    fun port(url: String, fallback: Int): Int = runCatching { URL(url).port }.getOrNull()?.takeIf { it > 0 } ?: fallback
}

/** Turns network exceptions into something a person can act on. */
fun friendlyError(e: Throwable, url: String = ""): String {
    val where = url.removePrefix("http://").removePrefix("https://").ifEmpty { "the node" }
    return when (e) {
        is SocketTimeoutException, is ConnectException, is NoRouteToHostException ->
            "can't reach $where. Is the node running on that computer, on the same Wi-Fi? Try [FIND NODE]."
        is UnknownHostException -> "unknown address $where. Check NODE_URI."
        is java.net.MalformedURLException -> "NODE_URI isn't a valid address (example: http://192.168.40.10:5001)."
        else -> e.message ?: e.javaClass.simpleName
    }
}
