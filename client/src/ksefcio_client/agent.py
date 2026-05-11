import argparse
import asyncio
import base64
import getpass
import logging
import os
import signal
import sys
from pathlib import Path

from ksefcio_client import crypto, protocol, socket_path

log = logging.getLogger("ksefcio.agent")


class AgentState:
    def __init__(self, km: crypto.KeyMaterial) -> None:
        self.km = km
        self.aes_key: bytes | None = None
        self.wrapped_aes_input: bytes | None = None  # last accepted wrapped blob, for idempotency


async def handle_op(state: AgentState, msg: dict) -> dict:
    op = msg.get("op")
    req_id = msg.get("id")

    if op == protocol.OP_IDENTITY:
        km = state.km
        return protocol.ok(req_id, {
            "identity": km.identity,
            "name": km.name,
            "cert_b64": base64.b64encode(km.cert_der).decode(),
            "cert_fingerprint": km.fingerprint,
            "key_type": km.key_type,
            "aes_unwrapped": state.aes_key is not None,
        })

    if op == protocol.OP_SIGN_REQUEST:
        try:
            method = msg["method"]
            path = msg["path"]
            ts = int(msg["ts"])
        except (KeyError, TypeError, ValueError):
            return protocol.err(req_id, protocol.ERR_BAD_REQUEST, "method, path, ts required")
        if not isinstance(method, str) or not isinstance(path, str):
            return protocol.err(req_id, protocol.ERR_BAD_REQUEST, "method and path must be strings")
        sig = crypto.sign_request(state.km, method, path, ts)
        return protocol.ok(req_id, {"signature_b64": base64.b64encode(sig).decode()})

    if op == protocol.OP_UNWRAP_AES:
        try:
            wrapped = base64.b64decode(msg["wrapped_b64"], validate=True)
        except (KeyError, ValueError):
            return protocol.err(req_id, protocol.ERR_BAD_REQUEST, "wrapped_b64 (base64) required")
        if state.aes_key is not None:
            if wrapped == state.wrapped_aes_input:
                return protocol.ok(req_id, {"already_set": True})
            return protocol.err(req_id, protocol.ERR_AES_MISMATCH,
                                "AES key already set from a different wrapped blob")
        try:
            aes = crypto.unwrap_aes_key(state.km, wrapped)
        except Exception as e:
            return protocol.err(req_id, protocol.ERR_UNWRAP_FAILED, str(e))
        if len(aes) != 32:
            return protocol.err(req_id, protocol.ERR_UNWRAP_FAILED,
                                f"unwrapped key has unexpected length {len(aes)} (need 32)")
        state.aes_key = aes
        state.wrapped_aes_input = wrapped
        return protocol.ok(req_id, {"already_set": False})

    if op == protocol.OP_DECRYPT:
        if state.aes_key is None:
            return protocol.err(req_id, protocol.ERR_NOT_READY,
                                "AES key not unwrapped yet; call unwrap_aes first")
        try:
            blob = base64.b64decode(msg["blob_b64"], validate=True)
        except (KeyError, ValueError):
            return protocol.err(req_id, protocol.ERR_BAD_REQUEST, "blob_b64 (base64) required")
        try:
            plaintext = crypto.decrypt_blob(state.aes_key, blob)
        except Exception as e:
            return protocol.err(req_id, protocol.ERR_DECRYPT_FAILED, str(e))
        return protocol.ok(req_id, {"plaintext_b64": base64.b64encode(plaintext).decode()})

    return protocol.err(req_id, protocol.ERR_UNKNOWN_OP, f"unknown op: {op!r}")


