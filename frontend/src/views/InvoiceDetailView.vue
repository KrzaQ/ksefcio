<script setup lang="ts">
import { computed, ref } from 'vue'
import { useInvoicesStore } from '../stores/invoices'

const props = defineProps<{ id: string }>()
const store = useInvoicesStore()

const invoice = computed(() =>
  store.decryptedInvoices.find(i => i.ksef_ref === props.id),
)

const redownloading = ref(false)
const redownloadError = ref('')

async function redownload() {
  redownloading.value = true
  redownloadError.value = ''
  try {
    await store.redownloadInvoice(props.id)
  } catch (e) {
    redownloadError.value = e instanceof Error ? e.message : 'Nieznany błąd'
  } finally {
    redownloading.value = false
  }
}

const amountFmt = new Intl.NumberFormat('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
function fmt(value: string): string {
  const n = parseFloat(value)
  return isNaN(n) ? value : amountFmt.format(n)
}
</script>

<template>
  <div>
    <router-link to="/invoices" class="text-amber-400 text-sm hover:underline">&larr; Wróć do listy</router-link>

    <div v-if="!invoice" class="mt-4 text-gray-500 text-sm">
      Faktura nie została znaleziona. Wróć do listy i spróbuj ponownie.
    </div>

    <template v-else>
      <h1 class="text-xl font-semibold mt-2">{{ invoice.invoice_number }}</h1>
      <p class="text-xs text-gray-500 mt-1">KSeF: {{ invoice.ksef_ref }}</p>

      <div class="grid grid-cols-2 gap-x-8 gap-y-3 mt-6 text-sm max-w-lg">
        <div>
          <div class="text-gray-500 text-xs">Sprzedawca</div>
          <div class="font-medium">{{ invoice.seller_name }}</div>
          <div class="text-xs text-gray-500">NIP {{ invoice.seller_nip }}</div>
        </div>
        <div>
          <div class="text-gray-500 text-xs">Nabywca</div>
          <div class="font-medium">{{ invoice.buyer_name }}</div>
          <div class="text-xs text-gray-500">NIP {{ invoice.buyer_nip }}</div>
        </div>

        <div>
          <div class="text-gray-500 text-xs">Data wystawienia</div>
          <div>{{ invoice.issue_date }}</div>
        </div>
        <div>
          <div class="text-gray-500 text-xs">Termin płatności</div>
          <div>{{ invoice.due_date ?? '\u2014' }}</div>
        </div>

        <div>
          <div class="text-gray-500 text-xs">Netto</div>
          <div>{{ fmt(invoice.net_amount) }} {{ invoice.currency }}</div>
        </div>
        <div>
          <div class="text-gray-500 text-xs">VAT</div>
          <div>{{ fmt(invoice.vat_amount) }} {{ invoice.currency }}</div>
        </div>
        <div>
          <div class="text-gray-500 text-xs">Brutto</div>
          <div class="font-semibold">{{ fmt(invoice.gross_amount) }} {{ invoice.currency }}</div>
        </div>
        <div v-if="invoice.bank_account">
          <div class="text-gray-500 text-xs">Konto bankowe</div>
          <div class="font-mono text-xs">{{ invoice.bank_account }}</div>
        </div>
      </div>

      <div class="flex gap-4 mt-6 text-sm">
        <span :class="invoice.paid ? 'text-green-400' : 'text-gray-500'">
          {{ invoice.paid ? 'Opłacona' : 'Nieopłacona' }}
        </span>
        <span v-if="invoice.ignored" class="text-gray-500">Ignorowana</span>
      </div>

      <div class="mt-6">
        <button
          @click="redownload"
          :disabled="redownloading"
          class="text-sm text-gray-500 hover:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ redownloading ? 'Pobieranie...' : 'Pobierz ponownie z KSeF' }}
        </button>
        <p v-if="redownloadError" class="text-red-400 text-sm mt-1">{{ redownloadError }}</p>
      </div>
    </template>
  </div>
</template>
