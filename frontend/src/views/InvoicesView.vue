<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useInvoicesStore, type DecryptedInvoice } from '../stores/invoices'
import { useAuthStore } from '../stores/auth'
import { useEntitiesStore } from '../stores/entities'
import { authenticateKsef } from '../ksef'
import { generateTransferFiles, downloadFile, cleanAccount } from '../transferGenerator'

const store = useInvoicesStore()
const auth = useAuthStore()
const entities = useEntitiesStore()

type SortKey = 'issue_date' | 'seller_name' | 'gross_amount'
const sortKey = ref<SortKey>('issue_date')
const sortAsc = ref(false)

// KSeF sync state
const syncing = ref(false)
const syncError = ref('')
const nipInput = ref('')

onMounted(() => {
  // Pre-fill NIP input from activeNip or identity
  if (auth.activeNip) {
    nipInput.value = auth.activeNip
  } else if (auth.identity && auth.identity.length === 10) {
    nipInput.value = auth.identity
  }
  store.fetchInvoices()
})

watch(() => auth.activeNip, () => {
  selectedRefs.value = new Set()
  store.fetchInvoices()
})
watch(() => store.showIgnored, () => store.fetchInvoices())

function selectNip(nip: string) {
  auth.activeNip = nip
  nipInput.value = nip
}

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

// Inline detail expansion
const expandedRef = ref<string | null>(null)

function toggleExpand(inv: DecryptedInvoice) {
  if (expandedRef.value === inv.ksef_ref) {
    expandedRef.value = null
  } else {
    expandedRef.value = inv.ksef_ref
    store.ensureLineItems(inv.ksef_ref)
  }
}

// Redownload
const redownloading = ref(false)
const redownloadError = ref('')

async function redownload(ksefRef: string) {
  redownloading.value = true
  redownloadError.value = ''
  try {
    await store.redownloadInvoice(ksefRef)
  } catch (e) {
    redownloadError.value = e instanceof Error ? e.message : 'Nieznany błąd'
  } finally {
    redownloading.value = false
  }
}

// Multi-select
const selectedRefs = ref<Set<string>>(new Set())

const allVisibleSelected = computed(() =>
  filteredInvoices.value.length > 0 &&
  filteredInvoices.value.every(inv => selectedRefs.value.has(inv.ksef_ref))
)

const selectedInvoices = computed(() =>
  filteredInvoices.value.filter(inv => selectedRefs.value.has(inv.ksef_ref))
)

const anySelectedMissingAccount = computed(() =>
  selectedInvoices.value.some(inv => !inv.bank_account)
)

function toggleSelect(inv: DecryptedInvoice) {
  const s = new Set(selectedRefs.value)
  if (s.has(inv.ksef_ref)) s.delete(inv.ksef_ref)
  else s.add(inv.ksef_ref)
  selectedRefs.value = s
}

function toggleSelectAll() {
  if (allVisibleSelected.value) {
    selectedRefs.value = new Set()
  } else {
    selectedRefs.value = new Set(filteredInvoices.value.map(inv => inv.ksef_ref))
  }
}

function selectUnpaid() {
  selectedRefs.value = new Set(
    filteredInvoices.value.filter(inv => !inv.paid && !inv.ignored).map(inv => inv.ksef_ref)
  )
}

// Bulk actions
const bulkActionError = ref('')
const bulkActionLoading = ref(false)

async function bulkAction(flags: { ignored?: boolean; paid?: boolean }) {
  bulkActionLoading.value = true
  bulkActionError.value = ''
  try {
    await store.bulkUpdateFlags([...selectedRefs.value], flags)
  } catch (e) {
    bulkActionError.value = e instanceof Error ? e.message : 'Nieznany błąd'
  } finally {
    bulkActionLoading.value = false
  }
}

// Transfer generation
const showBankAccountPrompt = ref(false)
const bankAccountInput = ref('')