def make_handler(state: AgentState):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername") or "<unix>"
        log.info("client connected: %s", peer)
        try:
            while True:
                try:
                    msg = await protocol.read_message(reader)
                except asyncio.IncompleteReadError:
                    break  # clean EOF
                except ValueError as e:
                    protocol.write_message(writer, protocol.err(None, protocol.ERR_BAD_REQUEST, str(e)))
                    await writer.drain()
                    break
                if msg is None:
                    break
                try:
                    response = await handle_op(state, msg)
                except Exception:
                    log.exception("op dispatch failed")
                    response = protocol.err(msg.get("id"), protocol.ERR_INTERNAL, "internal error")
                protocol.write_message(writer, response)
                await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            log.info("client disconnected: %s", peer)

    return handle


async def serve(state: AgentState, sock_path: Path) -> None:
    if sock_path.exists():
        # If the socket file exists but isn't accepting connections, remove it.
        # If something is listening, bind() will fail loudly below.
        try:
            sock_path.unlink()
        except OSError as e:
            log.warning("could not remove stale socket %s: %s", sock_path, e)

    prev_umask = os.umask(0o077)
    try:
        server = await asyncio.start_unix_server(make_handler(state), path=str(sock_path))
    finally:
        os.umask(prev_umask)
    os.chmod(sock_path, 0o600)
    log.info("ksefcio-agent ready: socket=%s identity=%s name=%s",
             sock_path, state.km.identity, state.km.name)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async with server:
        serve_task = asyncio.create_task(server.serve_forever())
        await stop.wait()
        log.info("shutdown requested")
        serve_task.cancel()
        try:
            await serve_task
        except asyncio.CancelledError:
            pass

    try:
        sock_path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("could not unlink socket %s on exit: %s", sock_path, e)


def daemonize(log_file: Path | None, pid_file: Path | None) -> None:
    """Double-fork into the background. Must be called BEFORE the asyncio loop starts."""
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    os.chdir("/")
    os.umask(0o077)

    null_rd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_rd, 0)
    os.close(null_rd)

    out_path = str(log_file) if log_file else os.devnull
    out_fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(out_fd, 1)
    os.dup2(out_fd, 2)
    os.close(out_fd)

    if pid_file:
        pid_file.write_text(f"{os.getpid()}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ksefcio-agent",
        description="Local credential agent for ksefcio (key custodian, no network).",
    )
    p.add_argument("--cert", required=True, type=Path, help="path to PEM certificate")
    p.add_argument("--key", required=True, type=Path, help="path to PEM PKCS#8 private key")
    p.add_argument("--socket", type=Path, default=None,
                   help=f"unix socket path (default: {socket_path.default_path()})")
    p.add_argument("--daemon", action="store_true",
                   help="fork into background AFTER reading passphrase")
    p.add_argument("--pid-file", type=Path, default=None,
                   help="path to write PID file (daemon mode only)")
    p.add_argument("--log-file", type=Path, default=None,
                   help="log file path (daemon mode; defaults to /dev/null)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.cert.is_file():
        print(f"cert not found: {args.cert}", file=sys.stderr)
        return 1
    if not args.key.is_file():
        print(f"key not found: {args.key}", file=sys.stderr)
        return 1

    passphrase = getpass.getpass("Key passphrase (empty for unencrypted): ").encode()
    try:
        km = crypto.load_keypair(args.cert, args.key, passphrase or None)
    except Exception as e:
        print(f"failed to load keypair: {e}", file=sys.stderr)
        return 1
    finally:
        passphrase = b""  # drop the local reference; bytes themselves may linger in memory

    sock_path = args.socket or socket_path.default_path()
    print(f"loaded: identity={km.identity} name={km.name} fp={km.fingerprint[:12]}…",
          file=sys.stderr)
    print(f"socket: {sock_path}", file=sys.stderr)

    if args.daemon:
        pid_file = args.pid_file or (sock_path.parent / "ksefcio-agent.pid")
        print(f"daemonizing; pid-file={pid_file} log-file={args.log_file or '/dev/null'}",
              file=sys.stderr)
        daemonize(args.log_file, pid_file)

    state = AgentState(km)
    try:
        asyncio.run(serve(state, sock_path))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
