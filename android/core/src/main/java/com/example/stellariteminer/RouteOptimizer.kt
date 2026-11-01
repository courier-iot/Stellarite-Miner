package com.example.stellariteminer

import kotlin.math.sqrt
import kotlin.random.Random

/**
 * Finds a short open path from the Sun through a block's stars: the "useful work"
 * half of Pulsarite mining. Pure JVM, no Android APIs.
 *
 * Greedy nearest-neighbour start, then 2-opt (reverse a stretch) and Or-opt
 * (move a stretch of 1–3 stars), with random "double-bridge" kicks to escape
 * local optima. Calling [improve] again continues from the best route so far,
 * so a block's route keeps getting shorter while the rig hashes.
 *
 * Same method as node/route_opt.py; the node does the official scoring.
 */
class RouteOptimizer(private val xs: DoubleArray, private val ys: DoubleArray, private val zs: DoubleArray) {
    private val n = xs.size
    private val rnd = Random(System.nanoTime())

    /** Best order found so far (indices into the star list). */
    var best: IntArray = nearestNeighbour()
        private set
    var bestLength: Double = length(best)
        private set
    private var polished = false

    private fun d(a: Int, b: Int): Double {
        val dx = xs[a] - xs[b]; val dy = ys[a] - ys[b]; val dz = zs[a] - zs[b]
        return sqrt(dx * dx + dy * dy + dz * dz)
    }

    private fun dSol(a: Int): Double = sqrt(xs[a] * xs[a] + ys[a] * ys[a] + zs[a] * zs[a])

    fun length(order: IntArray): Double {
        if (order.isEmpty()) return 0.0
        var total = dSol(order[0])
        for (i in 1 until order.size) total += d(order[i - 1], order[i])
        return total
    }

    private fun nearestNeighbour(): IntArray {
        val used = BooleanArray(n)
        val out = IntArray(n)
        var here = -1
        for (k in 0 until n) {
            var bestJ = -1
            var bestD = Double.MAX_VALUE
            for (j in 0 until n) if (!used[j]) {
                val dj = if (here < 0) dSol(j) else d(here, j)
                if (dj < bestD) { bestD = dj; bestJ = j }
            }
            used[bestJ] = true; out[k] = bestJ; here = bestJ
        }
        return out
    }

    private fun twoOpt(order: IntArray) {
        var improved = true
        while (improved) {
            improved = false
            for (i in 0 until n - 1) {
                for (j in i + 1 until n) {
                    val before = if (i == 0) dSol(order[j]) - dSol(order[i])
                        else d(order[i - 1], order[j]) - d(order[i - 1], order[i])
                    val after = if (j + 1 < n) d(order[i], order[j + 1]) - d(order[j], order[j + 1]) else 0.0
                    if (before + after < -1e-9) {
                        var a = i; var b = j
                        while (a < b) { val t = order[a]; order[a] = order[b]; order[b] = t; a++; b-- }
                        improved = true
                    }
                }
            }
        }
    }

    private fun orOpt(start: IntArray): IntArray {
        var order = start
        var cur = length(order)
        var improved = true
        while (improved) {
            improved = false
            search@ for (seg in 1..3) {
                for (i in 0..n - seg) {
                    val chunk = order.copyOfRange(i, i + seg)
                    val rest = order.copyOfRange(0, i) + order.copyOfRange(i + seg, n)
                    for (j in 0..rest.size) {
                        for (rev in booleanArrayOf(false, true)) {
                            val c = if (rev) chunk.reversedArray() else chunk
                            val cand = rest.copyOfRange(0, j) + c + rest.copyOfRange(j, rest.size)
                            val l = length(cand)
                            if (l < cur - 1e-9) {
                                order = cand; cur = l; improved = true
                                break@search
                            }
                        }
                    }
                }
            }
        }
        return order
    }

    private fun localSearch(order: IntArray): IntArray {
        twoOpt(order)
        return orOpt(order)
    }

    /** Keep improving the route for up to [millis] ms. Returns true if it got shorter. */
    fun improve(millis: Long): Boolean {
        val startLen = bestLength
        val deadline = System.currentTimeMillis() + millis
        if (!polished) {
            best = localSearch(best.copyOf())
            bestLength = length(best)
            polished = true
        }
        while (n >= 8 && System.currentTimeMillis() < deadline && !Thread.currentThread().isInterrupted) {
            // double-bridge kick: split into 4 parts A B C D, rejoin as A D C B
            val cuts = (1 until n).shuffled(rnd).take(3).sorted()
            val (a, b, c) = cuts
            val cand = best.copyOfRange(0, a) + best.copyOfRange(c, n) +
                best.copyOfRange(b, c) + best.copyOfRange(a, b)
            val opt = localSearch(cand)
            val l = length(opt)
            if (l < bestLength - 1e-9) { best = opt; bestLength = l }
        }
        return bestLength < startLen - 1e-9
    }
}
