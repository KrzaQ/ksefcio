import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap

# OID for organizationIdentifier (X.520 attribute, not in cryptography's NameOID).
OID_ORG_IDENTIFIER = x509.ObjectIdentifier("2.5.4.97")


@dataclass
class KeyMaterial:
    cert: x509.Certificate
    cert_der: bytes
    private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey
    identity: str  # 10-digit NIP or 11-digit PESEL
    name: str
    fingerprint: str  # sha256 hex of cert DER
    key_type: str  # "rsa" or "ec"


def load_keypair(cert_path: Path, key_path: Path, passphrase: bytes | None) -> KeyMaterial:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=passphrase)

    if isinstance(private_key, rsa.RSAPrivateKey):
        key_type = "rsa"
    elif isinstance(private_key, ec.EllipticCurvePrivateKey):
        key_type = "ec"
    else:
        raise ValueError(f"unsupported private key type: {type(private_key).__name__}")

    return KeyMaterial(
        cert=cert,
        cert_der=cert_der,
        private_key=private_key,
        identity=_extract_identity(cert),
        name=_extract_name(cert),
        fingerprint=hashlib.sha256(cert_der).hexdigest(),
        key_type=key_type,
    )


def sign_request(km: KeyMaterial, method: str, path: str, ts: int) -> bytes:
    """Sign the canonical message METHOD\\nPATH\\nTIMESTAMP that ksefcio's auth layer expects."""
    message = f"{method}\n{path}\n{ts}".encode()
    priv = km.private_key

    if isinstance(priv, rsa.RSAPrivateKey):
        return priv.sign(message, padding.PKCS1v15(), hashes.SHA256())

    if isinstance(priv, ec.EllipticCurvePrivateKey):
        der_sig = priv.sign(message, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der_sig)
        size = (priv.curve.key_size + 7) // 8
        return r.to_bytes(size, "big") + s.to_bytes(size, "big")

    raise AssertionError("unreachable")  # guarded in load_keypair


def unwrap_aes_key(km: KeyMaterial, wrapped: bytes) -> bytes:
    priv = km.private_key

    if isinstance(priv, rsa.RSAPrivateKey):
        return priv.decrypt(
            wrapped,
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )

    if isinstance(priv, ec.EllipticCurvePrivateKey):
        pub = km.cert.public_key()
        if not isinstance(pub, ec.EllipticCurvePublicKey):
            raise ValueError("EC private key paired with non-EC certificate")
        # Static-static ECDH with self — matches frontend's wrap-with-own-pubkey flow.
        # Web Crypto's deriveKey(ECDH, length=256) yields the raw shared X-coordinate
        # truncated/padded to 256 bits; for P-256 that's all 32 bytes.
        shared = priv.exchange(ec.ECDH(), pub)
        wrapping_key = shared[:32]
        return aes_key_unwrap(wrapping_key, wrapped)

    raise AssertionError("unreachable")


def decrypt_blob(aes_key: bytes, blob: bytes) -> bytes:
    if len(blob) < 12 + 16:
        raise ValueError("blob too short for AES-GCM (need 12B IV + 16B tag)")
    iv, ciphertext = blob[:12], blob[12:]
    return AESGCM(aes_key).decrypt(iv, ciphertext, associated_data=None)


def _extract_identity(cert: x509.Certificate) -> str:
    # Organization cert: organizationIdentifier = VATPL-XXXXXXXXXX (NIP).
    for attr in cert.subject.get_attributes_for_oid(OID_ORG_IDENTIFIER):
        m = re.match(r"VATPL-(\d{10})", attr.value)
        if m:
            return m.group(1)

    # Natural-person cert: serialNumber = TINPL-XXXXXXXXXX (NIP) or PNOPL-XXXXXXXXXXX (PESEL).
    for attr in cert.subject.get_attributes_for_oid(x509.NameOID.SERIAL_NUMBER):
        m = re.match(r"TINPL-(\d{10})", attr.value)
        if m:
            return m.group(1)
        m = re.match(r"PNOPL-(\d{11})", attr.value)
        if m:
            return m.group(1)

    raise ValueError("could not extract NIP or PESEL from certificate")


def _extract_name(cert: x509.Certificate) -> str:
    for attr in cert.subject.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME):
        return attr.value
    for attr in cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME):
        return attr.value
    return "Unknown"
