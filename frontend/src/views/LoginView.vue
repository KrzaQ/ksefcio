<script setup lang="ts">
import { ref } from 'vue'

const certFile = ref<File | null>(null)
const keyFile = ref<File | null>(null)
const password = ref('')
const error = ref('')

function onCertChange(e: Event) {
  const input = e.target as HTMLInputElement
  certFile.value = input.files?.[0] ?? null
}

function onKeyChange(e: Event) {
  const input = e.target as HTMLInputElement
  keyFile.value = input.files?.[0] ?? null
}

async function login() {
  error.value = ''
  if (!certFile.value || !keyFile.value) {
    error.value = 'Wybierz pliki certyfikatu i klucza'
    return
  }
  // TODO: implement actual auth flow
  error.value = 'Auth flow not implemented yet'
}
</script>

<template>
  <div class="max-w-md mx-auto mt-16">
    <h1 class="text-2xl font-semibold mb-6">Logowanie — ksefcio</h1>
    <form @submit.prevent="login" class="space-y-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Certyfikat (.pem)</label>
        <input type="file" accept=".pem,.crt" @change="onCertChange" class="block w-full text-sm" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Klucz prywatny (.key)</label>
        <input type="file" accept=".key,.pem" @change="onKeyChange" class="block w-full text-sm" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Hasło klucza</label>
        <input type="password" v-model="password" class="block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
      </div>
      <button type="submit" class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 text-sm font-medium">
        Zaloguj
      </button>
      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>
    </form>
  </div>
</template>