function handleGenerate() {
  const nip = auth.activeNip
  if (!nip) return
  const savedAccount = entities.getNipBankAccount(nip)
  if (!savedAccount) {
    showBankAccountPrompt.value = true
    return
  }
  doGenerate(savedAccount)
}

function saveBankAccountAndGenerate() {
  const nip = auth.activeNip
  if (!nip) return
  const account = cleanAccount(bankAccountInput.value)
  if (account.length !== 26) {
    bulkActionError.value = 'Numer konta musi mieć 26 cyfr'
    return
  }
  entities.setNipBankAccount(nip, account)
  showBankAccountPrompt.value = false
  doGenerate(account)
}

function doGenerate(senderAccount: string) {
  const entity = entities.getActive()
  if (!entity) return

  const config = {
    senderAccount,
    senderName: entity.name,
    titleTemplate: entities.transferTitleTemplate,
  }

  const invs = selectedInvoices.value.filter(inv => inv.bank_account)
  const files = generateTransferFiles(invs, config)
  const dateStr = new Date().toISOString().slice(0, 10)

  files.forEach((content, idx) => {
    const suffix = files.length > 1 ? `_${idx + 1}` : ''
    downloadFile(content, `przelewy_${dateStr}${suffix}.csv`)
  })
}

async function startSync() {
  syncError.value = ''
  const nip = nipInput.value.replace(/\s/g, '')
  if (!/^\d{10}$/.test(nip)) {
    syncError.value = 'NIP musi mieć 10 cyfr'
    return
  }
  await doSync(nip)
}

