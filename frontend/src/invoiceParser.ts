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

  // Invoice header (Fa)
  const fa = find(doc, 'Fa')
  const invoiceNumber = fa ? text(fa, 'P_1') : ''
  const issueDate = fa ? text(fa, 'P_2') : ''
  const currency = fa ? (text(fa, 'KodWaluty') || 'PLN') : 'PLN'
  const grossAmountRaw = fa ? text(fa, 'P_15') : ''

  // Net and VAT totals — sum P_13_* and P_14_* across all VAT rates (1..11)
  let netTotal = 0
  let vatTotal = 0
  if (fa) {
    for (let i = 1; i <= 11; i++) {
      const net = parseFloat(text(fa, `P_13_${i}`))
      const vat = parseFloat(text(fa, `P_14_${i}`))
      if (!isNaN(net)) netTotal += net
      if (!isNaN(vat)) vatTotal += vat
    }
  }

  // Payment info (Fa > Platnosc)
  const platnosc = fa ? find(fa, 'Platnosc') : null
  let dueDate: string | undefined
  let bankAccount: string | undefined
  if (platnosc) {
    dueDate = text(platnosc, 'TerminPlatnosci') || undefined
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
