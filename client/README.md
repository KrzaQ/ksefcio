# ksefcio-client

Local credential agent for ksefcio. Holds your KSeF private key and AES key
in memory, exposes crypto ops to a separate MCP shim over a Unix socket.

The agent has no network access — it does crypto only. The MCP shim (Stage 2,
not yet built) handles all HTTP traffic to the ksefcio backend.

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

## Tests

```
make client-test
```

These exercise the EC ECDH+AES-KW and RSA-OAEP paths against ephemeral keys
to match what the frontend does — no real KSeF cert required.
