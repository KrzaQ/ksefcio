import base64
import hashlib
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ksefcio.db import get_db, get_user, upsert_user

router = APIRouter(prefix="/api/auth")

JWT_SECRET = os.environ.get("KSEFCIO_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 24 * 60 * 60  # 24 hours

CERTS_DIR = Path(__file__).parent.parent.parent / "certs"

# OID for organizationIdentifier (not in cryptography's NameOID)
OID_ORG_IDENTIFIER = x509.ObjectIdentifier("2.5.4.97")

# --- CA certs loaded at import time ---

_root_cert: x509.Certificate | None = None
_intermediate_cert: x509.Certificate | None = None


def _load_cert_file(path: Path) -> x509.Certificate:
    data = path.read_bytes()
    if data.startswith(b"-----"):
        return x509.load_pem_x509_certificate(data)
    return x509.load_der_x509_certificate(data)


def _load_ca_certs():
    global _root_cert, _intermediate_cert
    root_path = CERTS_DIR / "cck-mf-root.crt"
    intermediate_path = CERTS_DIR / "cck-ksef.crt"
    if root_path.exists():
        _root_cert = _load_cert_file(root_path)
    if intermediate_path.exists():
        _intermediate_cert = _load_cert_file(intermediate_path)


_load_ca_certs()


# --- Pending challenges ---


@dataclass
class ChallengeData:
    nonce: bytes
    cert_fingerprint: str
    nip: str
    name: str
    expires_at: float


_pending_challenges: dict[str, ChallengeData] = {}


def _cleanup_expired():
    now = time.monotonic()
    expired = [k for k, v in _pending_challenges.items() if v.expires_at < now]
    for k in expired:
        del _pending_challenges[k]


# --- Cert helpers ---


def verify_cert_chain(user_cert: x509.Certificate):
    if _root_cert is None or _intermediate_cert is None:
        raise HTTPException(500, "CA certificates not loaded")

    try:
        _root_cert.verify_directly_issued_by(_root_cert)
        _intermediate_cert.verify_directly_issued_by(_root_cert)
        user_cert.verify_directly_issued_by(_intermediate_cert)
    except Exception as e:
        raise HTTPException(400, f"Certificate chain verification failed: {e}")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    for cert, label in [
        (user_cert, "user"),
        (_intermediate_cert, "intermediate"),
        (_root_cert, "root"),
    ]:
        if now < cert.not_valid_before_utc or now > cert.not_valid_after_utc:
            raise HTTPException(400, f"Certificate expired or not yet valid: {label}")


def extract_nip(cert: x509.Certificate) -> str:
    # Try organizationIdentifier (VATPL-XXXXXXXXXX) for organizations
    try:
        org_id = cert.subject.get_attributes_for_oid(OID_ORG_IDENTIFIER)
        if org_id:
            match = re.match(r"VATPL-(\d{10})", org_id[0].value)
            if match:
                return match.group(1)
    except Exception:
        pass

    # Try serialNumber (TINPL-XXXXXXXXXX) for natural persons
    try:
        serial = cert.subject.get_attributes_for_oid(x509.oid.NameOID.SERIAL_NUMBER)
        if serial:
            match = re.match(r"TINPL-(\d{10})", serial[0].value)
            if match:
                return match.group(1)
    except Exception:
        pass

    raise HTTPException(400, "Could not extract NIP from certificate")


def extract_name(cert: x509.Certificate) -> str:
    # Try organizationName first (for companies)
    try:
        org = cert.subject.get_attributes_for_oid(x509.oid.NameOID.ORGANIZATION_NAME)
        if org:
            return org[0].value
    except Exception:
        pass

    # Fall back to commonName
    try:
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        if cn:
            return cn[0].value
    except Exception:
        pass

    return "Unknown"


def cert_fingerprint(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def parse_cert(cert_pem: str) -> x509.Certificate:
    try:
        cert_bytes = cert_pem.encode() if isinstance(cert_pem, str) else cert_pem
        return x509.load_pem_x509_certificate(cert_bytes)
    except Exception:
        try:
            return x509.load_der_x509_certificate(base64.b64decode(cert_pem))
        except Exception:
            raise HTTPException(400, "Invalid certificate format")


# --- Endpoints ---


class ChallengeRequest(BaseModel):
    certificate: str  # PEM or base64-DER


class ChallengeResponse(BaseModel):
    challenge_id: str
    nonce: str  # base64
    nip: str
    name: str


@router.post("/challenge", response_model=ChallengeResponse)
async def create_challenge(req: ChallengeRequest):
    cert = parse_cert(req.certificate)
    verify_cert_chain(cert)
    nip = extract_nip(cert)
    name = extract_name(cert)

    _cleanup_expired()

    nonce = secrets.token_bytes(32)
    challenge_id = str(uuid.uuid4())
    _pending_challenges[challenge_id] = ChallengeData(
        nonce=nonce,
        cert_fingerprint=cert_fingerprint(cert),
        nip=nip,
        name=name,
        expires_at=time.monotonic() + 300,
    )

    return ChallengeResponse(
        challenge_id=challenge_id,
        nonce=base64.b64encode(nonce).decode(),
        nip=nip,
        name=name,
    )


class VerifyRequest(BaseModel):
    challenge_id: str
    signature: str  # base64
    certificate: str  # same cert as challenge


class VerifyResponse(BaseModel):
    token: str
    user: dict


@router.post("/verify", response_model=VerifyResponse)
async def verify_challenge(req: VerifyRequest, db=Depends(get_db)):
    challenge = _pending_challenges.get(req.challenge_id)
    if not challenge or challenge.expires_at < time.monotonic():
        _pending_challenges.pop(req.challenge_id, None)
        raise HTTPException(401, "Challenge expired or not found")

    cert = parse_cert(req.certificate)
    if cert_fingerprint(cert) != challenge.cert_fingerprint:
        raise HTTPException(400, "Certificate does not match challenge")

    # Verify signature over the nonce
    signature = base64.b64decode(req.signature)
    public_key = cert.public_key()

    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, challenge.nonce, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, challenge.nonce, ec.ECDSA(hashes.SHA256()))
        else:
            raise HTTPException(400, "Unsupported key type")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(401, f"Signature verification failed: {e}")

    del _pending_challenges[req.challenge_id]

    # Upsert user
    fp = cert_fingerprint(cert)
    user = await upsert_user(db, challenge.nip, challenge.name, fp)

    # Issue JWT
    if not JWT_SECRET:
        raise HTTPException(500, "JWT secret not configured")

    token = jwt.encode(
        {
            "nip": challenge.nip,
            "name": challenge.name,
            "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
            "iat": int(time.time()),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    return VerifyResponse(
        token=token,
        user={
            "nip": user["nip"],
            "name": user["name"],
            "has_wrapped_key": user["wrapped_aes_key"] is not None,
        },
    )


# --- Auth dependency ---


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing authorization header")

    token = auth[7:]
    if not JWT_SECRET:
        raise HTTPException(500, "JWT secret not configured")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

    return {"nip": payload["nip"], "name": payload["name"]}
