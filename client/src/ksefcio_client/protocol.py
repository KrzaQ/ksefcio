import asyncio
import json
from typing import Any

OP_IDENTITY = "identity"
OP_SIGN_REQUEST = "sign_request"
OP_UNWRAP_AES = "unwrap_aes"
OP_DECRYPT = "decrypt"

ERR_BAD_REQUEST = "bad_request"
ERR_UNKNOWN_OP = "unknown_op"
ERR_NOT_READY = "not_ready"
ERR_UNWRAP_FAILED = "unwrap_failed"
ERR_AES_MISMATCH = "aes_already_set_mismatch"
ERR_DECRYPT_FAILED = "decrypt_failed"
ERR_INTERNAL = "internal_error"

# Hard cap on a single NDJSON line. Encrypted invoice blobs are small XML;
# 4 MiB leaves comfortable headroom and bounds memory per connection.
MAX_LINE_BYTES = 4 * 1024 * 1024


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Read one NDJSON line. Returns None on EOF. Raises on oversized or invalid JSON."""
    line = await reader.readuntil(b"\n")
    if len(line) > MAX_LINE_BYTES:
        raise ValueError("message exceeds size limit")
    return json.loads(line)


def write_message(writer: asyncio.StreamWriter, msg: dict[str, Any]) -> None:
    writer.write(json.dumps(msg, separators=(",", ":")).encode() + b"\n")


def ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"id": req_id, "ok": True, "result": result}


def err(req_id: Any, code: str, message: str) -> dict[str, Any]:
    return {"id": req_id, "ok": False, "error": {"code": code, "message": message}}
