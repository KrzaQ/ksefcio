"""Tests for correction folding. Mirrors frontend/src/stores/invoices.ts:130."""
from ksefcio_client.invoice import (
    DecryptedInvoice,
    enrich_from_xml,
    fold_corrections,
    is_correction,
)


def _kor_xml(
    *,
    rodzaj: str = "KOR",
    przyczyna: str = "Zwrot towaru",
    corrects_ksef: str | None = "PARENT-REF",
    corrects_nr: str | None = "Faktura VAT: 1/01/2026",
    corrects_date: str | None = "2026-01-15",
    namespaced: bool = False,
) -> str:
    ns = ' xmlns="urn:x"' if namespaced else ""
    dane = ""
    if corrects_ksef or corrects_nr or corrects_date:
        parts = []
        if corrects_date:
            parts.append(f"<DataWystFaKorygowanej>{corrects_date}</DataWystFaKorygowanej>")
        if corrects_nr:
            parts.append(f"<NrFaKorygowanej>{corrects_nr}</NrFaKorygowanej>")
        if corrects_ksef:
            parts.append(f"<NrKSeFFaKorygowanej>{corrects_ksef}</NrKSeFFaKorygowanej>")
        dane = f"<DaneFaKorygowanej>{''.join(parts)}</DaneFaKorygowanej>"
    return (
        f'<Faktura{ns}><Fa>'
        f"<RodzajFaktury>{rodzaj}</RodzajFaktury>"
        f"<PrzyczynaKorekty>{przyczyna}</PrzyczynaKorekty>"
        f"{dane}"
        f"</Fa></Faktura>"
    )


def _inv(
    ksef_ref: str,
    *,
    paid: bool = False,
    ignored: bool = False,
    invoice_type: str = "VAT",
    corrects_ksef_ref: str | None = None,
    net: str = "100.00",
    vat: str = "23.00",
    gross: str = "123.00",
    payment: str | None = None,
    bank_account: str | None = None,
    id: int = 1,
) -> DecryptedInvoice:
    data: dict = {
        "ksef_ref": ksef_ref,
        "invoice_number": f"FV-{ksef_ref}",
        "issue_date": "2026-04-01",
        "net_amount": net,
        "vat_amount": vat,
        "gross_amount": gross,
        "currency": "PLN",
        "invoice_type": invoice_type,
    }
    if corrects_ksef_ref:
        data["corrects_ksef_ref"] = corrects_ksef_ref
    if payment is not None:
        data["payment_amount"] = payment
    if bank_account is not None:
        data["bank_account"] = bank_account
    return DecryptedInvoice(
        ksef_ref=ksef_ref, nip="1234567890", id=id,
        paid=paid, ignored=ignored,
        created_at="", updated_at="", data=data,
    )


def test_is_correction_detects_kor_variants():
    assert is_correction({"invoice_type": "KOR"})
    assert is_correction({"invoice_type": "KOR_ZAL"})
    assert is_correction({"invoice_type": "KOR_ROZ"})
    assert not is_correction({"invoice_type": "VAT"})
    assert not is_correction({})


def test_fold_no_corrections_passthrough():
    invs = [_inv("A"), _inv("B")]
    result = fold_corrections(invs)
    assert len(result) == 2
    assert all(not e.has_corrections for e in result)
    assert all(not e.is_orphan_correction for e in result)
    assert result[0].gross_amount == "123.00"


def test_fold_sums_amounts_and_marks_has_corrections():
    parent = _inv("A", net="100.00", vat="23.00", gross="123.00", id=1)
    kor = _inv("A-kor1", invoice_type="KOR", corrects_ksef_ref="A",
               net="-10.00", vat="-2.30", gross="-12.30", id=2)
    result = fold_corrections([parent, kor])
    assert len(result) == 1
    eff = result[0]
    assert eff.has_corrections
    assert eff.net_amount == "90.00"
    assert eff.vat_amount == "20.70"
    assert eff.gross_amount == "110.70"
    assert len(eff.corrections) == 1


def test_fold_payment_amount_prefers_explicit_then_falls_back_to_gross():
    parent = _inv("A", gross="100.00", payment="80.00", id=1)
    kor = _inv("A-kor", invoice_type="KOR", corrects_ksef_ref="A",
               gross="-50.00", id=2)  # no payment_amount → falls back to gross delta
    result = fold_corrections([parent, kor])
    assert result[0].payment_amount == "30.00"  # 80 + (-50)


def test_fold_latest_nonempty_bank_account_wins():
    parent = _inv("A", bank_account="PARENT-ACC", id=1)
    kor1 = _inv("A-k1", invoice_type="KOR", corrects_ksef_ref="A",
                bank_account="K1-ACC", id=2)
    kor2 = _inv("A-k2", invoice_type="KOR", corrects_ksef_ref="A",
                bank_account=None, id=3)
    result = fold_corrections([parent, kor1, kor2])
    # kor2 is later but has no bank_account → fall back to kor1.
    assert result[0].bank_account == "K1-ACC"


