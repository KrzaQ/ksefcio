<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useEntitiesStore } from '../stores/entities'
import {
  decryptPrivateKey,
  parseCertificate,
  extractIdentityFromCert,
  loadAesKey,
  storeAesKey,
  generateAesKey,
  wrapAesKey,
  makeNonExtractable,
  unwrapAesKey,
  arrayBufferToBase64,
  base64ToArrayBuffer,
  signRequest,
} from '../crypto'

const router = useRouter()
const auth = useAuthStore()
const entities = useEntitiesStore()

const selectedNip = ref<string | null>(entities.entities[0]?.nip ?? null)
const showNewForm = ref(entities.entities.length === 0)

const certFile = ref<File | null>(null)
const keyFile = ref<File | null>(null)
const password = ref('')
const error = ref('')
const loading = ref(false)

const selectedEntity = computed(() =>
  entities.entities.find(e => e.nip === selectedNip.value),
)

function onCertChange(e: Event) {
  const input = e.target as HTMLInputElement
  certFile.value = input.files?.[0] ?? null
}

function onKeyChange(e: Event) {
  const input = e.target as HTMLInputElement
  keyFile.value = input.files?.[0] ?? null
}

async function signedFetch(
  path: string,
  signingKey: CryptoKey,
  certDer: Uint8Array,
  options: RequestInit = {},
): Promise<Response> {
  const timestamp = Math.floor(Date.now() / 1000)
  const signature = await signRequest(signingKey, (options.method ?? 'GET').toUpperCase(), path, timestamp)

  const headers = new Headers(options.headers)
  headers.set('X-Cert', arrayBufferToBase64(certDer))
  headers.set('X-Timestamp', String(timestamp))
  headers.set('X-Signature', signature)

  return fetch(path, { ...options, headers })
}

async function login() {
  error.value = ''

  let certPem: string
  let keyPem: string

  if (showNewForm.value) {
    if (!certFile.value || !keyFile.value) {
      error.value = 'Wybierz pliki certyfikatu i klucza'
      return
    }
    certPem = await certFile.value.text()
    keyPem = await keyFile.value.text()
  } else {
    if (!selectedEntity.value) {
      error.value = 'Wybierz podmiot'
      return
    }
    certPem = selectedEntity.value.certPem
    keyPem = selectedEntity.value.keyPem
  }

  loading.value = true
  try {
    // 1. Decrypt private key
    console.log('[login] Decrypting private key...')
    const { signingKey, unwrapKey } = await decryptPrivateKey(keyPem, password.value)
    console.log('[login] Key imported. Signing algo:', signingKey.algorithm.name)

    // 2. Parse certificate
    console.log('[login] Parsing certificate...')
    const { derBytes, publicKey } = await parseCertificate(certPem)
    const { nip: certNip, pesel, name } = extractIdentityFromCert(derBytes)
    const userId = certNip ?? pesel!
    console.log('[login] Identity:', certNip ? `NIP ${certNip}` : `PESEL ${pesel}`, name)

    // 3. Load or setup AES key
    let aesKey = await loadAesKey(userId)
    console.log('[login] AES key from IndexedDB:', aesKey ? 'found' : 'not found')

    if (!aesKey) {
      const res = await signedFetch('/api/users/me', signingKey, derBytes)
      console.log('[login] GET /api/users/me:', res.status)

      if (res.ok) {
        const data = await res.json()
        if (data.wrapped_aes_key) {
          console.log('[login] Unwrapping AES key from server...')
          const wrappedBytes = base64ToArrayBuffer(data.wrapped_aes_key)
          aesKey = await unwrapAesKey(wrappedBytes, unwrapKey, publicKey)
          await storeAesKey(userId, aesKey)
          console.log('[login] AES key unwrapped and stored')
        }
      }

      if (!aesKey) {
        console.log('[login] Generating new AES key...')
        const extractableKey = await generateAesKey()
        const wrappedBytes = await wrapAesKey(extractableKey, publicKey, unwrapKey)

        const uploadRes = await signedFetch('/api/users/me/wrapped-key', signingKey, derBytes, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            wrapped_aes_key: arrayBufferToBase64(wrappedBytes),
            cert_fingerprint: 'auto',
          }),
        })
        if (!uploadRes.ok) {
          const body = await uploadRes.text()
          throw new Error(`Nie udało się zapisać klucza: HTTP ${uploadRes.status} — ${body}`)
        }

        aesKey = await makeNonExtractable(extractableKey)
        await storeAesKey(userId, aesKey)
        console.log('[login] AES key generated and stored')
      }
    }

    // 4. Save entity to localStorage (cert + encrypted key)
    entities.addEntity({ nip: userId, name, certPem, keyPem })

    // 5. Set session state
    auth.login(signingKey, unwrapKey, derBytes, userId, name, aesKey)
    console.log('[login] Session established for', userId)

    // 6. Navigate
    router.push('/invoices')
  } catch (e) {
    console.error('[login] Error:', e)
    error.value = e instanceof Error ? e.message : 'Nieznany błąd'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-md mx-auto mt-16">
    <h1 class="text-2xl font-semibold mb-6">Logowanie — ksefcio</h1>

    <!-- Saved entities -->
    <div v-if="entities.entities.length > 0 && !showNewForm" class="space-y-4">
      <div class="space-y-2">
        <label class="block text-sm font-medium text-gray-700">Podmiot</label>
        <div
          v-for="entity in entities.entities"
          :key="entity.nip"
          @click="selectedNip = entity.nip"
          class="flex items-center gap-3 border rounded px-3 py-2 cursor-pointer"
          :class="selectedNip === entity.nip ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'"
        >
          <div class="flex-1">
            <div class="font-medium text-sm">{{ entity.name }}</div>
            <div class="text-xs text-gray-500">{{ entity.nip }}</div>
          </div>
        </div>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Hasło klucza</label>
        <input type="password" v-model="password" class="block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
      </div>

      <button
        @click="login"
        :disabled="loading"
        class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {{ loading ? 'Logowanie...' : 'Zaloguj' }}
      </button>

      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>

      <button @click="showNewForm = true" class="w-full text-sm text-gray-500 hover:text-gray-700">
        + Dodaj nowy podmiot
      </button>
    </div>

    <!-- New entity form -->
    <form v-else @submit.prevent="login" class="space-y-4">
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
      <button
        type="submit"
        :disabled="loading"
        class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {{ loading ? 'Logowanie...' : 'Zaloguj' }}
      </button>
      <p v-if="error" class="text-red-600 text-sm">{{ error }}</p>

      <button
        v-if="entities.entities.length > 0"
        type="button"
        @click="showNewForm = false"
        class="w-full text-sm text-gray-500 hover:text-gray-700"
      >
        Wróć do listy podmiotów
      </button>
    </form>
  </div>
</template>
