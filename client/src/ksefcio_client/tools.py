"""MCP tool implementations. Stateless functions that operate on a ShimState."""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from ksefcio_client.agent_client import AgentClient
from ksefcio_client.invoice import (
    DecryptedInvoice,
    EffectiveInvoice,
    effective_to_detail,
    effective_to_summary,
    enrich_from_xml,
    fold_corrections,
)
from ksefcio_client.ksef_backend import KsefcioBackend

log = logging.getLogger("ksefcio.shim.tools")


@dataclass
class ShimState:
    agent: AgentClient
    backend: KsefcioBackend
    identity: str
    name: str
    nips: list[str]


async def _decrypt_one(state: ShimState, nip: str, row: dict) -> DecryptedInvoice | None:
    import base64
    blob = base64.b64decode(row["encrypted_blob"])
    try:
        plaintext = await state.agent.decrypt(blob)
        decoded = json.loads(plaintext)
    except Exception as e:
        log.warning("decrypt/parse failed for %s/%s: %s", nip, row.get("ksef_ref"), e)
        return None
    enrich_from_xml(decoded)
    return DecryptedInvoice.from_row(nip, row, decoded)


async def _fetch_effective(state: ShimState, nip: str) -> list[EffectiveInvoice]:
    """All effective invoices for a NIP (corrections folded). Includes ignored
    rows on the way in so folding sees the full picture; callers filter after."""
    raw = await state.backend.list_invoices(nip, include_ignored=True)
    decrypted = await asyncio.gather(*[_decrypt_one(state, nip, row) for row in raw])
    invoices = [d for d in decrypted if d is not None]
    return fold_corrections(invoices)


def _validate_nip(state: ShimState, nip: str) -> None:
    if nip not in state.nips:
        raise ValueError(
            f"unknown NIP {nip!r}; this identity has access to: {', '.join(state.nips) or '(none)'}"
        )


def _sort_key(eff: EffectiveInvoice) -> str:
    return eff.parent.data.get("issue_date") or ""


async def list_entities(state: ShimState) -> dict[str, Any]:
    return {"identity": state.identity, "name": state.name, "nips": state.nips}


async def list_invoices(
    state: ShimState,
    nip: str,
    include_ignored: bool = False,
    only_unpaid: bool = False,
    since: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Headline list. `since` is an ISO date (YYYY-MM-DD); invoices with
    issue_date >= since are kept. only_unpaid drops paid rows.
    """
    _validate_nip(state, nip)
    effective = await _fetch_effective(state, nip)

    filtered: list[EffectiveInvoice] = []
    for eff in effective:
        p = eff.parent
        if not include_ignored and p.ignored:
            continue
        if only_unpaid and p.paid:
            continue
        if since and (eff.parent.data.get("issue_date") or "") < since:
            continue
        filtered.append(eff)

    filtered.sort(key=_sort_key, reverse=True)
    truncated = filtered[: max(0, limit)]
    return {
        "nip": nip,
        "total_matching": len(filtered),
        "returned": len(truncated),
        "invoices": [effective_to_summary(eff) for eff in truncated],
    }


async def get_invoice(state: ShimState, nip: str, ksef_ref: str) -> dict[str, Any]:
    _validate_nip(state, nip)
    effective = await _fetch_effective(state, nip)
    for eff in effective:
        if eff.parent.ksef_ref == ksef_ref:
            return effective_to_detail(eff)
    # Could also be a correction folded under a parent — look for it there.
    for eff in effective:
        for k in eff.corrections:
            if k.ksef_ref == ksef_ref:
                return {
                    "note": f"This is a correction folded under parent {eff.parent.ksef_ref}",
                    "parent": effective_to_detail(eff),
                }
    raise ValueError(f"invoice {ksef_ref!r} not found for NIP {nip}")


async def unpaid_summary(state: ShimState, nip: str | None = None) -> dict[str, Any]:
    """Count + total brutto (effective payment_amount) of unpaid, non-ignored,
    non-orphan-correction invoices. Returns per-NIP breakdown plus an overall total."""
    nips_to_scan = [nip] if nip else list(state.nips)
    if nip:
        _validate_nip(state, nip)

    per_nip: list[dict[str, Any]] = []
    grand_count = 0
    grand_total = 0.0
    currency_seen: set[str] = set()

    for n in nips_to_scan:
        effective = await _fetch_effective(state, n)
        count = 0
        total = 0.0
        for eff in effective:
            p = eff.parent
            if p.paid or p.ignored or eff.is_orphan_correction:
                continue
            amount_str = eff.payment_amount if eff.payment_amount is not None else eff.gross_amount
            try:
                total += float(amount_str)
            except (TypeError, ValueError):
                pass
            count += 1
            cur = p.data.get("currency")
            if cur:
                currency_seen.add(cur)
        per_nip.append({"nip": n, "unpaid_count": count, "unpaid_total": f"{total:.2f}"})
        grand_count += count
        grand_total += total

    return {
        "per_nip": per_nip,
        "total_unpaid_count": grand_count,
        "total_unpaid_amount": f"{grand_total:.2f}",
        "currencies": sorted(currency_seen),
    }
