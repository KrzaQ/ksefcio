<script setup lang="ts">
import { useEntitiesStore } from '../stores/entities'

const entities = useEntitiesStore()
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
        <li v-for="entity in entities.entities" :key="entity.nip" class="flex items-center justify-between border border-gray-200 rounded px-3 py-2">
          <div>
            <span class="font-medium">{{ entity.name }}</span>
            <span class="text-gray-500 text-sm ml-2">NIP: {{ entity.nip }}</span>
          </div>
          <div class="flex items-center gap-2">
            <button
              v-if="entities.activeNip !== entity.nip"
              @click="entities.activeNip = entity.nip"
              class="text-sm text-blue-600 hover:underline"
            >
              Aktywuj
            </button>
            <span v-else class="text-sm text-green-600">Aktywny</span>
            <button @click="entities.removeEntity(entity.nip)" class="text-sm text-red-600 hover:underline">Usuń</button>
          </div>
        </li>
      </ul>
    </section>

    <section>
      <h2 class="text-lg font-medium mb-2">Klucz szyfrujący</h2>
      <p class="text-gray-500 text-sm">Eksport i import klucza AES — do implementacji.</p>
    </section>
  </div>
</template>
