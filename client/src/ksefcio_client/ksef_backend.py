"""Async HTTP client for the ksefcio backend.

Every request is signed via the local agent (which holds the private key).
The signed message is METHOD\\nPATH[?QUERY]\\nTIMESTAMP — must match
backend/src/ksefcio/auth.py exactly.
"""
import base64
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from ksefcio_client.agent_client import AgentClient


class BackendError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class KsefcioBackend:
    def __init__(self, base_url: str, agent: AgentClient, cert_b64: str, verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.agent = agent
        self.cert_b64 = cert_b64
        # Reasonable defaults: 30s for the wrapped-key fetch + full invoice listings.
        self._client = httpx.AsyncClient(timeout=30.0, verify=verify, base_url=self.base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "KsefcioBackend":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    def _canonical_path(self, url: str) -> str:
        """Mirror FastAPI's request.url.path[+query] used in auth.py:170."""
        parts = urlsplit(url)
        return parts.path + (f"?{parts.query}" if parts.query else "")

    async def _signed_request(self, method: str, path: str) -> httpx.Response:
        url = f"{self.base_url}{path}"
        signed_path = self._canonical_path(url)
        ts = int(time.time())
        signature = await self.agent.sign_request(method, signed_path, ts)

        headers = {
            "X-Cert": self.cert_b64,
            "X-Timestamp": str(ts),
            "X-Signature": base64.b64encode(signature).decode(),
        }
        return await self._client.request(method, path, headers=headers)

    async def _get_json(self, path: str) -> Any:
        resp = await self._signed_request("GET", path)
        if resp.status_code >= 400:
            raise BackendError(resp.status_code, resp.text)
        return resp.json()

    async def get_me(self) -> dict:
        """Returns {identity, name, has_wrapped_key, wrapped_aes_key, cert_fingerprint, nips}."""
        return await self._get_json("/api/users/me")

    async def list_invoices(self, nip: str, include_ignored: bool = True) -> list[dict]:
        """Returns invoices with encrypted_blob (base64). include_ignored=True by default —
        the shim filters client-side so it can fold corrections regardless of ignore state."""
        suffix = "?include_ignored=true" if include_ignored else ""
        return await self._get_json(f"/api/invoices/{nip}{suffix}")
