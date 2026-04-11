<script setup lang="ts">
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()

const appVersion = import.meta.env.VITE_APP_VERSION ?? 'dev'
const appCommit = import.meta.env.VITE_APP_COMMIT ?? 'unknown'
</script>

<template>
  <div class="min-h-screen">
    <nav v-if="auth.isAuthenticated" class="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-4">
        <router-link to="/invoices" class="text-amber-400 text-xl tracking-wide" style="font-family: 'Cinzel Decorative', serif; font-weight: 700;">ksefcio</router-link>
        <router-link to="/invoices" class="text-sm text-gray-400 hover:text-gray-200 px-2 py-1 rounded hover:bg-gray-800">Faktury</router-link>
        <router-link to="/settings" class="text-sm text-gray-400 hover:text-gray-200 px-2 py-1 rounded hover:bg-gray-800">Ustawienia</router-link>
      </div>
      <div class="flex items-center gap-3 text-sm text-gray-500">
        <span>{{ auth.name }} ({{ auth.identity }})</span>
        <button @click="auth.logout()" class="text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-gray-800">Wyloguj</button>
      </div>
    </nav>
    <main class="max-w-screen-xl mx-auto px-4 py-6">
      <router-view />
    </main>
    <footer class="border-t border-gray-800 px-4 py-3 text-center text-xs text-gray-600">
      © 2026 <a href="https://github.com/KrzaQ/ksefcio" class="text-gray-500 hover:text-amber-500">KrzaQ</a> · ksefcio
      <span v-if="appVersion !== 'dev'" class="ml-1">{{ appVersion }}</span>
      <span v-if="appCommit !== 'unknown'" class="ml-1 text-gray-700">{{ appCommit.slice(0, 7) }}</span>
    </footer>
  </div>
</template>