async function doSync(nip: string) {
  syncing.value = true
  syncError.value = ''
  try {
    const tokens = await authenticateKsef(nip)
    auth.ksefAccessToken = tokens.accessToken
    auth.activeNip = nip
    if (!auth.knownNips.includes(nip)) {
      auth.knownNips.push(nip)
    }
    // Persist verified NIP to entity in localStorage
    const entity = entities.getActive()
    if (entity && !entity.ksefNips?.includes(nip)) {
      entity.ksefNips = [...(entity.ksefNips ?? []), nip]
      entities.addEntity(entity)
    }
    console.log('[sync] KSeF auth success, fetching invoices...')
    const count = await store.syncFromKsef(tokens.accessToken)
    console.log(`[sync] Synced ${count} new invoices`)
  } catch (e) {
    console.error('[sync] Error:', e)
    syncError.value = e instanceof Error ? e.message : 'Nieznany błąd'
  } finally {
    syncing.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-xl font-semibold">Faktury</h1>
      <div class="flex items-center gap-2">
        <!-- NIP selector: known NIPs as buttons + manual input -->
        <button
          v-for="nip in auth.knownNips"
          :key="nip"
          @click="selectNip(nip)"
          class="px-3 py-2 rounded text-sm font-mono border"
          :class="auth.activeNip === nip
            ? 'border-amber-500 bg-amber-950/40 text-amber-400'
            : 'border-gray-700 text-gray-400 hover:border-gray-600'"
        >
          {{ nip }}
        </button>
        <input
          v-model="nipInput"
          placeholder="NIP (10 cyfr)"
          class="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm w-36 font-mono text-gray-200 focus:border-amber-500 focus:outline-none"
          maxlength="10"
          @keyup.enter="startSync"
        />
        <button
          @click="startSync"
          :disabled="syncing"
          class="bg-amber-600 text-white px-4 py-2 rounded text-sm hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ syncing ? 'Synchronizacja...' : 'Synchronizuj z KSeF' }}
        </button>
      </div>
    </div>

    <div v-if="store.syncProgress" class="bg-amber-950/40 text-amber-400 text-sm px-3 py-2 rounded mb-4">
      {{ store.syncProgress }}
    </div>

    <div v-if="syncError" class="bg-red-950/40 text-red-400 text-sm px-3 py-2 rounded mb-4">
      {{ syncError }}
    </div>

    <div class="flex items-center gap-4 mb-4 text-sm text-gray-400">
      <label class="flex items-center gap-1.5">
        <input type="checkbox" v-model="store.showPaid" />
        Pokaż opłacone
      </label>
      <label class="flex items-center gap-1.5">
        <input type="checkbox" v-model="store.showIgnored" />
        Pokaż ignorowane
      </label>
      <button @click="selectUnpaid" class="bg-amber-600 text-white px-3 py-1.5 rounded text-sm hover:bg-amber-500">
        Zaznacz nieopłacone
      </button>
    </div>

    <div v-if="store.decryptError" class="bg-red-950/40 text-red-400 text-sm px-3 py-2 rounded mb-4">
      {{ store.decryptError }}
    </div>

    <!-- Action bar -->
    <div v-if="selectedRefs.size > 0" class="sticky top-0 z-10 bg-gray-900 border border-gray-700 rounded px-4 py-3 mb-4 flex items-center gap-3 flex-wrap">
      <span class="text-sm text-gray-400">Zaznaczono: {{ selectedRefs.size }}</span>
      <button @click="bulkAction({ ignored: true })" :disabled="bulkActionLoading"
        class="bg-gray-700 text-gray-200 px-3 py-1.5 rounded text-sm hover:bg-gray-600 disabled:opacity-50">
        Ignoruj
      </button>
      <button @click="bulkAction({ paid: true })" :disabled="bulkActionLoading"
        class="bg-gray-700 text-gray-200 px-3 py-1.5 rounded text-sm hover:bg-gray-600 disabled:opacity-50">
        Opłacone
      </button>
      <button @click="handleGenerate"
        :disabled="bulkActionLoading || anySelectedMissingAccount"
        class="bg-amber-600 text-white px-3 py-1.5 rounded text-sm hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed"
        :title="anySelectedMissingAccount ? 'Odznacz faktury bez numeru konta' : ''">
        Generuj koszyk przelewów
      </button>
      <span v-if="anySelectedMissingAccount" class="text-red-400 text-xs">
        Odznacz faktury bez numeru konta
      </span>
      <span v-if="bulkActionError" class="text-red-400 text-xs">{{ bulkActionError }}</span>
    </div>

    <!-- Bank account prompt -->
    <div v-if="showBankAccountPrompt" class="border border-amber-600 rounded px-4 py-3 mb-4 bg-amber-950/30">
      <p class="text-sm text-gray-300 mb-2">Podaj numer konta nadawcy dla NIP {{ auth.activeNip }}:</p>
      <div class="flex items-center gap-2">
        <input v-model="bankAccountInput" placeholder="26-cyfrowy numer konta"
          @keyup.enter="saveBankAccountAndGenerate"
          class="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm font-mono w-72 text-gray-200 focus:border-amber-500 focus:outline-none"
          maxlength="32" />
        <button @click="saveBankAccountAndGenerate"
          class="bg-amber-600 text-white px-3 py-2 rounded text-sm hover:bg-amber-500">
          Zapisz i generuj
        </button>
        <button @click="showBankAccountPrompt = false"
          class="text-gray-500 text-sm hover:text-gray-300">
          Anuluj
        </button>
      </div>
    </div>

    <div v-if="!auth.activeNip" class="text-gray-500 text-sm">
      Wybierz NIP lub zsynchronizuj dane z KSeF, aby zobaczyć faktury.
    </div>

    <div v-else-if="store.loading" class="text-gray-500 text-sm">
      Wczytywanie faktur...
    </div>

    <div v-else-if="filteredInvoices.length === 0" class="text-gray-500 text-sm">
      Brak faktur do wyświetlenia. Zsynchronizuj dane z KSeF, aby zobaczyć faktury.
    </div>

    <table v-else class="w-full text-sm">
      <thead>
        <tr class="border-b border-gray-700 text-left text-gray-500">
          <th class="py-2 px-2 w-8" @click.stop>
            <input type="checkbox" :checked="allVisibleSelected" @change="toggleSelectAll" />
          </th>
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
        <template v-for="inv in filteredInvoices" :key="inv.ksef_ref">
          <tr
            @click="toggleExpand(inv)"
            class="border-b border-gray-800 hover:bg-gray-900 cursor-pointer"
            :class="{ 'opacity-40': inv.ignored, 'text-gray-600': inv.paid }"
          >
            <td class="py-2 px-2 text-center" @click.stop>
              <input type="checkbox" :checked="selectedRefs.has(inv.ksef_ref)" @change="toggleSelect(inv)" />
            </td>
            <td class="py-2 px-2">{{ inv.issue_date }}</td>
            <td class="py-2 px-2 font-mono text-xs">{{ inv.invoice_number }}</td>
            <td class="py-2 px-2">
              <div class="flex items-center gap-1">
                <span>{{ inv.seller_name }}</span>
                <span v-if="!inv.bank_account" class="text-red-500 text-xs font-bold" title="Brak numeru konta bankowego">!</span>
              </div>
              <div class="text-xs text-gray-500">{{ inv.seller_nip }}</div>
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
          <!-- Expanded detail row -->
          <tr v-if="expandedRef === inv.ksef_ref">
            <td colspan="8" class="bg-gray-900 px-4 py-3 border-b border-gray-800">
              <div class="grid grid-cols-2 gap-x-8 gap-y-2 text-sm max-w-lg mb-3">
                <div>
                  <span class="text-gray-500 text-xs">Nabywca</span>
                  <div>{{ inv.buyer_name }}</div>
                  <div class="text-xs text-gray-500">NIP {{ inv.buyer_nip }}</div>
                </div>
                <div>
                  <span class="text-gray-500 text-xs">Netto / VAT</span>
                  <div>{{ formatAmount(inv.net_amount) }} + {{ formatAmount(inv.vat_amount) }} {{ inv.currency }}</div>
                </div>
                <div v-if="inv.bank_account">
                  <span class="text-gray-500 text-xs">Konto bankowe</span>
                  <div class="font-mono text-xs">{{ inv.bank_account }}</div>
                </div>
                <div>
                  <span class="text-gray-500 text-xs">KSeF</span>
                  <div class="text-xs text-gray-500">{{ inv.ksef_ref }}</div>
                </div>
              </div>

              <!-- Line items -->
              <table v-if="inv.line_items?.length" class="w-full text-xs mt-2 mb-3">
                <thead>
                  <tr class="border-b border-gray-700 text-gray-500">
                    <th class="py-1 px-2 text-left">Opis</th>
                    <th class="py-1 px-2 text-right">Ilość</th>
                    <th class="py-1 px-2 text-right">Cena jedn.</th>
                    <th class="py-1 px-2 text-right">Netto</th>
                    <th class="py-1 px-2 text-right">VAT</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(item, idx) in inv.line_items" :key="idx" class="border-b border-gray-800">
                    <td class="py-1 px-2">{{ item.description }}</td>
                    <td class="py-1 px-2 text-right font-mono">{{ item.quantity ?? '' }} {{ item.unit ?? '' }}</td>
                    <td class="py-1 px-2 text-right font-mono">{{ item.unit_price ? formatAmount(item.unit_price) : '' }}</td>
                    <td class="py-1 px-2 text-right font-mono">{{ formatAmount(item.net_amount) }}</td>
                    <td class="py-1 px-2 text-right">{{ item.vat_rate ?? '' }}{{ item.vat_rate && !isNaN(Number(item.vat_rate)) ? '%' : '' }}</td>
                  </tr>
                </tbody>
              </table>

              <div class="flex items-center gap-4 text-xs" @click.stop>
                <button
                  @click="redownload(inv.ksef_ref)"
                  :disabled="redownloading"
                  class="text-gray-500 hover:text-gray-300 disabled:opacity-50"
                >
                  {{ redownloading ? 'Pobieranie...' : 'Pobierz ponownie z KSeF' }}
                </button>
                <span v-if="redownloadError" class="text-red-400">{{ redownloadError }}</span>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>
