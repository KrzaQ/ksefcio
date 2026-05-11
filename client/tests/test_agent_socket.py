"""End-to-end test: real asyncio Unix socket server, real client, real NDJSON.

Verifies the full agent.serve() loop without spawning a subprocess.
"""
import asyncio
import base64
import datetime as dt
import json
import os
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import aes_key_wrap
from cryptography.x509.oid import NameOID

from ksefcio_client import agent, crypto, protocol


def _make_ec_pair(tmp_path: Path) -> tuple[Path, Path, ec.EllipticCurvePrivateKey]:
    priv = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, "PNOPL-88092104372"),
            x509.NameAttribute(NameOID.COMMON_NAME, "TEST PERSON"),
        ]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TEST")]))
        .public_key(priv.public_key())
        .serial_number(1)
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .sign(priv, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return cert_path, key_path, priv


async def _start_server(state: agent.AgentState, sock_path: Path) -> asyncio.Server:
    prev = os.umask(0o077)
    try:
        server = await asyncio.start_unix_server(agent.make_handler(state), path=str(sock_path))
    finally:
        os.umask(prev)
    os.chmod(sock_path, 0o600)
    return server


async def _rpc(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, req: dict) -> dict:
    writer.write((json.dumps(req) + "\n").encode())
    await writer.drain()
    line = await reader.readuntil(b"\n")
    return json.loads(line)


@pytest.mark.asyncio
async def test_full_flow_over_socket(tmp_path):
    cert_path, key_path, priv = _make_ec_pair(tmp_path)
    km = crypto.load_keypair(cert_path, key_path, passphrase=None)
    state = agent.AgentState(km)

    sock_path = tmp_path / "agent.sock"
    server = await _start_server(state, sock_path)
    try:
        # Socket permissions enforced.
        assert (sock_path.stat().st_mode & 0o777) == 0o600

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        try:
            # identity — pre-unwrap state visible
            resp = await _rpc(reader, writer, {"id": "1", "op": "identity"})
            assert resp["ok"] is True
            assert resp["result"]["identity"] == "88092104372"
            assert resp["result"]["key_type"] == "ec"
            assert resp["result"]["aes_unwrapped"] is False

            # decrypt before unwrap → not_ready
            resp = await _rpc(reader, writer, {"id": "2", "op": "decrypt", "blob_b64": "AAAA"})
            assert resp["ok"] is False
            assert resp["error"]["code"] == protocol.ERR_NOT_READY

            # unwrap an AES key wrapped with self-ECDH (same as frontend)
            aes_key = AESGCM.generate_key(bit_length=256)
            shared = priv.exchange(ec.ECDH(), priv.public_key())
            wrapped = aes_key_wrap(shared[:32], aes_key)
            resp = await _rpc(reader, writer, {
                "id": "3", "op": "unwrap_aes",
                "wrapped_b64": base64.b64encode(wrapped).decode(),
            })
            assert resp["ok"] is True
            assert resp["result"]["already_set"] is False

            # second unwrap with same blob → idempotent
            resp = await _rpc(reader, writer, {
                "id": "4", "op": "unwrap_aes",
                "wrapped_b64": base64.b64encode(wrapped).decode(),
            })
            assert resp["ok"] is True
            assert resp["result"]["already_set"] is True

            # unwrap with different blob → mismatch error
            other = AESGCM.generate_key(bit_length=256)
            other_wrapped = aes_key_wrap(shared[:32], other)
            resp = await _rpc(reader, writer, {
                "id": "5", "op": "unwrap_aes",
                "wrapped_b64": base64.b64encode(other_wrapped).decode(),
            })
            assert resp["ok"] is False
            assert resp["error"]["code"] == protocol.ERR_AES_MISMATCH

            # decrypt now works
            plaintext = b"<Faktura>hello</Faktura>"
            iv = os.urandom(12)
            blob = iv + AESGCM(aes_key).encrypt(iv, plaintext, None)
            resp = await _rpc(reader, writer, {
                "id": "6", "op": "decrypt",
                "blob_b64": base64.b64encode(blob).decode(),
            })
            assert resp["ok"] is True
            assert base64.b64decode(resp["result"]["plaintext_b64"]) == plaintext

            # sign_request returns valid P1363 signature
            resp = await _rpc(reader, writer, {
                "id": "7", "op": "sign_request",
                "method": "GET", "path": "/api/users/me", "ts": 1700000000,
            })
            assert resp["ok"] is True
            sig = base64.b64decode(resp["result"]["signature_b64"])
            assert len(sig) == 64

            # unknown op
            resp = await _rpc(reader, writer, {"id": "8", "op": "nope"})
            assert resp["ok"] is False
            assert resp["error"]["code"] == protocol.ERR_UNKNOWN_OP

            # malformed (missing fields)
            resp = await _rpc(reader, writer, {"id": "9", "op": "sign_request"})
            assert resp["ok"] is False
            assert resp["error"]["code"] == protocol.ERR_BAD_REQUEST

            # identity now reflects unwrapped state
            resp = await _rpc(reader, writer, {"id": "10", "op": "identity"})
            assert resp["result"]["aes_unwrapped"] is True
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()
        sock_path.unlink(missing_ok=True)
