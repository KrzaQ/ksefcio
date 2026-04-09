<script setup lang="ts">
defineProps<{ id: string }>()
</script>

<template>
  <div>
    <router-link to="/invoices" class="text-blue-600 text-sm hover:underline">&larr; Wróć do listy</router-link>
    <h1 class="text-xl font-semibold mt-2">Faktura {{ id }}</h1>
    <p class="text-gray-500 mt-4">Szczegóły faktury pojawią się tutaj.</p>
  </div>
</template>
