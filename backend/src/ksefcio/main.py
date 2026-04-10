import base64
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ksefcio.auth import AuthenticatedUser, get_authenticated_user
from ksefcio.db import (
    get_db,
    get_invoices,
    get_user,
    init_db,
    update_invoice_flags,
    update_wrapped_key,
    upsert_invoice,
)
from ksefcio.ksef_auth import router as ksef_auth_router
from ksefcio.ksef_proxy import close_ksef_client
from ksefcio.ksef_proxy import router as ksef_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_ksef_client()


app = FastAPI(title="ksefcio", lifespan=lifespan)

if os.environ.get("KSEFCIO_DEV"):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(ksef_auth_router)  # must be before ksef_router (catch-all)
app.include_router(ksef_router)


# --- User endpoints ---


class WrappedKeyRequest(BaseModel):
    wrapped_aes_key: str  # base64


@app.get("/api/users/me")
async def get_me(user: AuthenticatedUser = Depends(get_authenticated_user), db=Depends(get_db)):
    db_user = await get_user(db, user.identity)
    if not db_user:
        raise HTTPException(404, "User not found")
    return {
        "identity": db_user["identity"],
        "name": db_user["name"],
        "has_wrapped_key": db_user["wrapped_aes_key"] is not None,
        "wrapped_aes_key": (
            base64.b64encode(db_user["wrapped_aes_key"]).decode()
            if db_user["wrapped_aes_key"]
            else None
        ),
        "cert_fingerprint": db_user["cert_fingerprint"],
    }


@app.post("/api/users/me/wrapped-key")
async def set_wrapped_key(
    req: WrappedKeyRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user),
    db=Depends(get_db),
):
    await update_wrapped_key(
        db, user.identity, base64.b64decode(req.wrapped_aes_key), user.cert_fingerprint
    )
    return {"ok": True}


# --- Invoice endpoints ---


class InvoiceUpsert(BaseModel):
    encrypted_blob: str  # base64


class InvoiceFlags(BaseModel):
    ignored: bool | None = None
    paid: bool | None = None


@app.get("/api/invoices")
async def list_invoices(
    include_ignored: bool = False,
    user: AuthenticatedUser = Depends(get_authenticated_user),
    db=Depends(get_db),
):
    invoices = await get_invoices(db, user.identity, include_ignored)
    return [
        {
            "ksef_ref": inv["ksef_ref"],
            "ignored": bool(inv["ignored"]),
            "paid": bool(inv["paid"]),
            "encrypted_blob": base64.b64encode(inv["encrypted_blob"]).decode(),
            "created_at": inv["created_at"],
            "updated_at": inv["updated_at"],
        }
        for inv in invoices
    ]


@app.put("/api/invoices/{ksef_ref}")
async def upsert_invoice_endpoint(
    ksef_ref: str,
    req: InvoiceUpsert,
    user: AuthenticatedUser = Depends(get_authenticated_user),
    db=Depends(get_db),
):
    inv = await upsert_invoice(db, user.identity, ksef_ref, base64.b64decode(req.encrypted_blob))
    return {
        "ksef_ref": inv["ksef_ref"],
        "ignored": bool(inv["ignored"]),
        "paid": bool(inv["paid"]),
    }


@app.patch("/api/invoices/{ksef_ref}")
async def patch_invoice(
    ksef_ref: str,
    req: InvoiceFlags,
    user: AuthenticatedUser = Depends(get_authenticated_user),
    db=Depends(get_db),
):
    await update_invoice_flags(db, user.identity, ksef_ref, req.ignored, req.paid)
    return {"ok": True}


# --- Static files (production: serve built Vue app) ---

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
