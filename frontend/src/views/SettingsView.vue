<script setup lang="ts">
import { computed } from 'vue'
import { useEntitiesStore } from '../stores/entities'
import { useAuthStore } from '../stores/auth'

const entities = useEntitiesStore()
const auth = useAuthStore()
const activeEntity = computed(() => entities.getActive())
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold mb-4">Ustawienia</h1>

    <section class="mb-8">
      <h2 class="text-lg font-medium mb-2">Podmioty</h2>
      <div v-if="entities.entities.length === 0" class="text-gray-500 text-sm">
        Brak zapisanych podmiotów. Zaloguj się, aby dodać podmiot.
      </div>
      <ul v-else class="space-y-2">
        <li v-for="entity in entities.entities" :key="entity.identity" class="flex items-center justify-between border border-gray-700 rounded px-3 py-2">
          <div>
            <span class="font-medium">{{ entity.name }}</span>
            <span class="text-gray-500 text-sm ml-2">{{ entity.identity }}</span>
          </div>
          <div class="flex items-center gap-2">
            <button
              v-if="entities.activeIdentity !== entity.identity"
              @click="entities.activeIdentity = entity.identity"
              class="text-sm text-amber-400 hover:underline"
            >
              Aktywuj
            </button>
            <span v-else class="text-sm text-green-400">Aktywny</span>
            <button @click="entities.removeEntity(entity.identity)" class="text-sm text-red-400 hover:underline">Usuń</button>
          </div>
        </li>
      </ul>
    </section>

    <section class="mb-8" v-if="auth.isAuthenticated">
      <h2 class="text-lg font-medium mb-2">Konta bankowe nadawcy</h2>
      <p class="text-gray-500 text-sm mb-3">Numer konta źródłowego dla przelewów wychodzących z każdego NIP-u.</p>
      <div v-if="activeEntity?.ksefNips?.length" class="space-y-2">
        <div v-for="nip in activeEntity.ksefNips" :key="nip" class="flex items-center gap-3">
          <span class="font-mono text-sm w-28">{{ nip }}</span>
          <input
            :value="entities.getNipBankAccount(nip) ?? ''"
            @change="(e: Event) => entities.setNipBankAccount(nip, (e.target as HTMLInputElement).value)"
            placeholder="26-cyfrowy numer konta"
            class="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm font-mono flex-1 text-gray-200 focus:border-amber-500 focus:outline-none"
          />
        </div>
      </div>
      <div v-else class="text-gray-500 text-sm">
        Zsynchronizuj dane z KSeF, aby zobaczyć powiązane NIP-y.
      </div>
    </section>

    <section class="mb-8">
      <h2 class="text-lg font-medium mb-2">Tytuł przelewu</h2>
      <p class="text-gray-500 text-sm mb-2">
        Szablon tytułu przelewu. Dostępne zmienne: <code class="text-gray-400">{their_id}</code> (numer faktury), <code class="text-gray-400">{ksef_id}</code> (numer KSeF).
      </p>
      <input
        v-model="entities.transferTitleTemplate"
        class="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm w-full text-gray-200 focus:border-amber-500 focus:outline-none"
      />
    </section>

    <section>
      <h2 class="text-lg font-medium mb-2">Klucz szyfrujący</h2>
      <p class="text-gray-500 text-sm">Eksport i import klucza AES — do implementacji.</p>
    </section>
  </div>
</template>
