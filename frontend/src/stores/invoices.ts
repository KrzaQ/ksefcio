import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Invoice {
  ksef_ref: string
  ignored: boolean
  paid: boolean
  encrypted_blob: string  // base64
  created_at: string
  updated_at: string
}

export const useInvoicesStore = defineStore('invoices', () => {
  const invoices = ref<Invoice[]>([])
  const showIgnored = ref(false)
  const showPaid = ref(true)
  const loading = ref(false)

  async function fetchInvoices(token: string) {
    loading.value = true
    try {
      const params = new URLSearchParams()
      if (showIgnored.value) params.set('include_ignored', 'true')
      const res = await fetch(`/api/invoices?${params}`, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      invoices.value = await res.json()
    } finally {
      loading.value = false
    }
  }

  async function updateFlags(token: string, ksefRef: string, flags: { ignored?: boolean; paid?: boolean }) {
    const res = await fetch(`/api/invoices/${encodeURIComponent(ksefRef)}`, {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(flags),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
  }

  return { invoices, showIgnored, showPaid, loading, fetchInvoices, updateFlags }
})
