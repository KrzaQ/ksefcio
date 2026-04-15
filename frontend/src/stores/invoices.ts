import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiFetch } from '../api'
import { useAuthStore } from './auth'
import { decryptBlob, encryptBlob, arrayBufferToBase64, base64ToArrayBuffer } from '../crypto'
import { authenticateKsef, queryKsefInvoices, downloadKsefInvoice } from '../ksef'
import { parseInvoiceXml } from '../invoiceParser'

export interface Invoice {
  id: number
  ksef_ref: string
  ignored: boolean
  paid: boolean
  encrypted_blob: string  // base64
  created_at: string
  updated_at: string
}

export interface LineItem {
  description: string
  unit?: string
  quantity?: string
  unit_price?: string
  net_amount: string
  vat_rate?: string
}

export interface InvoiceData {
  ksef_ref: string
  invoice_number: string
  seller_name: string
  seller_nip: string
  buyer_name: string
  buyer_nip: string
  issue_date: string
  net_amount: string
  vat_amount: string
  gross_amount: string
  currency: string
  payment_amount?: string
  due_date?: string
  bank_account?: string
  line_items?: LineItem[]
  invoice_type?: string              // 'VAT' | 'KOR' | 'KOR_ZAL' | 'KOR_ROZ' | 'ZAL' | 'ROZ' | 'UPR'
  corrects_ksef_ref?: string
  corrects_invoice_number?: string
  corrects_issue_date?: string
  correction_reason?: string
  xml?: string  // full FA XML from KSeF
}

export interface DecryptedInvoice extends InvoiceData {
  id: number
  ignored: boolean
  paid: boolean
  created_at: string
  updated_at: string
}

export interface EffectiveInvoice extends DecryptedInvoice {
  corrections: DecryptedInvoice[]
  has_corrections: boolean
  paid_mismatch: boolean
  ignored_mismatch: boolean
  is_orphan_correction: boolean
}

