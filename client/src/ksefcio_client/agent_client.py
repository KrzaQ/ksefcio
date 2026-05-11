"""Async client for the local ksefcio-agent Unix socket.

Holds one persistent connection and serializes requests with an asyncio.Lock,
because the wire is a single stream of NDJSON request/response pairs. On any
I/O error the connection is torn down; the next call reconnects automatically.
"""
import asyncio
import base64
import json
from dataclasses import dataclass
from pathlib import Path

from ksefcio_client import protocol


class AgentError(RuntimeError):
    """The agent rejected a request or the connection broke."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class AgentIdentity:
    identity: str
    name: str
    cert_b64: str
    cert_fingerprint: str
    key_type: str
    aes_unwrapped: bool


class AgentClient:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.open_unix_connection(str(self.socket_path))
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as e:
            raise AgentError("agent_unreachable",
                             f"could not connect to ksefcio-agent at {self.socket_path}: {e}") from e

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = self._writer = None

    async def _ensure_connected(self) -> None:
        if self._reader is None or self._writer is None or self._writer.is_closing():
            await self.close()
            await self.connect()

    async def _call(self, op: str, **fields: object) -> dict:
        async with self._lock:
            for attempt in (1, 2):  # one retry after a reconnect
                try:
                    await self._ensure_connected()
                    assert self._reader and self._writer
                    self._next_id += 1
                    req = {"id": str(self._next_id), "op": op, **fields}
                    self._writer.write(json.dumps(req, separators=(",", ":")).encode() + b"\n")
                    await self._writer.drain()
                    line = await self._reader.readuntil(b"\n")
                    if len(line) > protocol.MAX_LINE_BYTES:
                        raise AgentError("internal_error", "response exceeds size limit")
                    msg = json.loads(line)
                    break
                except (ConnectionError, asyncio.IncompleteReadError, BrokenPipeError) as e:
                    await self.close()
                    if attempt == 2:
                        raise AgentError("agent_unreachable",
                                         f"connection to ksefcio-agent lost: {e}") from e
                    continue

        if not msg.get("ok"):
            err = msg.get("error") or {}
            raise AgentError(err.get("code", "internal_error"),
                             err.get("message", "agent returned an error"))
        return msg.get("result") or {}

    async def identity(self) -> AgentIdentity:
        r = await self._call(protocol.OP_IDENTITY)
        return AgentIdentity(
            identity=r["identity"],
            name=r["name"],
            cert_b64=r["cert_b64"],
            cert_fingerprint=r["cert_fingerprint"],
            key_type=r["key_type"],
            aes_unwrapped=r["aes_unwrapped"],
        )

    async def sign_request(self, method: str, path: str, ts: int) -> bytes:
        r = await self._call(protocol.OP_SIGN_REQUEST, method=method, path=path, ts=ts)
        return base64.b64decode(r["signature_b64"])

    async def unwrap_aes(self, wrapped: bytes) -> bool:
        """Returns True if the key was already set (idempotent no-op)."""
        r = await self._call(protocol.OP_UNWRAP_AES, wrapped_b64=base64.b64encode(wrapped).decode())
        return bool(r.get("already_set"))

    async def decrypt(self, blob: bytes) -> bytes:
        r = await self._call(protocol.OP_DECRYPT, blob_b64=base64.b64encode(blob).decode())
        return base64.b64decode(r["plaintext_b64"])
