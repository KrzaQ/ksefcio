"""KSeF XAdES-BES auth: split signing (backend builds XML, frontend signs)."""

import base64
import hashlib
import time
import uuid
from datetime import datetime, timezone

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Request
from lxml import etree
from pydantic import BaseModel

from ksefcio.auth import AuthenticatedUser, get_authenticated_user, parse_cert_der
from ksefcio.ksef_proxy import KSEF_BASE_URL, get_ksef_client

router = APIRouter(prefix="/api/ksef/auth")

# --- Namespaces and algorithm URIs ---

NS_AUTH = "http://ksef.mf.gov.pl/auth/token/2.0"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"

C14N_ALGO = "http://www.w3.org/2001/10/xml-exc-c14n#"
DIGEST_ALGO = "http://www.w3.org/2001/04/xmlenc#sha256"
SIG_ALGO_RSA = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SIG_ALGO_EC = "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
TRANSFORM_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

# --- In-memory pending request store (TTL 5 min) ---

REQUEST_TTL = 300

# (xml_root, signature_value_element, created_at)
_pending: dict[str, tuple[etree._Element, etree._Element, float]] = {}


def _cleanup_pending():
    now = time.time()
    expired = [k for k, (_, _, t) in _pending.items() if now - t > REQUEST_TTL]
    for k in expired:
        del _pending[k]


# --- XML construction helpers ---


def _ds(tag: str) -> str:
    return f"{{{NS_DS}}}{tag}"


def _xades(tag: str) -> str:
    return f"{{{NS_XADES}}}{tag}"


def _auth(tag: str) -> str:
    return f"{{{NS_AUTH}}}{tag}"


def _c14n(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n", exclusive=True)


def _sha256_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _extract_token(val) -> str:
    """KSeF returns tokens as either a string or {"token": "...", "validUntil": "..."}."""
    return val["token"] if isinstance(val, dict) else val


def _detect_sig_algo(cert: x509.Certificate) -> str:
    if isinstance(cert.public_key(), ec.EllipticCurvePublicKey):
        return SIG_ALGO_EC
    return SIG_ALGO_RSA


def build_xades_envelope(
    challenge: str,
    nip: str,
    cert: x509.Certificate,
) -> tuple[etree._Element, etree._Element, bytes]:
    """Build unsigned XAdES-BES AuthTokenRequest XML.

    Returns (xml_root, signature_value_element, signed_info_c14n_bytes).
    """
    sig_id = f"Signature-{uuid.uuid4()}"
    sp_id = f"SignedProperties-{uuid.uuid4()}"

    # --- AuthTokenRequest root ---
    root = etree.Element(
        _auth("AuthTokenRequest"),
        nsmap={None: NS_AUTH, "xsi": "http://www.w3.org/2001/XMLSchema-instance"},
    )

    etree.SubElement(root, _auth("Challenge")).text = challenge
    ctx = etree.SubElement(root, _auth("ContextIdentifier"))
    etree.SubElement(ctx, _auth("Nip")).text = nip
    etree.SubElement(root, _auth("SubjectIdentifierType")).text = "certificateSubject"

    # --- ds:Signature ---
    sig_algo = _detect_sig_algo(cert)

    signature = etree.SubElement(root, _ds("Signature"), nsmap={"ds": NS_DS})
    signature.set("Id", sig_id)

    # SignedInfo
    signed_info = etree.SubElement(signature, _ds("SignedInfo"))
    etree.SubElement(signed_info, _ds("CanonicalizationMethod")).set("Algorithm", C14N_ALGO)
    etree.SubElement(signed_info, _ds("SignatureMethod")).set("Algorithm", sig_algo)

    # Reference 1: document (enveloped)
    ref_doc = etree.SubElement(signed_info, _ds("Reference"))
    ref_doc.set("URI", "")
    transforms = etree.SubElement(ref_doc, _ds("Transforms"))
    etree.SubElement(transforms, _ds("Transform")).set("Algorithm", TRANSFORM_ENVELOPED)
    etree.SubElement(transforms, _ds("Transform")).set("Algorithm", C14N_ALGO)
    etree.SubElement(ref_doc, _ds("DigestMethod")).set("Algorithm", DIGEST_ALGO)
    doc_digest_el = etree.SubElement(ref_doc, _ds("DigestValue"))

    # Reference 2: SignedProperties
    ref_sp = etree.SubElement(signed_info, _ds("Reference"))
    ref_sp.set("URI", f"#{sp_id}")
    ref_sp.set("Type", "http://uri.etsi.org/01903#SignedProperties")
    sp_transforms = etree.SubElement(ref_sp, _ds("Transforms"))
    etree.SubElement(sp_transforms, _ds("Transform")).set("Algorithm", C14N_ALGO)
    etree.SubElement(ref_sp, _ds("DigestMethod")).set("Algorithm", DIGEST_ALGO)
    sp_digest_el = etree.SubElement(ref_sp, _ds("DigestValue"))

    # SignatureValue (empty, to be filled after client signs)
    sig_value = etree.SubElement(signature, _ds("SignatureValue"))

    # KeyInfo
    key_info = etree.SubElement(signature, _ds("KeyInfo"))
    x509_data = etree.SubElement(key_info, _ds("X509Data"))
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    etree.SubElement(x509_data, _ds("X509Certificate")).text = base64.b64encode(
        cert_der
    ).decode("ascii")

    # ds:Object → xades:QualifyingProperties → SignedProperties
    obj = etree.SubElement(signature, _ds("Object"))
    qual_props = etree.SubElement(
        obj, _xades("QualifyingProperties"), nsmap={"xades": NS_XADES}
    )
    qual_props.set("Target", f"#{sig_id}")

    signed_props = etree.SubElement(qual_props, _xades("SignedProperties"))
    signed_props.set("Id", sp_id)

    sig_props = etree.SubElement(signed_props, _xades("SignedSignatureProperties"))

    # SigningTime
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    etree.SubElement(sig_props, _xades("SigningTime")).text = now

    # SigningCertificate
    signing_cert = etree.SubElement(sig_props, _xades("SigningCertificate"))
    cert_el = etree.SubElement(signing_cert, _xades("Cert"))

    cert_digest_el = etree.SubElement(cert_el, _xades("CertDigest"))
    etree.SubElement(cert_digest_el, _ds("DigestMethod")).set("Algorithm", DIGEST_ALGO)
    etree.SubElement(cert_digest_el, _ds("DigestValue")).text = _sha256_b64(cert_der)

    issuer_serial = etree.SubElement(cert_el, _xades("IssuerSerial"))
    etree.SubElement(issuer_serial, _ds("X509IssuerName")).text = (
        cert.issuer.rfc4514_string()
    )
    etree.SubElement(issuer_serial, _ds("X509SerialNumber")).text = str(
        cert.serial_number
    )

    # --- Compute digests ---

    # 1. SignedProperties digest
    sp_digest_el.text = _sha256_b64(_c14n(signed_props))

    # 2. Document digest (enveloped: remove Signature, C14N root, re-add)
    root.remove(signature)
    doc_digest_el.text = _sha256_b64(_c14n(root))
    root.append(signature)

    # 3. Canonicalize SignedInfo (this is what the client signs)
    signed_info_c14n = _c14n(signed_info)

    return root, sig_value, signed_info_c14n


# --- Endpoints ---


class PrepareRequest(BaseModel):
    nip: str


class PrepareResponse(BaseModel):
    request_id: str
    signed_info_b64: str


class FinalizeRequest(BaseModel):
    request_id: str
    signature_value_b64: str


@router.post("/prepare")
async def prepare(
    req: PrepareRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_authenticated_user),
):
    _cleanup_pending()

    client = await get_ksef_client()

    # Get challenge from KSeF
    challenge_resp = await client.post(
        "/auth/challenge",
        json={"contextIdentifier": {"type": "onip", "identifier": req.nip}},
    )
    if challenge_resp.status_code != 200:
        raise HTTPException(
            502, f"KSeF challenge failed: {challenge_resp.status_code} {challenge_resp.text}"
        )

    data = challenge_resp.json()
    challenge = data["challenge"]

    # Parse cert from auth header
    cert_b64 = request.headers.get("x-cert")
    cert = parse_cert_der(cert_b64)

    # Build XAdES envelope
    xml_root, sig_value_el, signed_info_c14n = build_xades_envelope(
        challenge, req.nip, cert
    )

    # Store for finalize
    request_id = str(uuid.uuid4())
    _pending[request_id] = (xml_root, sig_value_el, time.time())

    return PrepareResponse(
        request_id=request_id,
        signed_info_b64=base64.b64encode(signed_info_c14n).decode("ascii"),
    )


