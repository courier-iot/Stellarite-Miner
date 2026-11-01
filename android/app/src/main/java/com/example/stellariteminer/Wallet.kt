package com.example.stellariteminer

import java.math.BigInteger
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * Minimal secp256k1 public-key math (Android's built-in crypto doesn't offer this curve).
 * Only what a wallet needs to derive its address: private key -> compressed public key.
 */
object Secp256k1 {
    private val P = BigInteger("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F", 16)
    val N = BigInteger("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFBAAEDCE6AF48A03BBFD25E8CD0364141", 16)
    private val GX = BigInteger("79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798", 16)
    private val GY = BigInteger("483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8", 16)
    private val TWO = BigInteger.valueOf(2)
    private val THREE = BigInteger.valueOf(3)

    private class Pt(val x: BigInteger, val y: BigInteger)

    private fun add(a: Pt?, b: Pt?): Pt? {
        if (a == null) return b
        if (b == null) return a
        if (a.x == b.x) {
            if ((a.y + b.y).mod(P) == BigInteger.ZERO) return null
            val l = THREE * a.x * a.x * (TWO * a.y).modInverse(P) % P
            val x = (l * l - TWO * a.x).mod(P)
            return Pt(x, (l * (a.x - x) - a.y).mod(P))
        }
        val l = (b.y - a.y) * (b.x - a.x).modInverse(P) % P
        val x = (l * l - a.x - b.x).mod(P)
        return Pt(x, (l * (a.x - x) - a.y).mod(P))
    }

    /** 33-byte compressed public key for a private key in [1, N-1]. */
    fun publicKey(priv: BigInteger): ByteArray {
        require(priv.signum() > 0 && priv < N) { "private key out of range" }
        var result: Pt? = null
        var addend: Pt? = Pt(GX, GY)
        for (i in 0 until priv.bitLength()) {
            if (priv.testBit(i)) result = add(result, addend)
            addend = add(addend, addend)
        }
        val r = result!!
        val x = r.x.toByteArray().let { b -> ByteArray(32).also { o ->
            val src = if (b.size > 32) b.copyOfRange(b.size - 32, b.size) else b
            System.arraycopy(src, 0, o, 32 - src.size, src.size) } }
        return byteArrayOf(if (r.y.testBit(0)) 3 else 2) + x
    }
}

/**
 * The app's own wallet: one private key, stored on the phone, giving a
 * Pulsarite address (plsr…) and a Nebulite address (nblt…).
 * Same key and address format as wallet.py, so keys move between phone and computer.
 */
class Wallet(private val prefs: android.content.SharedPreferences) {

    val privateKeyHex: String? get() = prefs.getString(KEY, null)

    fun hasKey() = privateKeyHex != null

    /** Creates a new random key (replacing any existing one: back it up first!). */
    fun create(): String {
        val rnd = SecureRandom()
        var k: BigInteger
        do { k = BigInteger(256, rnd) } while (k.signum() == 0 || k >= Secp256k1.N)
        val hex = k.toString(16).padStart(64, '0')
        prefs.edit().putString(KEY, hex).apply()
        return hex
    }

    /** Imports a key from wallet.json's "private_key" (64 hex characters). Returns false if invalid. */
    fun import(hex: String): Boolean {
        val clean = hex.trim().lowercase().removePrefix("0x")
        if (clean.length != 64 || clean.any { it !in "0123456789abcdef" }) return false
        val k = BigInteger(clean, 16)
        if (k.signum() == 0 || k >= Secp256k1.N) return false
        prefs.edit().putString(KEY, clean).apply()
        return true
    }

    fun address(prefix: String): String? = privateKeyHex?.let { addressFor(it, prefix) }

    companion object {
        private const val KEY = "wallet_private_key"

        private fun sha256(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b)

        /** Same as crypto_utils.address_from_pubkey: prefix + hex(sha256(pub)[:20] + sha256d(that)[:4]). */
        fun addressFor(privateKeyHex: String, prefix: String): String {
            val pub = Secp256k1.publicKey(BigInteger(privateKeyHex, 16))
            val digest = sha256(pub).copyOfRange(0, 20)
            val check = sha256(sha256(digest)).copyOfRange(0, 4)
            return prefix + (digest + check).joinToString("") { "%02x".format(it.toInt() and 0xff) }
        }

        /** The wallet.json contents for this key, so it can be used with wallet.py too. */
        fun walletJson(privateKeyHex: String) = "{\"private_key\": \"$privateKeyHex\"}"
    }
}