def test_fold_paid_mismatch_surfaces():
    parent = _inv("A", paid=False, id=1)
    kor = _inv("A-kor", invoice_type="KOR", corrects_ksef_ref="A", paid=True, id=2)
    result = fold_corrections([parent, kor])
    assert result[0].paid_mismatch is True
    assert result[0].ignored_mismatch is False


def test_fold_orphan_correction_surfaced():
    orphan = _inv("orphan", invoice_type="KOR", corrects_ksef_ref="missing-parent", id=1)
    result = fold_corrections([orphan])
    assert len(result) == 1
    assert result[0].is_orphan_correction is True
    assert result[0].parent.ksef_ref == "orphan"


def test_enrich_fills_missing_correction_fields_from_xml():
    """Mirrors the real-world KFS 1/2026 case: stored JSON has all correction
    fields as None, but the embedded XML clearly says <RodzajFaktury>KOR</...>
    plus the parent in <DaneFaKorygowanej>."""
    data = {"xml": _kor_xml(corrects_ksef="PARENT-REF",
                              corrects_nr="Faktura VAT: 2/04/2026",
                              corrects_date="2026-04-15")}
    enrich_from_xml(data)
    assert data["invoice_type"] == "KOR"
    assert data["correction_reason"] == "Zwrot towaru"
    assert data["corrects_ksef_ref"] == "PARENT-REF"
    assert data["corrects_invoice_number"] == "Faktura VAT: 2/04/2026"
    assert data["corrects_issue_date"] == "2026-04-15"


def test_enrich_does_not_overwrite_existing_fields():
    data = {
        "invoice_type": "VAT",  # frontend got it right, leave it alone
        "corrects_ksef_ref": None,  # missing — should be filled
        "xml": _kor_xml(corrects_ksef="PARENT-REF"),
    }
    enrich_from_xml(data)
    assert data["invoice_type"] == "VAT"  # untouched
    assert data["corrects_ksef_ref"] == "PARENT-REF"  # filled


def test_enrich_handles_namespaced_xml():
    data = {"xml": _kor_xml(namespaced=True)}
    enrich_from_xml(data)
    assert data["invoice_type"] == "KOR"
    assert data["corrects_ksef_ref"] == "PARENT-REF"


def test_enrich_handles_missing_or_broken_xml():
    assert enrich_from_xml({})  == {}
    assert enrich_from_xml({"xml": ""}) == {"xml": ""}
    assert enrich_from_xml({"xml": "<broken"}) == {"xml": "<broken"}
    # Well-formed but no Fa element — no fields filled
    data = {"xml": "<Faktura><Naglowek/></Faktura>"}
    enrich_from_xml(data)
    assert "invoice_type" not in data


def test_enrich_then_fold_recovers_zero_delta_correction():
    """Integration: enrichment should make a stale KOR foldable into its parent."""
    parent = _inv("PARENT", net="100.00", vat="23.00", gross="123.00", id=1)
    # Simulate the KFS 1/2026 case: all correction fields are missing from JSON
    # but the XML carries them.
    kor = DecryptedInvoice(
        ksef_ref="STALE-KOR", nip="1234567890", id=2,
        paid=False, ignored=False, created_at="", updated_at="",
        data={
            "net_amount": "0.00", "vat_amount": "0.00", "gross_amount": "0",
            "xml": _kor_xml(corrects_ksef="PARENT"),
        },
    )
    enrich_from_xml(kor.data)
    result = fold_corrections([parent, kor])
    assert len(result) == 1  # KOR was folded, not surfaced as a standalone row
    eff = result[0]
    assert eff.has_corrections
    assert eff.gross_amount == "123.00"  # zero-delta: parent unchanged


def test_fold_zero_delta_correction_leaves_parent_amount():
    """Per KSeF docs, P_13/14/15 on a correction are always deltas. A formal-only
    correction (e.g. fixing a NIP, line description) has zero deltas, so the
    parent's effective amount stays unchanged."""
    parent = _inv("A", net="100.00", vat="23.00", gross="123.00", id=1)
    kor = _inv("A-kor", invoice_type="KOR", corrects_ksef_ref="A",
               net="0.00", vat="0.00", gross="0", id=2)
    result = fold_corrections([parent, kor])
    eff = result[0]
    assert eff.has_corrections
    assert eff.gross_amount == "123.00"
    assert eff.net_amount == "100.00"
    assert eff.vat_amount == "23.00"


def test_fold_multiple_corrections_summed_and_sorted_by_id():
    parent = _inv("A", net="100.00", gross="100.00", id=10)
    kor_a = _inv("A-k1", invoice_type="KOR", corrects_ksef_ref="A",
                 net="-5.00", gross="-5.00", id=20)
    kor_b = _inv("A-k2", invoice_type="KOR", corrects_ksef_ref="A",
                 net="-3.00", gross="-3.00", id=15)
    # Pass them out of order; folding should sort by id.
    result = fold_corrections([parent, kor_a, kor_b])
    eff = result[0]
    assert eff.gross_amount == "92.00"
    assert [k.id for k in eff.corrections] == [15, 20]
