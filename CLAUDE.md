# ksefcio

KSeF invoice browser and payment basket generator.

## What this is

A web app for browsing invoices from KSeF (Krajowy System e-Faktur) and generating payment files (mBank format initially). Targets Polish businesses — initially two entities (JDG + spółka), ideally a public tool.

## Architecture

### Zero-knowledge server

The server never sees unencrypted user data. All invoice metadata and content is encrypted client-side with an AES key that only the user possesses. The server stores opaque blobs.

### Authentication

- Users authenticate via KSeF certificates (.key + .pem) issued by the Ministry of Finance.
- Auth is challenge-response: server sends nonce, client signs with private key, server verifies signature against the public cert and the KSeF CA chain (root: CCK MF Root, intermediate: CCK KSeF).
- User identity is extracted from the certificate subject (NIP or PESEL):
  - JDG (natural person, NIP): `serialNumber` = `TINPL-XXXXXXXXXX`
  - JDG (natural person, PESEL): `serialNumber` = `PNOPL-XXXXXXXXXXX`
  - Spółka (organization): `organizationIdentifier` = `VATPL-XXXXXXXXXX`

### Encryption

- AES key is generated randomly on first setup.
- The AES key is wrapped (encrypted) with the user's certificate public key and stored on the server as a blob.
- On certificate rotation (every ~2 years): client unwraps AES key with old private key, re-wraps with new private key, uploads new wrapped key. Data itself is never re-encrypted.
- Private keys never leave the browser. Server never sees the AES key.

### KSeF integration

- Backend proxies KSeF API calls (KSeF API lacks CORS headers for browser access).
- Client signs KSeF auth challenges, backend forwards requests with the resulting session token.

## Stack

- **Backend**: Python (uv for project/dependency management). FastAPI. Minimal — proxy + blob CRUD.
- **Frontend**: Vue.js + Vite. Handles all crypto (Web Crypto API), invoice parsing, UI.
- **Database**: SQLite.
- **No filesystem storage** — everything in the DB (encrypted blobs are small XML, not large binaries).

## Project layout

```
ksefcio/
  CLAUDE.md
  Makefile              # dev, build, clean, lint, test
  Makefile.local        # gitignored — deploy target config
  docker-compose.yml
  backend/
    Dockerfile          # multi-stage: builds frontend, then bundles with backend
    pyproject.toml
    src/ksefcio/
      __init__.py
      main.py           # FastAPI app, serves Vue static files in production
      db.py
      ksef_proxy.py
      auth.py
  frontend/
    package.json
    vite.config.ts      # proxies /api/* to FastAPI in dev
    src/
      ...
```

## Development

- `make dev-backend` — runs FastAPI dev server
- `make dev-frontend` — runs Vite dev server (proxies API to backend)
- Frontend and backend run as separate processes in dev.

## Build and deploy

- Single Docker container: multi-stage build compiles Vue, then serves static files from FastAPI.
- SQLite DB file mounted as a Docker volume for persistence.
- `make build` — builds the Docker image.
- `make deploy` — defined in Makefile.local (e.g. docker compose up on remote).

## Data model

```
users
  identity        -- primary key, NIP or PESEL extracted from verified certificate (plaintext)
  name            -- company/person name from certificate (plaintext)
  wrapped_aes_key -- AES key wrapped with user's certificate public key
  cert_fingerprint
  ...

invoices
  identity        -- FK to users
  ksef_ref        -- KSeF reference number
  ignored         -- bool, user marked as ignored
  paid            -- bool, user marked as paid
  encrypted_blob  -- encrypted invoice XML + metadata
```

## KSeF CA chain

Root and intermediate certs for verification:
- Root: https://ksef.podatki.gov.pl/media/0kodmn01/cck-mf-root.crt (valid until 2040)
- Intermediate: https://ksef.podatki.gov.pl/media/4vghzhga/cck-ksef.crt (valid until 2036)
- CRL: https://puesc.gov.pl/pki/crl/mfroot.crl

## KSeF API docs

- Official docs: https://github.com/CIRFMF/ksef-docs
- Certificate docs: https://github.com/CIRFMF/ksef-docs/blob/main/certyfikaty-KSeF.md
- Test API: https://api-test.ksef.mf.gov.pl/
