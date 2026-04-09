import base64
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils as asym_utils
from fastapi import Depends, HTTPException, Request

from ksefcio.db import get_db, upsert_user

TIMESTAMP_TOLERANCE = 300  # 5 minutes

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


def extract_user_id(cert: x509.Certificate) -> str:
    """Extract user identifier from certificate: NIP (10 digits) or PESEL (11 digits)."""
    # Try organizationIdentifier (VATPL-XXXXXXXXXX) for organizations → NIP
    try:
        org_id = cert.subject.get_attributes_for_oid(OID_ORG_IDENTIFIER)
        if org_id:
            match = re.match(r"VATPL-(\d{10})", org_id[0].value)
            if match:
                return match.group(1)
    except Exception:
        pass

    # Try serialNumber for natural persons
    try:
        serial = cert.subject.get_attributes_for_oid(x509.oid.NameOID.SERIAL_NUMBER)
        if serial:
            # TINPL = NIP (10 digits)
            match = re.match(r"TINPL-(\d{10})", serial[0].value)
            if match:
                return match.group(1)
            # PNOPL = PESEL (11 digits, JDG natural person certs)
            match = re.match(r"PNOPL-(\d{11})", serial[0].value)
            if match:
                return match.group(1)
    except Exception:
        pass

    raise HTTPException(400, "Could not extract NIP or PESEL from certificate")


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


def parse_cert_der(cert_b64: str) -> x509.Certificate:
    """Parse a base64-encoded DER certificate from the X-Cert header."""
    try:
        return x509.load_der_x509_certificate(base64.b64decode(cert_b64))
    except Exception:
        raise HTTPException(400, "Invalid certificate in X-Cert header")


# --- Signed request auth dependency ---


@dataclass
class AuthenticatedUser:
    nip: str
    name: str
    cert_fingerprint: str


async def get_authenticated_user(request: Request, db=Depends(get_db)) -> AuthenticatedUser:
    cert_b64 = request.headers.get("x-cert")
    timestamp_str = request.headers.get("x-timestamp")
    signature_b64 = request.headers.get("x-signature")

    if not cert_b64 or not timestamp_str or not signature_b64:
        raise HTTPException(401, "Missing auth headers (X-Cert, X-Timestamp, X-Signature)")

    # Parse and verify certificate
    cert = parse_cert_der(cert_b64)
    verify_cert_chain(cert)

    # Check timestamp freshness
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise HTTPException(400, "X-Timestamp must be an integer (unix seconds)")

    now = int(time.time())
    if abs(now - timestamp) > TIMESTAMP_TOLERANCE:
        raise HTTPException(401, "Request timestamp too old or too far in the future")

    # Construct signed message: METHOD\nPATH\nTIMESTAMP
    # Path includes query string to prevent query param tampering
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    message = f"{request.method}\n{path}\n{timestamp_str}".encode()

    # Verify signature
    signature = base64.b64decode(signature_b64)
    public_key = cert.public_key()

    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            # Web Crypto produces IEEE P1363 (r||s) signatures, convert to DER
            key_byte_size = (public_key.key_size + 7) // 8
            if len(signature) == 2 * key_byte_size:
                r = int.from_bytes(signature[:key_byte_size], "big")
                s = int.from_bytes(signature[key_byte_size:], "big")
                signature = asym_utils.encode_dss_signature(r, s)
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        else:
            raise HTTPException(400, "Unsupported key type")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Signature verification failed")

    # Extract identity and auto-upsert user
    nip = extract_user_id(cert)
    name = extract_name(cert)
    fp = cert_fingerprint(cert)
    await upsert_user(db, nip, name, fp)

    return AuthenticatedUser(nip=nip, name=name, cert_fingerprint=fp)
