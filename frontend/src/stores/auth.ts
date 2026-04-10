import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  // Session state — memory-only, not persisted
  const signingKey = shallowRef<CryptoKey | null>(null)
  const unwrapKey = shallowRef<CryptoKey | null>(null)
  const certDer = shallowRef<Uint8Array | null>(null)
  const nip = ref<string | null>(null)
  const name = ref<string | null>(null)
  const aesKey = shallowRef<CryptoKey | null>(null)
  const ksefAccessToken = ref<string | null>(null)

  const isAuthenticated = computed(() => signingKey.value !== null)

  function login(
    newSigningKey: CryptoKey,
    newUnwrapKey: CryptoKey,
    newCertDer: Uint8Array,
    newNip: string,
    newName: string,
    newAesKey: CryptoKey,
  ) {
    signingKey.value = newSigningKey
    unwrapKey.value = newUnwrapKey
    certDer.value = newCertDer
    nip.value = newNip
    name.value = newName
    aesKey.value = newAesKey
  }

  function logout() {
    signingKey.value = null
    unwrapKey.value = null
    certDer.value = null
    nip.value = null
    name.value = null
    aesKey.value = null
    ksefAccessToken.value = null
  }

  return { signingKey, unwrapKey, certDer, nip, name, aesKey, ksefAccessToken, isAuthenticated, login, logout }
})
