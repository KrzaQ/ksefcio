"""ksefcio MCP shim (stdio transport).

Spawned by Claude per session. Connects to the local ksefcio-agent for crypto,
talks to the ksefcio backend over HTTP, exposes read-only MCP tools. Holds no
secrets itself — everything sensitive stays in the agent.
"""
import argparse
import asyncio
import base64
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ksefcio_client import socket_path, tools
from ksefcio_client.agent_client import AgentClient, AgentError
from ksefcio_client.ksef_backend import KsefcioBackend

log = logging.getLogger("ksefcio.shim")


async def _initialize(backend_url: str, sock: Path, verify_tls: bool) -> tools.ShimState:
    agent = AgentClient(sock)
    try:
        await agent.connect()
        ident = await agent.identity()
        log.info("agent: identity=%s name=%s key_type=%s", ident.identity, ident.name, ident.key_type)

        backend = KsefcioBackend(backend_url, agent, cert_b64=ident.cert_b64, verify=verify_tls)
        me = await backend.get_me()
        wrapped_b64 = me.get("wrapped_aes_key")
        if not wrapped_b64:
            await backend.aclose()
            await agent.close()
            raise RuntimeError(
                "ksefcio backend has no wrapped_aes_key for this identity yet — "
                "log in via the web UI once to set it up."
            )
        await agent.unwrap_aes(base64.b64decode(wrapped_b64))
        log.info("aes key unwrapped; nips=%s", me.get("nips"))

        return tools.ShimState(
            agent=agent,
            backend=backend,
            identity=me.get("identity", ident.identity),
            name=me.get("name", ident.name),
            nips=list(me.get("nips") or []),
        )
    except Exception:
        await agent.close()
        raise


def _build_mcp(state: tools.ShimState) -> FastMCP:
    mcp = FastMCP(
        "ksefcio",
        instructions=(
            f"ksefcio: Polish KSeF invoice browser for identity {state.identity} ({state.name}). "
            f"Available NIPs: {', '.join(state.nips) or '(none synced yet)'}. "
            "All data is end-to-end encrypted; this server decrypts via a local agent."
        ),
    )

    @mcp.tool()
    async def list_entities() -> dict[str, Any]:
        """List the NIPs (Polish tax IDs) this identity has access to in ksefcio.
        Returns the identity, display name, and the list of NIPs whose invoices can be queried."""
        return await tools.list_entities(state)

    @mcp.tool()
    async def list_invoices(
        nip: str,
        include_ignored: bool = False,
        only_unpaid: bool = False,
        since: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List invoices for a given NIP, with corrections folded into their parents.

        Args:
            nip: 10-digit Polish tax ID. Must be one of list_entities().nips.
            include_ignored: include invoices the user marked as ignored (default false).
            only_unpaid: drop invoices the user already marked as paid (default false).
            since: ISO date (YYYY-MM-DD); only invoices with issue_date >= since are returned.
            limit: maximum number of rows to return (default 50).

        Returns headline fields per invoice (number, dates, parties, amounts, paid/ignored flags,
        and correction info). Use get_invoice(nip, ksef_ref) for line items and full corrections.
        """
        return await tools.list_invoices(state, nip, include_ignored, only_unpaid, since, limit)

    @mcp.tool()
    async def get_invoice(nip: str, ksef_ref: str) -> dict[str, Any]:
        """Full details for one invoice, including line items and any corrections that target it.

        Args:
            nip: 10-digit Polish tax ID.
            ksef_ref: KSeF reference number (e.g. "1234567890-20260411-AB12CD-EF").
        """
        return await tools.get_invoice(state, nip, ksef_ref)

    @mcp.tool()
    async def unpaid_summary(nip: str | None = None) -> dict[str, Any]:
        """Count and total brutto of unpaid (non-ignored, non-orphan-correction) invoices.

        Args:
            nip: 10-digit Polish tax ID to scope to. If omitted, sums across all accessible NIPs.
        """
        return await tools.unpaid_summary(state, nip)

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ksefcio-mcp",
        description="MCP stdio shim for ksefcio. Reads private-key ops from the local agent.",
    )
    p.add_argument("--backend", default=os.environ.get("KSEFCIO_BACKEND_URL"),
                   help="ksefcio backend URL (or set KSEFCIO_BACKEND_URL)")
    p.add_argument("--socket", type=Path, default=None,
                   help=f"agent socket path (default: {socket_path.default_path()})")
    p.add_argument("--insecure", action="store_true",
                   help="skip TLS certificate verification (for dev backends)")
    p.add_argument("--verbose", action="store_true", help="log to stderr at DEBUG level")
    return p.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    if not args.backend:
        print("--backend or KSEFCIO_BACKEND_URL is required", file=sys.stderr)
        return 2

    sock = args.socket or socket_path.default_path()

    try:
        state = await _initialize(args.backend, sock, verify_tls=not args.insecure)
    except AgentError as e:
        print(f"ksefcio-mcp: agent error: {e}", file=sys.stderr)
        print(f"  hint: start ksefcio-agent (socket: {sock})", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ksefcio-mcp: initialization failed: {e}", file=sys.stderr)
        return 1

    mcp = _build_mcp(state)
    try:
        await mcp.run_stdio_async()
    finally:
        await state.backend.aclose()
        await state.agent.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
