<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useInvoicesStore, type DecryptedInvoice } from '../stores/invoices'

const router = useRouter()
const store = useInvoicesStore()

type SortKey = 'issue_date' | 'seller_name' | 'gross_amount'
const sortKey = ref<SortKey>('issue_date')
const sortAsc = ref(false)

onMounted(() => store.fetchInvoices())

watch(() => store.showIgnored, () => store.fetchInvoices())

const filteredInvoices = computed(() => {
  let list = store.decryptedInvoices
  if (!store.showPaid) {
    list = list.filter(i => !i.paid)
  }

  const key = sortKey.value
  const dir = sortAsc.value ? 1 : -1
  return [...list].sort((a, b) => {
    if (key === 'gross_amount') {
      return dir * (parseFloat(a.gross_amount) - parseFloat(b.gross_amount))
    }
    return dir * String(a[key]).localeCompare(String(b[key]), 'pl')
  })
})

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    sortKey.value = key
    sortAsc.value = key !== 'issue_date'
  }
}

function sortIndicator(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortAsc.value ? ' \u25B2' : ' \u25BC'
}

const amountFmt = new Intl.NumberFormat('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function formatAmount(value: string): string {
  const n = parseFloat(value)
  return isNaN(n) ? value : amountFmt.format(n)
}

async function togglePaid(inv: DecryptedInvoice) {
  await store.updateFlags(inv.ksef_ref, { paid: !inv.paid })
}

async function toggleIgnored(inv: DecryptedInvoice) {
  await store.updateFlags(inv.ksef_ref, { ignored: !inv.ignored })
}

function goToDetail(inv: DecryptedInvoice) {
  router.push(`/invoices/${encodeURIComponent(inv.ksef_ref)}`)
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-xl font-semibold">Faktury</h1>
      <button
        disabled
        class="bg-gray-400 text-white px-4 py-2 rounded text-sm cursor-not-allowed"
      >
        Synchronizuj z KSeF
      </button>
    </div>

    <div class="flex items-center gap-4 mb-4 text-sm">
      <label class="flex items-center gap-1.5">
        <input type="checkbox" v-model="store.showPaid" />
        Pokaż opłacone
      </label>
      <label class="flex items-center gap-1.5">
        <input type="checkbox" v-model="store.showIgnored" />
        Pokaż ignorowane
      </label>
    </div>

    <div v-if="store.decryptError" class="bg-red-50 text-red-700 text-sm px-3 py-2 rounded mb-4">
      {{ store.decryptError }}
    </div>

    <div v-if="store.loading" class="text-gray-500 text-sm">
      Wczytywanie faktur...
    </div>

    <div v-else-if="filteredInvoices.length === 0" class="text-gray-500 text-sm">
      Brak faktur do wyświetlenia. Zsynchronizuj dane z KSeF, aby zobaczyć faktury.
    </div>

    <table v-else class="w-full text-sm">
      <thead>
        <tr class="border-b border-gray-200 text-left text-gray-500">
          <th @click="toggleSort('issue_date')" class="py-2 px-2 cursor-pointer select-none">
            Data wystawienia{{ sortIndicator('issue_date') }}
          </th>
          <th class="py-2 px-2">Numer</th>
          <th @click="toggleSort('seller_name')" class="py-2 px-2 cursor-pointer select-none">
            Sprzedawca{{ sortIndicator('seller_name') }}
          </th>
          <th @click="toggleSort('gross_amount')" class="py-2 px-2 text-right cursor-pointer select-none">
            Kwota brutto{{ sortIndicator('gross_amount') }}
          </th>
          <th class="py-2 px-2">Termin płatności</th>
          <th class="py-2 px-2 text-center">Opłacona</th>
          <th class="py-2 px-2 text-center">Ignorowana</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="inv in filteredInvoices"
          :key="inv.ksef_ref"
          @click="goToDetail(inv)"
          class="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
          :class="{ 'opacity-50': inv.ignored }"
        >
          <td class="py-2 px-2">{{ inv.issue_date }}</td>
          <td class="py-2 px-2 font-mono text-xs">{{ inv.invoice_number }}</td>
          <td class="py-2 px-2">
            <div>{{ inv.seller_name }}</div>
            <div class="text-xs text-gray-400">{{ inv.seller_nip }}</div>
          </td>
          <td class="py-2 px-2 text-right font-mono">
            {{ formatAmount(inv.gross_amount) }} {{ inv.currency }}
          </td>
          <td class="py-2 px-2">{{ inv.due_date ?? '\u2014' }}</td>
          <td class="py-2 px-2 text-center" @click.stop>
            <input type="checkbox" :checked="inv.paid" @change="togglePaid(inv)" />
          </td>
          <td class="py-2 px-2 text-center" @click.stop>
            <input type="checkbox" :checked="inv.ignored" @change="toggleIgnored(inv)" />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
