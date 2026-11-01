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
    val N = BigInteger("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16)
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

    private fun multiply(k: BigInteger): Pt {
        var result: Pt? = null
        var addend: Pt? = Pt(GX, GY)
        for (i in 0 until k.bitLength()) {
            if (k.testBit(i)) result = add(result, addend)
            addend = add(addend, addend)
        }
        return result!!
    }

    /**
     * ECDSA signature (DER-encoded) over SHA-256(message), with the nonce chosen
     * deterministically per RFC 6979 so a weak random generator can't leak the key.
     * Verifies with the nodes' check (cryptography's ECDSA(SHA256)).
     */
    fun sign(priv: BigInteger, message: ByteArray): ByteArray {
        val h = MessageDigest.getInstance("SHA-256").digest(message)
        val z = BigInteger(1, h)
        val x = toBytes32(priv)
        val h1 = toBytes32(z.mod(N))
        fun hmac(key: ByteArray, vararg parts: ByteArray): ByteArray {
            val mac = javax.crypto.Mac.getInstance("HmacSHA256")
            mac.init(javax.crypto.spec.SecretKeySpec(key, "HmacSHA256"))
            parts.forEach { mac.update(it) }
            return mac.doFinal()
        }
        var v = ByteArray(32) { 1 }
        var kk = ByteArray(32)
        kk = hmac(kk, v, byteArrayOf(0), x, h1); v = hmac(kk, v)
        kk = hmac(kk, v, byteArrayOf(1), x, h1); v = hmac(kk, v)
        while (true) {
            v = hmac(kk, v)
            val k = BigInteger(1, v)
            if (k.signum() > 0 && k < N) {
                val r = multiply(k).x.mod(N)
                var s = k.modInverse(N).multiply(z.add(r.multiply(priv))).mod(N)
                if (r.signum() != 0 && s.signum() != 0) {
                    if (s > N.shiftRight(1)) s = N.subtract(s)     // low-S form
                    return der(r, s)
                }
            }
            kk = hmac(kk, v, byteArrayOf(0)); v = hmac(kk, v)
        }
    }

    private fun der(r: BigInteger, s: BigInteger): ByteArray {
        fun int(i: BigInteger): ByteArray { val b = i.toByteArray(); return byteArrayOf(0x02, b.size.toByte()) + b }
        val body = int(r) + int(s)
        return byteArrayOf(0x30, body.size.toByte()) + body
    }

    private fun toBytes32(i: BigInteger): ByteArray {
        val b = i.toByteArray()
        val src = if (b.size > 32) b.copyOfRange(b.size - 32, b.size) else b
        return ByteArray(32).also { System.arraycopy(src, 0, it, 32 - src.size, src.size) }
    }

    /** 33-byte compressed public key for a private key in [1, N-1]. */
    fun publicKey(priv: BigInteger): ByteArray {
        require(priv.signum() > 0 && priv < N) { "private key out of range" }
        val r = multiply(priv)
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

    /**
     * A signed transaction, exactly as the node expects it:
     * {"from": public key hex, "to", "amount", "fee", "nonce", "sig"}, where sig signs
     * the canonical JSON of the other fields (sorted keys, no spaces), as wallet.py does.
     */
    fun signTransaction(to: String, amount: Long, fee: Long, nonce: Long): org.json.JSONObject {
        val key = privateKeyHex ?: throw IllegalStateException("no wallet on this phone")
        val pub = hex(Secp256k1.publicKey(BigInteger(key, 16)))
        val signing = "{\"amount\":$amount,\"fee\":$fee,\"from\":\"$pub\",\"nonce\":$nonce,\"to\":\"$to\"}"
        val sig = hex(Secp256k1.sign(BigInteger(key, 16), signing.toByteArray()))
        return org.json.JSONObject().put("from", pub).put("to", to).put("amount", amount)
            .put("fee", fee).put("nonce", nonce).put("sig", sig)
    }

    /**
     * A fee-free username claim: {"type":"name","from","name","nonce","work","sig"}.
     * Searches for `work` so sha256d(canonical claim) has [bits] leading zero bits
     * (the node's anti-spam rule), then signs. Takes a few seconds; call off the
     * main thread. [progress] gets the number of tries so far; [cancelled] can stop it.
     */
    fun signNameClaim(name: String, nonce: Long, bits: Int,
                      progress: (Long) -> Unit = {}, cancelled: () -> Boolean = { false }): org.json.JSONObject? {
        val key = privateKeyHex ?: throw IllegalStateException("no wallet on this phone")
        val pub = hex(Secp256k1.publicKey(BigInteger(key, 16)))
        val head = "{\"from\":\"$pub\",\"name\":\"$name\",\"nonce\":$nonce,\"type\":\"name\",\"work\":".toByteArray()
        val tail = "}".toByteArray()
        val limit = BigInteger.ONE.shiftLeft(256 - bits)
        val mid = MessageDigest.getInstance("SHA-256").apply { update(head) }     // hash the fixed part once
        val outer = MessageDigest.getInstance("SHA-256")
        var work = 0L
        while (true) {
            val md = mid.clone() as MessageDigest
            md.update(work.toString().toByteArray()); md.update(tail)
            val h = outer.digest(md.digest())
            if (BigInteger(1, h) < limit) break
            work++
            if (work and 0xFFFF == 0L) { progress(work); if (cancelled()) return null }
        }
        val signing = String(head) + work + "}"
        val sig = hex(Secp256k1.sign(BigInteger(key, 16), signing.toByteArray()))
        return org.json.JSONObject().put("type", "name").put("from", pub).put("name", name)
            .put("nonce", nonce).put("work", work).put("sig", sig)
    }

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

        private fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it.toInt() and 0xff) }

        /** Same check as crypto_utils.is_valid_address. */
        fun isValidAddress(addr: String, prefix: String): Boolean {
            if (!addr.startsWith(prefix)) return false
            val body = addr.substring(prefix.length)
            if (body.length != 48 || body.any { it !in "0123456789abcdef" }) return false
            val raw = ByteArray(24) { body.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
            return sha256(sha256(raw.copyOfRange(0, 20))).copyOfRange(0, 4).contentEquals(raw.copyOfRange(20, 24))
        }

        /** The wallet.json contents for this key, so it can be used with wallet.py too. */
        fun walletJson(privateKeyHex: String) = "{\"private_key\": \"$privateKeyHex\"}"
    }
}
