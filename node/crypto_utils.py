"""Hashing, keys, signatures and addresses."""
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from config import ADDRESS_PREFIX


def sha256d(data: bytes) -> bytes:
    """Double SHA-256, the proof-of-work hash (same idea as Bitcoin)."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def canonical(obj) -> bytes:
    """Deterministic JSON so every node hashes and signs identical bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


# ---- keys ---------------------------------------------------------------

def new_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256K1())


def private_key_to_hex(key) -> str:
    return format(key.private_numbers().private_value, "064x")


def private_key_from_hex(hex_str: str):
    return ec.derive_private_key(int(hex_str, 16), ec.SECP256K1())


def public_key_hex(key) -> str:
    """Compressed SEC1 public key (33 bytes) as hex."""
    pub = key.public_key() if hasattr(key, "public_key") else key
    return pub.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
    ).hex()


def address_from_pubkey(pub_hex: str) -> str:
    digest = hashlib.sha256(bytes.fromhex(pub_hex)).digest()[:20]
    checksum = sha256d(digest)[:4]
    return ADDRESS_PREFIX + (digest + checksum).hex()


def is_valid_address(addr) -> bool:
    if not isinstance(addr, str) or not addr.startswith(ADDRESS_PREFIX):
        return False
    body = addr[len(ADDRESS_PREFIX):]
    if len(body) != 48:
        return False
    try:
        raw = bytes.fromhex(body)
    except ValueError:
        return False
    return sha256d(raw[:20])[:4] == raw[20:]


# ---- signatures ---------------------------------------------------------

def sign(private_key, message: bytes) -> str:
    return private_key.sign(message, ec.ECDSA(hashes.SHA256())).hex()


def verify(pub_hex: str, message: bytes, sig_hex: str) -> bool:
    try:
        pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256K1(), bytes.fromhex(pub_hex)
        )
        pub.verify(bytes.fromhex(sig_hex), message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