export const useInvoicesStore = defineStore('invoices', () => {
  const invoices = ref<Invoice[]>([])
  const decryptedInvoices = ref<DecryptedInvoice[]>([])
  const decryptError = ref<string | null>(null)
  const showIgnored = ref(false)
  const showPaid = ref(true)
  const loading = ref(false)

  async function decryptAll() {
    const auth = useAuthStore()
    if (!auth.aesKey) {
      decryptError.value = 'Brak klucza szyfrującego — zaloguj się ponownie'
      decryptedInvoices.value = []
      return
    }

    const results = await Promise.allSettled(
      invoices.value.map(async (inv): Promise<DecryptedInvoice> => {
        const encrypted = base64ToArrayBuffer(inv.encrypted_blob)
        const plaintext = await decryptBlob(auth.aesKey!, encrypted)
        const stored: InvoiceData = JSON.parse(new TextDecoder().decode(plaintext))
        if (stored.xml && (
          !stored.bank_account
          || stored.payment_amount === undefined
          || stored.invoice_type === undefined
        )) {
          const reparsed = parseInvoiceXml(stored.xml, inv.ksef_ref)
          if (!stored.bank_account) stored.bank_account = reparsed.bank_account
          if (stored.payment_amount === undefined) stored.payment_amount = reparsed.payment_amount
          if (stored.invoice_type === undefined) {
            stored.invoice_type = reparsed.invoice_type
            stored.corrects_ksef_ref = reparsed.corrects_ksef_ref
            stored.corrects_invoice_number = reparsed.corrects_invoice_number
            stored.corrects_issue_date = reparsed.corrects_issue_date
            stored.correction_reason = reparsed.correction_reason
          }
        }
        const { xml: _xml, ...data } = stored
        return {
          ...data,
          id: inv.id,
          ignored: inv.ignored,
          paid: inv.paid,
          created_at: inv.created_at,
          updated_at: inv.updated_at,
        }
      }),
    )

    const ok: DecryptedInvoice[] = []
    let failed = 0
    for (const r of results) {
      if (r.status === 'fulfilled') ok.push(r.value)
      else failed++
    }

    decryptedInvoices.value = ok
    decryptError.value = failed > 0
      ? `Nie udało się odszyfrować ${failed} faktur(y)`
      : null
  }

  const effectiveInvoices = computed<EffectiveInvoice[]>(() => {
    const all = decryptedInvoices.value
    const corrections: DecryptedInvoice[] = []
    const nonCorrections: DecryptedInvoice[] = []
    for (const inv of all) {
      if (inv.invoice_type?.startsWith('KOR')) corrections.push(inv)
      else nonCorrections.push(inv)
    }

    const byRef = new Map<string, DecryptedInvoice>()
    for (const inv of nonCorrections) byRef.set(inv.ksef_ref, inv)

    const parentToCorrections = new Map<string, DecryptedInvoice[]>()
    const orphans: DecryptedInvoice[] = []
    for (const kor of corrections) {
      const parent = kor.corrects_ksef_ref ? byRef.get(kor.corrects_ksef_ref) : undefined
      if (parent) {
        const list = parentToCorrections.get(parent.ksef_ref) ?? []
        list.push(kor)
        parentToCorrections.set(parent.ksef_ref, list)
      } else {
        orphans.push(kor)
      }
    }
    for (const list of parentToCorrections.values()) list.sort((a, b) => a.id - b.id)

    const result: EffectiveInvoice[] = []

    for (const parent of nonCorrections) {
      const kors = parentToCorrections.get(parent.ksef_ref) ?? []
      if (kors.length === 0) {
        result.push({
          ...parent,
          corrections: [],
          has_corrections: false,
          paid_mismatch: false,
          ignored_mismatch: false,
          is_orphan_correction: false,
        })
        continue
      }

      const parsed = (s?: string) => {
        const n = parseFloat(s ?? '')
        return isNaN(n) ? 0 : n
      }
      const net = parsed(parent.net_amount) + kors.reduce((s, k) => s + parsed(k.net_amount), 0)
      const vat = parsed(parent.vat_amount) + kors.reduce((s, k) => s + parsed(k.vat_amount), 0)
      const gross = parsed(parent.gross_amount) + kors.reduce((s, k) => s + parsed(k.gross_amount), 0)
      const paymentBase = parent.payment_amount !== undefined ? parsed(parent.payment_amount) : parsed(parent.gross_amount)
      const paymentDelta = kors.reduce((s, k) => s + (k.payment_amount !== undefined ? parsed(k.payment_amount) : parsed(k.gross_amount)), 0)
      const payment = paymentBase + paymentDelta

      let bankAccount = parent.bank_account
      for (let i = kors.length - 1; i >= 0; i--) {
        if (kors[i]!.bank_account) { bankAccount = kors[i]!.bank_account; break }
      }

      result.push({
        ...parent,
        net_amount: net.toFixed(2),
        vat_amount: vat.toFixed(2),
        gross_amount: gross.toFixed(2),
        payment_amount: payment.toFixed(2),
        bank_account: bankAccount,
        corrections: kors,
        has_corrections: true,
        paid_mismatch: kors.some(k => k.paid !== parent.paid),
        ignored_mismatch: kors.some(k => k.ignored !== parent.ignored),
        is_orphan_correction: false,
      })
    }

    for (const orphan of orphans) {
      result.push({
        ...orphan,
        corrections: [],
        has_corrections: false,
        paid_mismatch: false,
        ignored_mismatch: false,
        is_orphan_correction: true,
      })
    }

    return result
  })

  function expandWithCorrections(ksefRefs: string[]): string[] {
    const expanded = new Set<string>()
    for (const ref of ksefRefs) {
      expanded.add(ref)
      const eff = effectiveInvoices.value.find(i => i.ksef_ref === ref)
      if (eff) {
        for (const c of eff.corrections) expanded.add(c.ksef_ref)
      }
    }
    return [...expanded]
  }

  async function fetchInvoices() {
    const auth = useAuthStore()
    if (!auth.activeNip) {
      invoices.value = []
      decryptedInvoices.value = []
      return
    }
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (showIgnored.value) params.set('include_ignored', 'true')
      const qs = params.toString()
      const base = `/api/invoices/${auth.activeNip}`
      const res = await apiFetch(qs ? `${base}?${qs}` : base)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      invoices.value = await res.json()
      await decryptAll()
    } finally {
      loading.value = false
    }
  }

  async function updateFlags(ksefRef: string, flags: { ignored?: boolean; paid?: boolean }) {
    return bulkUpdateFlags([ksefRef], flags)
  }

  async function bulkUpdateFlags(ksefRefs: string[], flags: { ignored?: boolean; paid?: boolean }) {
    const snapshots = new Map<string, DecryptedInvoice>()
    for (const ref of ksefRefs) {
      const idx = decryptedInvoices.value.findIndex(i => i.ksef_ref === ref)
      if (idx >= 0) {
        const inv = decryptedInvoices.value[idx]!
        snapshots.set(ref, { ...inv })
        if (flags.ignored !== undefined) inv.ignored = flags.ignored
        if (flags.paid !== undefined) inv.paid = flags.paid
      }
    }

    try {
      const auth = useAuthStore()
      await Promise.all(ksefRefs.map(ref =>
        apiFetch(`/api/invoices/${auth.activeNip}/${encodeURIComponent(ref)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(flags),
        }).then(res => {
          if (!res.ok) throw new Error(`HTTP ${res.status} for ${ref}`)
        })
      ))
      for (const ref of ksefRefs) {
        const rawIdx = invoices.value.findIndex(i => i.ksef_ref === ref)
        if (rawIdx >= 0) {
          const raw = invoices.value[rawIdx]!
          if (flags.ignored !== undefined) raw.ignored = flags.ignored
          if (flags.paid !== undefined) raw.paid = flags.paid
        }
      }
    } catch (e) {
      for (const [ref, snapshot] of snapshots) {
        const idx = decryptedInvoices.value.findIndex(i => i.ksef_ref === ref)
        if (idx >= 0) decryptedInvoices.value[idx] = snapshot
      }
      throw e
    }
  }

  const syncProgress = ref('')

  async function syncFromKsef(accessToken: string): Promise<number> {
    const auth = useAuthStore()
    if (!auth.activeNip || !auth.aesKey) throw new Error('No active NIP or AES key')

    // Fetch raw invoice list (without decrypting) to know which refs we already have
    const params = new URLSearchParams()
    if (showIgnored.value) params.set('include_ignored', 'true')
    const qs = params.toString()
    const base = `/api/invoices/${auth.activeNip}`
    const existingRes = await apiFetch(qs ? `${base}?${qs}` : base)
    const existingList: Invoice[] = existingRes.ok ? await existingRes.json() : []
    const existingRefs = new Set(existingList.map(i => i.ksef_ref))

    // Query KSeF for invoices in the last 12 months (API allows max 3 months per query)
    const now = new Date()
    const yearAgo = new Date(now)
    yearAgo.setFullYear(yearAgo.getFullYear() - 1)

    syncProgress.value = 'Pobieranie listy faktur z KSeF...'
    const headers = await queryKsefInvoices(accessToken, yearAgo, now)

    const newHeaders = headers.filter(h => !existingRefs.has(h.ksefNumber))
    if (newHeaders.length === 0) {
      syncProgress.value = ''
      return 0
    }

    let synced = 0
    for (const header of newHeaders) {
      // KSeF rate limit: 16 requests/minute for invoice downloads
      if (synced > 0) await new Promise(r => setTimeout(r, 5000))
      synced++
      syncProgress.value = `Pobieranie faktury ${synced}/${newHeaders.length}...`

      const xml = await downloadKsefInvoice(header.ksefNumber, accessToken)
      const data = parseInvoiceXml(xml, header.ksefNumber)
      data.xml = xml

      // Fill in amounts from metadata if XML parsing missed them
      if (data.gross_amount === '0.00' && header.grossAmount) {
        data.gross_amount = header.grossAmount.toFixed(2)
        data.net_amount = header.netAmount.toFixed(2)
        data.vat_amount = header.vatAmount.toFixed(2)
      }
      if (!data.seller_name && header.seller?.name) data.seller_name = header.seller.name
      if (!data.seller_nip && header.seller?.nip) data.seller_nip = header.seller.nip
      if (!data.currency) data.currency = header.currency

      const plaintext = new TextEncoder().encode(JSON.stringify(data))
      const encrypted = await encryptBlob(auth.aesKey!, plaintext.buffer as ArrayBuffer)
      const blob = arrayBufferToBase64(encrypted)

      await apiFetch(
        `/api/invoices/${auth.activeNip}/${encodeURIComponent(header.ksefNumber)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ encrypted_blob: blob }),
        },
      )
    }

    syncProgress.value = ''
    await fetchInvoices()
    return newHeaders.length
  }

  async function redownloadInvoice(ksefRef: string): Promise<void> {
    await redownloadInvoices([ksefRef])
  }

  async function redownloadInvoices(ksefRefs: string[]): Promise<void> {
    const auth = useAuthStore()
    if (!auth.activeNip || !auth.aesKey) {
      throw new Error('Brak aktywnego NIP lub klucza szyfrującego')
    }

    if (!auth.ksefAccessToken) {
      const tokens = await authenticateKsef(auth.activeNip)
      auth.ksefAccessToken = tokens.accessToken
    }

    for (const ksefRef of ksefRefs) {
      const xml = await downloadKsefInvoice(ksefRef, auth.ksefAccessToken!)
      const data = parseInvoiceXml(xml, ksefRef)
      data.xml = xml

      const plaintext = new TextEncoder().encode(JSON.stringify(data))
      const encrypted = await encryptBlob(auth.aesKey, plaintext.buffer as ArrayBuffer)
      const blob = arrayBufferToBase64(encrypted)

      const res = await apiFetch(
        `/api/invoices/${auth.activeNip}/${encodeURIComponent(ksefRef)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ encrypted_blob: blob }),
        },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    }

    await fetchInvoices()
  }

  /** Parse line items on demand from stored XML. Mutates the decrypted invoice in place. */
  async function ensureLineItems(ksefRef: string) {
    const dec = decryptedInvoices.value.find(i => i.ksef_ref === ksefRef)
    if (!dec || dec.line_items) return

    const auth = useAuthStore()
    if (!auth.aesKey) return

    const inv = invoices.value.find(i => i.ksef_ref === ksefRef)
    if (!inv) return

    const encrypted = base64ToArrayBuffer(inv.encrypted_blob)
    const stored: InvoiceData = JSON.parse(new TextDecoder().decode(await decryptBlob(auth.aesKey, encrypted)))
    if (!stored.xml) return

    const parsed = parseInvoiceXml(stored.xml, ksefRef)
    dec.line_items = parsed.line_items
  }

  async function getInvoiceXml(ksefRef: string): Promise<string | null> {
    const auth = useAuthStore()
    if (!auth.aesKey) return null
    const inv = invoices.value.find(i => i.ksef_ref === ksefRef)
    if (!inv) return null
    const encrypted = base64ToArrayBuffer(inv.encrypted_blob)
    const stored: InvoiceData = JSON.parse(new TextDecoder().decode(await decryptBlob(auth.aesKey, encrypted)))
    return stored.xml ?? null
  }

  return {
    invoices, decryptedInvoices, effectiveInvoices, decryptError,
    showIgnored, showPaid, loading, syncProgress,
    fetchInvoices, updateFlags, bulkUpdateFlags, expandWithCorrections,
    syncFromKsef, redownloadInvoice, redownloadInvoices, ensureLineItems, getInvoiceXml,
  }
})
