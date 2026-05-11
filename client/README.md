# ksefcio-client

Two pieces:

- **`ksefcio-agent`** — long-running credential vault. Holds the KSeF private
  key and AES key in memory. Exposes crypto ops (sign, unwrap, decrypt) over a
  Unix socket. **No network access.**
- **`ksefcio-mcp`** — stdio MCP server spawned by Claude Code per session.
  Talks to the ksefcio backend over HTTP, routes all crypto through the agent,
  exposes read-only tools (`list_entities`, `list_invoices`, `get_invoice`,
  `unpaid_summary`). **Holds no secrets.**

The split is deliberate: the MCP shim is what Claude prompts can talk to, so
it can't reach the private key even if compromised. It can only ask the agent
to sign an exact `METHOD\nPATH\nTIMESTAMP` string or decrypt a specific blob
it already has.

## Install

```
make client-install   # from repo root
```

## Run

```
make dev-agent CERT=~/path/to/ksefcio.crt KEY=~/path/to/ksefcio.key
```

Or directly:

```
cd client
uv run ksefcio-agent --cert ~/path/to/cert.pem --key ~/path/to/key.pem
```

You'll be prompted for the key passphrase (press Enter if the key is
unencrypted). On success the agent prints the socket path and stays in the
foreground. `Ctrl-C` to stop.

### Daemon mode

After the passphrase prompt, fork into the background:

```
uv run ksefcio-agent --cert … --key … --daemon \
    --log-file ~/.local/share/ksefcio/agent.log
```

PID file defaults to `$XDG_RUNTIME_DIR/ksefcio-agent.pid`. Stop with
`kill $(cat that-pid-file)`.

## Manual verification with socat

In one terminal, start the agent. In another:

```
socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/ksefcio-agent.sock
```

Then paste NDJSON requests (one per line):

```json
{"id":"1","op":"identity"}
{"id":"2","op":"sign_request","method":"GET","path":"/api/users/me","ts":1746000000}
```

The agent replies with one NDJSON line per request.

## Op reference

| op             | input fields                              | output fields                                                                              |
|----------------|-------------------------------------------|--------------------------------------------------------------------------------------------|
| `identity`     | —                                         | `identity`, `name`, `cert_b64`, `cert_fingerprint`, `key_type`, `aes_unwrapped`            |
| `sign_request` | `method`, `path`, `ts` (int unix seconds) | `signature_b64` (PKCS1v15-SHA256 for RSA, ECDSA-SHA256 IEEE P1363 for EC)                  |
| `unwrap_aes`   | `wrapped_b64`                             | `already_set` (bool); idempotent — re-sending the same blob is a no-op                     |
| `decrypt`      | `blob_b64` (IV‖ciphertext+tag)            | `plaintext_b64`; fails with `not_ready` if `unwrap_aes` hasn't been called                 |

Errors come back as `{"id":…,"ok":false,"error":{"code":…,"message":…}}`.

## MCP shim (`ksefcio-mcp`)

Run once the agent is up. The shim is normally spawned by Claude Code, but
you can sanity-check it from the shell:

```
make dev-mcp BACKEND=https://your-ksefcio.example
```

Or directly:

```
cd client
uv run ksefcio-mcp --backend https://your-ksefcio.example
```

The shim connects to the agent, asks it for `identity()`, fetches the wrapped
AES key from `/api/users/me`, asks the agent to unwrap it, then serves MCP over
stdio. Fails fast if the agent isn't running.

CLI flags:

| flag                | env                       | meaning                                           |
|---------------------|---------------------------|---------------------------------------------------|
| `--backend URL`     | `KSEFCIO_BACKEND_URL`     | ksefcio backend URL (required)                    |
| `--socket PATH`     | —                         | agent socket path (default: `$XDG_RUNTIME_DIR/ksefcio-agent.sock`) |
| `--insecure`        | —                         | skip TLS verification (dev backends with self-signed certs) |
| `--verbose`         | —                         | DEBUG-level stderr logs                           |

### Wiring into Claude Code

Add to a `.mcp.json` (project-scoped) or `~/.claude.json` (user-scoped):

```json
{
  "mcpServers": {
    "ksefcio": {
      "command": "ksefcio-mcp",
      "args": ["--backend", "https://your-ksefcio.example"]
    }
  }
}
```

If `ksefcio-mcp` isn't on PATH (e.g. you didn't `pipx install` it), point at the
uv-managed binary directly:

```json
{
  "mcpServers": {
    "ksefcio": {
      "command": "/home/you/code/ksefcio/client/.venv/bin/ksefcio-mcp",
      "args": ["--backend", "https://your-ksefcio.example"]
    }
  }
}
```

Start `ksefcio-agent` before launching Claude. The shim will fail to initialize
if the agent socket isn't reachable.

### MCP tools

| tool                                            | what it does                                                                          |
|-------------------------------------------------|---------------------------------------------------------------------------------------|
| `list_entities()`                               | Identity + accessible NIPs                                                            |
| `list_invoices(nip, include_ignored?, only_unpaid?, since?, limit=50)` | Headline list, corrections folded into parents                  |
| `get_invoice(nip, ksef_ref)`                    | Full invoice with line items and corrections                                          |
| `unpaid_summary(nip?)`                          | Count + total brutto of unpaid (non-ignored) invoices, per-NIP + grand total          |

## Tests

```
make client-test
```

Crypto tests exercise the EC ECDH+AES-KW and RSA-OAEP paths against ephemeral
keys to match what the frontend does — no real KSeF cert required. Invoice
tests cover correction folding (sums, orphans, paid mismatches).
