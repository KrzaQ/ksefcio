import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const nip = ref<string | null>(null)
  const name = ref<string | null>(null)

  const isAuthenticated = computed(() => token.value !== null)

  function login(jwt: string, userNip: string, userName: string) {
    token.value = jwt
    nip.value = userNip
    name.value = userName
  }

  function logout() {
    token.value = null
    nip.value = null
    name.value = null
  }

  return { token, nip, name, isAuthenticated, login, logout }
})
