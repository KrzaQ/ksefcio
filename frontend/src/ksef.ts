import { apiFetch } from './api'
import { useAuthStore } from './stores/auth'
import { signDigest, base64ToArrayBuffer } from './crypto'

export interface KsefInvoiceHeader {
  ksefNumber: string
  invoiceNumber: string
  issueDate: string
  seller: { nip: string; name?: string }
  buyer: { name?: string }
  netAmount: number
  grossAmount: number
  vatAmount: number
  currency: string
}

/** Split a date range into chunks of at most 3 months (KSeF API limit). */
function* threeMonthChunks(from: Date, to: Date): Generator<[string, string]> {
  let cursor = new Date(from)
  while (cursor < to) {
    const chunkEnd = new Date(cursor)
    chunkEnd.setMonth(chunkEnd.getMonth() + 3)
    if (chunkEnd > to) chunkEnd.setTime(to.getTime())
    yield [cursor.toISOString(), chunkEnd.toISOString()]
    cursor = new Date(chunkEnd)
  }
}

export async function queryKsefInvoices(
  accessToken: string,
  dateFrom: Date,
  dateTo: Date,
): Promise<KsefInvoiceHeader[]> {
  const allInvoices: KsefInvoiceHeader[] = []
  const pageSize = 250

  for (const [chunkFrom, chunkTo] of threeMonthChunks(dateFrom, dateTo)) {
    let pageOffset = 0

    while (true) {
      const res = await apiFetch(
        `/api/ksef/invoices/query/metadata?pageSize=${pageSize}&pageOffset=${pageOffset}&sortOrder=Desc`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${accessToken}`,
          },
          body: JSON.stringify({
            subjectType: 'Subject2',
            dateRange: {
              dateType: 'Invoicing',
              from: chunkFrom,
              to: chunkTo,
            },
          }),
        },
      )
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`KSeF query failed: HTTP ${res.status} — ${text}`)
      }

      const data = await res.json()
      console.log('[ksef] Query metadata response:', JSON.stringify(data).slice(0, 500))

      const items: any[] = data.invoices ?? []
      for (const item of items) {
        allInvoices.push({
          ksefNumber: item.ksefNumber,
          invoiceNumber: item.invoiceNumber,
          issueDate: item.issueDate,
          seller: item.seller,
          buyer: item.buyer,
          netAmount: item.netAmount,
          grossAmount: item.grossAmount,
          vatAmount: item.vatAmount,
          currency: item.currency,
        })
      }

      if (!data.hasMore) break
      pageOffset++
    }
  }

  console.log(`[ksef] Found ${allInvoices.length} invoices`)
  return allInvoices
}

export async function downloadKsefInvoice(
  ksefRef: string,
  accessToken: string,
): Promise<string> {
  const res = await apiFetch(`/api/ksef/invoices/ksef/${ksefRef}`, {
    headers: {
      'Accept': 'application/xml',
      'Authorization': `Bearer ${accessToken}`,
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`KSeF download failed for ${ksefRef}: HTTP ${res.status} — ${text}`)
  }
  return res.text()
}

export async function authenticateKsef(nip: string): Promise<{ accessToken: string; refreshToken: string }> {
  const auth = useAuthStore()
  if (!auth.signingKey) throw new Error('Not authenticated')

  // 1. Prepare: backend gets challenge from KSeF, builds XAdES envelope
  console.log('[ksef] Preparing auth for NIP', nip)
  const prepareRes = await apiFetch('/api/ksef/auth/prepare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nip }),
  })
  if (!prepareRes.ok) {
    const body = await prepareRes.text()
    throw new Error(`KSeF prepare failed: HTTP ${prepareRes.status} — ${body}`)
  }

  const { request_id, signed_info_b64 } = await prepareRes.json()
  console.log('[ksef] Got SignedInfo to sign, request_id:', request_id)

  // 2. Sign the canonical SignedInfo bytes with the private key
  const signatureValue = await signDigest(auth.signingKey, base64ToArrayBuffer(signed_info_b64))
  console.log('[ksef] Signed, submitting to KSeF...')

  // 3. Finalize: backend inserts signature, submits to KSeF, redeems tokens
  const finalizeRes = await apiFetch('/api/ksef/auth/finalize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id, signature_value_b64: signatureValue }),
  })
  if (!finalizeRes.ok) {
    const body = await finalizeRes.text()
    throw new Error(`KSeF finalize failed: HTTP ${finalizeRes.status} — ${body}`)
  }

  const tokens = await finalizeRes.json()
  console.log('[ksef] Auth complete, got access token')
  return { accessToken: tokens.access_token, refreshToken: tokens.refresh_token }
}