@router.post("/finalize")
async def finalize(
    req: FinalizeRequest,
    _user: AuthenticatedUser = Depends(get_authenticated_user),
):
    _cleanup_pending()

    entry = _pending.pop(req.request_id, None)
    if entry is None:
        raise HTTPException(404, "Request expired or not found")

    xml_root, sig_value_el, _ = entry

    # Insert signature value
    sig_value_el.text = req.signature_value_b64

    # Serialize XML
    xml_bytes = etree.tostring(xml_root, xml_declaration=True, encoding="UTF-8")

    client = await get_ksef_client()

    # Submit signed XML to KSeF
    submit_resp = await client.post(
        "/auth/xades-signature",
        content=xml_bytes,
        headers={"Content-Type": "application/xml"},
    )
    if submit_resp.status_code not in (200, 202):
        raise HTTPException(
            502, f"KSeF xades-signature failed: {submit_resp.status_code} {submit_resp.text}"
        )

    submit_data = submit_resp.json()
    auth_token = _extract_token(submit_data["authenticationToken"])
    ref_number = submit_data["referenceNumber"]

    # Poll for completion
    poll_data = None
    for _ in range(30):
        poll_resp = await client.get(
            f"/auth/{ref_number}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        if poll_resp.status_code == 200:
            poll_data = poll_resp.json()
            status = poll_data.get("status", {})
            status_code = status.get("code", 0)

            if status_code == 200:
                break
            if status_code >= 400:
                desc = status.get("description", "Unknown error")
                details = status.get("details", [])
                raise HTTPException(
                    502,
                    f"KSeF auth failed: {status_code} {desc} — {'; '.join(details)}",
                )
        await _async_sleep(1)
    else:
        raise HTTPException(
            504,
            f"KSeF auth polling timed out. Last response: {poll_resp.status_code} {poll_resp.text}",
        )

    # Redeem tokens
    redeem_resp = await client.post(
        "/auth/token/redeem",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    if redeem_resp.status_code not in (200, 202):
        raise HTTPException(
            502, f"KSeF token redeem failed: {redeem_resp.status_code} {redeem_resp.text}"
        )

    tokens = redeem_resp.json()
    return {
        "access_token": _extract_token(tokens.get("accessToken", auth_token)),
        "refresh_token": _extract_token(tokens.get("refreshToken", "")),
    }


async def _async_sleep(seconds: float):
    import asyncio

    await asyncio.sleep(seconds)
