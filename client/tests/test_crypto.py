"""Round-trip self-tests. No real KSeF cert needed.

These exercise the same primitives the frontend uses (static-static ECDH + AES-KW,
RSA-OAEP, AES-GCM, ECDSA P1363) so a regression there should fail here too.
"""
import datetime as dt
import os
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import aes_key_wrap
from cryptography.x509.oid import NameOID

from ksefcio_client import crypto

OID_ORG_IDENTIFIER = x509.ObjectIdentifier("2.5.4.97")


def _make_cert(private_key, subject: x509.Name) -> x509.Certificate:
    now = dt.datetime.now(dt.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )


def _write_pair(tmp_path: Path, private_key, cert: x509.Certificate, passphrase: bytes | None) -> tuple[Path, Path]:
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    enc: serialization.KeySerializationEncryption
    enc = serialization.BestAvailableEncryption(passphrase) if passphrase else serialization.NoEncryption()
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            enc,
        )
    )
    return cert_path, key_path


def _ec_pesel_cert(priv: ec.EllipticCurvePrivateKey) -> x509.Certificate:
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, "PNOPL-88092104372"),
        x509.NameAttribute(NameOID.COMMON_NAME, "TEST PERSON (uwierzytelnienie)"),
    ])
    return _make_cert(priv, subject)


def _rsa_org_cert(priv: rsa.RSAPrivateKey) -> x509.Certificate:
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        x509.NameAttribute(OID_ORG_IDENTIFIER, "VATPL-1234567890"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Spółka sp. z o.o."),
    ])
    return _make_cert(priv, subject)


def test_ec_load_and_identity(tmp_path):
    priv = ec.generate_private_key(ec.SECP256R1())
    cert = _ec_pesel_cert(priv)
    cert_path, key_path = _write_pair(tmp_path, priv, cert, passphrase=b"hunter2")

    km = crypto.load_keypair(cert_path, key_path, passphrase=b"hunter2")
    assert km.identity == "88092104372"
    assert km.name == "TEST PERSON (uwierzytelnienie)"
    assert km.key_type == "ec"
    assert len(km.fingerprint) == 64


def test_rsa_load_and_identity(tmp_path):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _rsa_org_cert(priv)
    cert_path, key_path = _write_pair(tmp_path, priv, cert, passphrase=None)

    km = crypto.load_keypair(cert_path, key_path, passphrase=None)
    assert km.identity == "1234567890"
    assert km.name == "Test Spółka sp. z o.o."
    assert km.key_type == "rsa"


def test_ec_unwrap_round_trip(tmp_path):
    priv = ec.generate_private_key(ec.SECP256R1())
    cert = _ec_pesel_cert(priv)
    cert_path, key_path = _write_pair(tmp_path, priv, cert, passphrase=None)
    km = crypto.load_keypair(cert_path, key_path, passphrase=None)

    # Frontend-equivalent wrap: static-static ECDH (self×self), use raw X-coord as AES-KW key.
    aes_key = AESGCM.generate_key(bit_length=256)
    shared = priv.exchange(ec.ECDH(), priv.public_key())
    wrapping_key = shared[:32]
    wrapped = aes_key_wrap(wrapping_key, aes_key)

    unwrapped = crypto.unwrap_aes_key(km, wrapped)
    assert unwrapped == aes_key


def test_rsa_unwrap_round_trip(tmp_path):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _rsa_org_cert(priv)
    cert_path, key_path = _write_pair(tmp_path, priv, cert, passphrase=None)
    km = crypto.load_keypair(cert_path, key_path, passphrase=None)

    aes_key = AESGCM.generate_key(bit_length=256)
    wrapped = priv.public_key().encrypt(
        aes_key,
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )

    unwrapped = crypto.unwrap_aes_key(km, wrapped)
    assert unwrapped == aes_key


def test_ec_sign_request_is_p1363_and_verifies(tmp_path):
    priv = ec.generate_private_key(ec.SECP256R1())
    cert = _ec_pesel_cert(priv)
    cert_path, key_path = _write_pair(tmp_path, priv, cert, passphrase=None)
    km = crypto.load_keypair(cert_path, key_path, passphrase=None)

    sig = crypto.sign_request(km, "GET", "/api/users/me", 1700000000)
    # P-256 P1363 = 32-byte r || 32-byte s.
    assert len(sig) == 64

    # Convert back to DER for verification.
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    priv.public_key().verify(
        encode_dss_signature(r, s),
        b"GET\n/api/users/me\n1700000000",
        ec.ECDSA(hashes.SHA256()),
    )


def test_rsa_sign_request_verifies(tmp_path):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _rsa_org_cert(priv)
    cert_path, key_path = _write_pair(tmp_path, priv, cert, passphrase=None)
    km = crypto.load_keypair(cert_path, key_path, passphrase=None)

    sig = crypto.sign_request(km, "POST", "/api/users/me/wrapped-key", 1700000000)
    priv.public_key().verify(
        sig,
        b"POST\n/api/users/me/wrapped-key\n1700000000",
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_decrypt_blob_round_trip():
    aes_key = AESGCM.generate_key(bit_length=256)
    plaintext = b"<Faktura>example</Faktura>"
    iv = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(iv, plaintext, associated_data=None)
    blob = iv + ciphertext
    assert crypto.decrypt_blob(aes_key, blob) == plaintext


def test_decrypt_blob_rejects_short_input():
    with pytest.raises(ValueError):
        crypto.decrypt_blob(b"\x00" * 32, b"too-short")


def test_load_keypair_wrong_passphrase(tmp_path):
    priv = ec.generate_private_key(ec.SECP256R1())
    cert = _ec_pesel_cert(priv)
    cert_path, key_path = _write_pair(tmp_path, priv, cert, passphrase=b"correct")
    with pytest.raises(Exception):
        crypto.load_keypair(cert_path, key_path, passphrase=b"wrong")
