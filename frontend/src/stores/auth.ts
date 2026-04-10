import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  // Session state — memory-only, not persisted
  const signingKey = shallowRef<CryptoKey | null>(null)
  const unwrapKey = shallowRef<CryptoKey | null>(null)
  const certDer = shallowRef<Uint8Array | null>(null)
  const identity = ref<string | null>(null)
  const name = ref<string | null>(null)
  const aesKey = shallowRef<CryptoKey | null>(null)
  const ksefAccessToken = ref<string | null>(null)

  const isAuthenticated = computed(() => signingKey.value !== null)

  function login(
    newSigningKey: CryptoKey,
    newUnwrapKey: CryptoKey,
    newCertDer: Uint8Array,
    newIdentity: string,
    newName: string,
    newAesKey: CryptoKey,
  ) {
    signingKey.value = newSigningKey
    unwrapKey.value = newUnwrapKey
    certDer.value = newCertDer
    identity.value = newIdentity
    name.value = newName
    aesKey.value = newAesKey
  }

  function logout() {
    signingKey.value = null
    unwrapKey.value = null
    certDer.value = null
    identity.value = null
    name.value = null
    aesKey.value = null
    ksefAccessToken.value = null
  }

  return { signingKey, unwrapKey, certDer, identity, name, aesKey, ksefAccessToken, isAuthenticated, login, logout }
})
