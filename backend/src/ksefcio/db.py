import os
from contextlib import asynccontextmanager

import aiosqlite

DB_PATH = os.environ.get("KSEFCIO_DB_PATH", "ksefcio.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    nip TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wrapped_aes_key BLOB,
    cert_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nip TEXT NOT NULL REFERENCES users(nip),
    ksef_ref TEXT NOT NULL,
    ignored INTEGER NOT NULL DEFAULT 0,
    paid INTEGER NOT NULL DEFAULT 0,
    encrypted_blob BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(nip, ksef_ref)
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA)
        await db.commit()


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


# --- Users ---


async def get_user(db: aiosqlite.Connection, nip: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM users WHERE nip = ?", (nip,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_user(db: aiosqlite.Connection, nip: str, name: str, cert_fingerprint: str) -> dict:
    await db.execute(
        """INSERT INTO users (nip, name, cert_fingerprint)
           VALUES (?, ?, ?)
           ON CONFLICT(nip) DO UPDATE SET
             name = excluded.name,
             cert_fingerprint = excluded.cert_fingerprint,
             updated_at = datetime('now')""",
        (nip, name, cert_fingerprint),
    )
    await db.commit()
    return await get_user(db, nip)


async def update_wrapped_key(
    db: aiosqlite.Connection, nip: str, wrapped_aes_key: bytes, cert_fingerprint: str
):
    await db.execute(
        """UPDATE users
           SET wrapped_aes_key = ?, cert_fingerprint = ?, updated_at = datetime('now')
           WHERE nip = ?""",
        (wrapped_aes_key, cert_fingerprint, nip),
    )
    await db.commit()


# --- Invoices ---


async def get_invoices(
    db: aiosqlite.Connection, nip: str, include_ignored: bool = False
) -> list[dict]:
    if include_ignored:
        cursor = await db.execute(
            "SELECT * FROM invoices WHERE nip = ? ORDER BY created_at DESC", (nip,)
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM invoices WHERE nip = ? AND ignored = 0 ORDER BY created_at DESC",
            (nip,),
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def upsert_invoice(
    db: aiosqlite.Connection, nip: str, ksef_ref: str, encrypted_blob: bytes
) -> dict:
    await db.execute(
        """INSERT INTO invoices (nip, ksef_ref, encrypted_blob)
           VALUES (?, ?, ?)
           ON CONFLICT(nip, ksef_ref) DO UPDATE SET
             encrypted_blob = excluded.encrypted_blob,
             updated_at = datetime('now')""",
        (nip, ksef_ref, encrypted_blob),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM invoices WHERE nip = ? AND ksef_ref = ?", (nip, ksef_ref)
    )
    row = await cursor.fetchone()
    return dict(row)


async def update_invoice_flags(
    db: aiosqlite.Connection,
    nip: str,
    ksef_ref: str,
    ignored: bool | None = None,
    paid: bool | None = None,
):
    updates = []
    params = []
    if ignored is not None:
        updates.append("ignored = ?")
        params.append(int(ignored))
    if paid is not None:
        updates.append("paid = ?")
        params.append(int(paid))
    if not updates:
        return
    updates.append("updated_at = datetime('now')")
    params.extend([nip, ksef_ref])
    await db.execute(
        f"UPDATE invoices SET {', '.join(updates)} WHERE nip = ? AND ksef_ref = ?",
        params,
    )
    await db.commit()
