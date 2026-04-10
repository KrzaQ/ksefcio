import type { InvoiceData } from './stores/invoices'

/** Parse FA(2) or FA(3) invoice XML into InvoiceData. */
export function parseInvoiceXml(xml: string, ksefRef: string): InvoiceData {
  const doc = new DOMParser().parseFromString(xml, 'application/xml')

  const parseError = doc.querySelector('parsererror')
  if (parseError) {
    throw new Error(`Invalid invoice XML for ${ksefRef}: ${parseError.textContent}`)
  }

  // Namespace-agnostic element lookup: getElementsByTagNameNS('*', localName)
  function find(parent: Element | Document, tagName: string): Element | null {
    return parent.getElementsByTagNameNS('*', tagName)[0] ?? null
  }

  function text(parent: Element | Document, tagName: string): string {
    return find(parent, tagName)?.textContent?.trim() ?? ''
  }

  /** Get text of a direct child element only (no deep search). */
  function childText(parent: Element, tagName: string): string {
    for (const child of parent.children) {
      if (child.localName === tagName) return child.textContent?.trim() ?? ''
    }
    return ''
  }

  // Detect FA variant: 2 or 3 (field mapping differs)
  const variant = parseInt(text(doc, 'WariantFormularza')) || 2

  // Seller (Podmiot1)
  const podmiot1 = find(doc, 'Podmiot1')
  let sellerNip = ''
  let sellerName = ''
  if (podmiot1) {
    sellerNip = text(podmiot1, 'NIP')
    sellerName = text(podmiot1, 'Nazwa')
      || `${text(podmiot1, 'ImiePierwsze')} ${text(podmiot1, 'Nazwisko')}`.trim()
  }

  // Buyer (Podmiot2)
  const podmiot2 = find(doc, 'Podmiot2')
  let buyerNip = ''
  let buyerName = ''
  if (podmiot2) {
    buyerNip = text(podmiot2, 'NIP')
    buyerName = text(podmiot2, 'Nazwa')
      || `${text(podmiot2, 'ImiePierwsze')} ${text(podmiot2, 'Nazwisko')}`.trim()
  }

  // Invoice header (Fa) — use childText to avoid hitting FaWiersz fields
  const fa = find(doc, 'Fa')
  let invoiceNumber: string
  let issueDate: string
  if (variant >= 3) {
    // FA(3): P_1 = issue date, P_2 = invoice number
    issueDate = fa ? childText(fa, 'P_1') : ''
    invoiceNumber = fa ? childText(fa, 'P_2') : ''
  } else {
    // FA(2): P_1 = invoice number, P_2 = issue date
    invoiceNumber = fa ? childText(fa, 'P_1') : ''
    issueDate = fa ? childText(fa, 'P_2') : ''
  }
  const currency = fa ? childText(fa, 'KodWaluty') || 'PLN' : 'PLN'
  const grossAmountRaw = fa ? childText(fa, 'P_15') : ''

  // Net and VAT totals — sum P_13_* and P_14_* across all VAT rates
  let netTotal = 0
  let vatTotal = 0
  if (fa) {
    // FA(3) uses P_13_6_1..P_13_6_3 + P_13_7..P_13_11; FA(2) uses P_13_1..P_13_11
    const netFields = ['P_13_1', 'P_13_2', 'P_13_3', 'P_13_4', 'P_13_5',
      'P_13_6', 'P_13_6_1', 'P_13_6_2', 'P_13_6_3',
      'P_13_7', 'P_13_8', 'P_13_9', 'P_13_10', 'P_13_11']
    const vatFields = ['P_14_1', 'P_14_2', 'P_14_3', 'P_14_4', 'P_14_5',
      'P_14_6', 'P_14_6_1', 'P_14_6_2', 'P_14_6_3',
      'P_14_7', 'P_14_8', 'P_14_9', 'P_14_10', 'P_14_11']
    for (const f of netFields) {
      const v = parseFloat(childText(fa, f))
      if (!isNaN(v)) netTotal += v
    }
    for (const f of vatFields) {
      const v = parseFloat(childText(fa, f))
      if (!isNaN(v)) vatTotal += v
    }
  }

  // Payment info (Fa > Platnosc)
  const platnosc = fa ? find(fa, 'Platnosc') : null
  let dueDate: string | undefined
  let bankAccount: string | undefined
  if (platnosc) {
    // FA(3): TerminPlatnosci is a complex element with Termin child
    // FA(2): TerminPlatnosci is a simple text element
    const terminEl = find(platnosc, 'TerminPlatnosci')
    if (terminEl) {
      const termin = childText(terminEl, 'Termin')
      dueDate = (termin || terminEl.textContent?.trim() || undefined) as string | undefined
      // Guard against textContent pulling in child element text
      if (dueDate && dueDate.length > 10) dueDate = termin || undefined
    }
    bankAccount = text(platnosc, 'NrRB') || undefined
  }

  const grossAmount = grossAmountRaw || (netTotal + vatTotal).toFixed(2)

  return {
    ksef_ref: ksefRef,
    invoice_number: invoiceNumber,
    seller_name: sellerName,
    seller_nip: sellerNip,
    buyer_name: buyerName,
    buyer_nip: buyerNip,
    issue_date: issueDate,
    net_amount: netTotal.toFixed(2),
    vat_amount: vatTotal.toFixed(2),
    gross_amount: grossAmount,
    currency,
    due_date: dueDate,
    bank_account: bankAccount,
  }
}
