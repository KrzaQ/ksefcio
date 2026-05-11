"""Decrypted invoice data + correction folding.

Mirrors frontend/src/stores/invoices.ts: a "correction" invoice (KOR*) is folded
into its parent, adding the signed deltas in P_13/14/15 so the parent row
reflects the effective state. Per KSeF docs, P_13/14/15 on a correction
always carry deltas — formal-only corrections (e.g. fixing a NIP or
description) just have zero deltas. Corrections whose parent isn't in the
dataset are surfaced as orphans.

The decrypted blob is JSON.stringify(InvoiceData) from the frontend, so we
just work with dicts here — no validation, full forward compatibility with
new fields the frontend might add.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any


def _parse_amount(s: Any) -> float:
    if s is None:
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _fmt_amount(v: float) -> str:
    return f"{v:.2f}"


def is_correction(invoice: dict) -> bool:
    """KOR, KOR_ZAL, KOR_ROZ — any invoice_type starting with KOR."""
    t = invoice.get("invoice_type")
    return isinstance(t, str) and t.startswith("KOR")


def _child_text(parent: ET.Element | None, local_name: str) -> str | None:
    """Return text of the first direct child with the given local name (namespace-agnostic), trimmed."""
    if parent is None:
        return None
    el = parent.find(f"{{*}}{local_name}")
    if el is None:
        return None
    text = (el.text or "").strip()
    return text or None


def enrich_from_xml(data: dict) -> dict:
    """Backfill correction-related fields from the embedded XML if they're missing in `data`.

    Older sync runs of the frontend parser left these fields unset on stale
    invoices (KFS 1/2026 is the canonical example). The raw FA(3) XML is still
    in the blob, so we re-extract on the fly here — defensive against
    legacy data and future parser regressions.

    Only fills fields that are currently None/absent. Never overwrites a value
    the frontend parser already set. Mutates and returns `data`.
    """
    xml = data.get("xml")
    if not xml:
        return data
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return data
    fa = root.find(".//{*}Fa")
    if fa is None:
        return data

    if data.get("invoice_type") is None:
        v = _child_text(fa, "RodzajFaktury")
        if v:
            data["invoice_type"] = v
    if data.get("correction_reason") is None:
        v = _child_text(fa, "PrzyczynaKorekty")
        if v:
            data["correction_reason"] = v

    dane = fa.find("{*}DaneFaKorygowanej")
    if dane is not None:
        if data.get("corrects_ksef_ref") is None:
            v = _child_text(dane, "NrKSeFFaKorygowanej")
            if v:
                data["corrects_ksef_ref"] = v
        if data.get("corrects_invoice_number") is None:
            v = _child_text(dane, "NrFaKorygowanej")
            if v:
                data["corrects_invoice_number"] = v
        if data.get("corrects_issue_date") is None:
            v = _child_text(dane, "DataWystFaKorygowanej")
            if v:
                data["corrects_issue_date"] = v

    return data


@dataclass
class DecryptedInvoice:
    """One decrypted invoice with the server-side flags merged in."""
    ksef_ref: str
    nip: str
    id: int
    paid: bool
    ignored: bool
    created_at: str
    updated_at: str
    data: dict[str, Any]  # the JSON-decoded InvoiceData

    @classmethod
    def from_row(cls, nip: str, row: dict, decoded: dict) -> "DecryptedInvoice":
        return cls(
            ksef_ref=row["ksef_ref"],
            nip=nip,
            id=row["id"],
            paid=bool(row.get("paid")),
            ignored=bool(row.get("ignored")),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            data=decoded,
        )


@dataclass
class EffectiveInvoice:
    """A non-correction invoice with its corrections folded in.

    Or, when is_orphan_correction is True, a KOR row whose parent isn't in
    the dataset — shown standalone so the user knows it exists.
    """
    parent: DecryptedInvoice
    corrections: list[DecryptedInvoice] = field(default_factory=list)
    net_amount: str = "0.00"
    vat_amount: str = "0.00"
    gross_amount: str = "0.00"
    payment_amount: str | None = None
    bank_account: str | None = None
    paid_mismatch: bool = False
    ignored_mismatch: bool = False
    is_orphan_correction: bool = False

    @property
    def has_corrections(self) -> bool:
        return bool(self.corrections)


def fold_corrections(invoices: list[DecryptedInvoice]) -> list[EffectiveInvoice]:
    corrections: list[DecryptedInvoice] = []
    non_corrections: list[DecryptedInvoice] = []
    for inv in invoices:
        (corrections if is_correction(inv.data) else non_corrections).append(inv)

    by_ref = {inv.ksef_ref: inv for inv in non_corrections}
    parent_to_kors: dict[str, list[DecryptedInvoice]] = {}
    orphans: list[DecryptedInvoice] = []

    for kor in corrections:
        parent_ref = kor.data.get("corrects_ksef_ref")
        parent = by_ref.get(parent_ref) if parent_ref else None
        if parent is not None:
            parent_to_kors.setdefault(parent.ksef_ref, []).append(kor)
        else:
            orphans.append(kor)

    for kors in parent_to_kors.values():
        kors.sort(key=lambda k: k.id)

    result: list[EffectiveInvoice] = []

    for parent in non_corrections:
        kors = parent_to_kors.get(parent.ksef_ref, [])
        if not kors:
            d = parent.data
            result.append(EffectiveInvoice(
                parent=parent,
                net_amount=str(d.get("net_amount", "0.00")),
                vat_amount=str(d.get("vat_amount", "0.00")),
                gross_amount=str(d.get("gross_amount", "0.00")),
                payment_amount=d.get("payment_amount"),
                bank_account=d.get("bank_account"),
            ))
            continue

        pd = parent.data
        net = _parse_amount(pd.get("net_amount")) + sum(_parse_amount(k.data.get("net_amount")) for k in kors)
        vat = _parse_amount(pd.get("vat_amount")) + sum(_parse_amount(k.data.get("vat_amount")) for k in kors)
        gross = _parse_amount(pd.get("gross_amount")) + sum(_parse_amount(k.data.get("gross_amount")) for k in kors)

        # Settlement: prefer explicit payment_amount; fall back to gross.
        def _payment(d: dict) -> float:
            pa = d.get("payment_amount")
            return _parse_amount(pa if pa is not None else d.get("gross_amount"))

        payment = _payment(pd) + sum(_payment(k.data) for k in kors)

        # Latest non-empty bank_account wins (matches frontend's reverse-iteration logic).
        bank_account = pd.get("bank_account")
        for k in reversed(kors):
            ba = k.data.get("bank_account")
            if ba:
                bank_account = ba
                break

        result.append(EffectiveInvoice(
            parent=parent,
            corrections=kors,
            net_amount=_fmt_amount(net),
            vat_amount=_fmt_amount(vat),
            gross_amount=_fmt_amount(gross),
            payment_amount=_fmt_amount(payment),
            bank_account=bank_account,
            paid_mismatch=any(k.paid != parent.paid for k in kors),
            ignored_mismatch=any(k.ignored != parent.ignored for k in kors),
        ))

    for orphan in orphans:
        d = orphan.data
        result.append(EffectiveInvoice(
            parent=orphan,
            net_amount=str(d.get("net_amount", "0.00")),
            vat_amount=str(d.get("vat_amount", "0.00")),
            gross_amount=str(d.get("gross_amount", "0.00")),
            payment_amount=d.get("payment_amount"),
            bank_account=d.get("bank_account"),
            is_orphan_correction=True,
        ))

    return result


def effective_to_summary(eff: EffectiveInvoice) -> dict[str, Any]:
    """Headline fields suitable for list_invoices output."""
    p = eff.parent
    d = p.data
    return {
        "nip": p.nip,
        "ksef_ref": p.ksef_ref,
        "invoice_number": d.get("invoice_number"),
        "issue_date": d.get("issue_date"),
        "due_date": d.get("due_date"),
        "seller_name": d.get("seller_name"),
        "seller_nip": d.get("seller_nip"),
        "buyer_name": d.get("buyer_name"),
        "buyer_nip": d.get("buyer_nip"),
        "currency": d.get("currency"),
        "net_amount": eff.net_amount,
        "vat_amount": eff.vat_amount,
        "gross_amount": eff.gross_amount,
        "payment_amount": eff.payment_amount,
        "bank_account": eff.bank_account,
        "invoice_type": d.get("invoice_type"),
        "paid": p.paid,
        "ignored": p.ignored,
        "has_corrections": eff.has_corrections,
        "correction_count": len(eff.corrections),
        "paid_mismatch": eff.paid_mismatch,
        "ignored_mismatch": eff.ignored_mismatch,
        "is_orphan_correction": eff.is_orphan_correction,
    }


def effective_to_detail(eff: EffectiveInvoice) -> dict[str, Any]:
    """Full payload for get_invoice — includes line items and the full correction list."""
    summary = effective_to_summary(eff)
    d = eff.parent.data
    summary.update({
        "line_items": d.get("line_items"),
        "correction_reason": d.get("correction_reason"),
        "corrects_ksef_ref": d.get("corrects_ksef_ref"),
        "corrects_invoice_number": d.get("corrects_invoice_number"),
        "corrects_issue_date": d.get("corrects_issue_date"),
        "corrections": [
            {
                "ksef_ref": k.ksef_ref,
                "invoice_number": k.data.get("invoice_number"),
                "issue_date": k.data.get("issue_date"),
                "invoice_type": k.data.get("invoice_type"),
                "correction_reason": k.data.get("correction_reason"),
                "net_amount": k.data.get("net_amount"),
                "vat_amount": k.data.get("vat_amount"),
                "gross_amount": k.data.get("gross_amount"),
                "payment_amount": k.data.get("payment_amount"),
                "paid": k.paid,
                "ignored": k.ignored,
                "line_items": k.data.get("line_items"),
            }
            for k in eff.corrections
        ],
    })
    return summary
