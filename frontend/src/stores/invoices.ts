import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch } from '../api'
import { useAuthStore } from './auth'
import { decryptBlob, base64ToArrayBuffer } from '../crypto'

export interface Invoice {
  ksef_ref: string
  ignored: boolean
  paid: boolean
  encrypted_blob: string  // base64
  created_at: string
  updated_at: string
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
  due_date?: string
  bank_account?: string
}

export interface DecryptedInvoice extends InvoiceData {
  ignored: boolean
  paid: boolean
  created_at: string
  updated_at: string
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
        const data: InvoiceData = JSON.parse(new TextDecoder().decode(plaintext))
        return {
          ...data,
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

  async function fetchInvoices() {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (showIgnored.value) params.set('include_ignored', 'true')
      const qs = params.toString()
      const res = await apiFetch(qs ? `/api/invoices?${qs}` : '/api/invoices')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      invoices.value = await res.json()
      await decryptAll()
    } finally {
      loading.value = false
    }
  }

  async function updateFlags(ksefRef: string, flags: { ignored?: boolean; paid?: boolean }) {
    // Optimistic update
    const idx = decryptedInvoices.value.findIndex(i => i.ksef_ref === ksefRef)
    const prev = idx >= 0 ? { ...decryptedInvoices.value[idx] } : null
    if (idx >= 0) {
      if (flags.ignored !== undefined) decryptedInvoices.value[idx].ignored = flags.ignored
      if (flags.paid !== undefined) decryptedInvoices.value[idx].paid = flags.paid
    }

    try {
      const res = await apiFetch(`/api/invoices/${encodeURIComponent(ksefRef)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(flags),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      // Sync raw invoices array
      const rawIdx = invoices.value.findIndex(i => i.ksef_ref === ksefRef)
      if (rawIdx >= 0) {
        if (flags.ignored !== undefined) invoices.value[rawIdx].ignored = flags.ignored
        if (flags.paid !== undefined) invoices.value[rawIdx].paid = flags.paid
      }
    } catch (e) {
      // Revert on failure
      if (idx >= 0 && prev) {
        decryptedInvoices.value[idx] = prev as DecryptedInvoice
      }
      throw e
    }
  }

  return {
    invoices, decryptedInvoices, decryptError,
    showIgnored, showPaid, loading,
    fetchInvoices, updateFlags,
  }
})
