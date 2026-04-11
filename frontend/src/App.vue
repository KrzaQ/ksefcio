<script setup lang="ts">
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
</script>

<template>
  <div class="min-h-screen">
    <nav v-if="auth.isAuthenticated" class="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-4">
        <router-link to="/invoices" class="text-amber-400 text-xl tracking-wide" style="font-family: 'Cinzel Decorative', serif; font-weight: 700;">ksefcio</router-link>
        <router-link to="/invoices" class="text-sm text-gray-400 hover:text-gray-200">Faktury</router-link>
        <router-link to="/settings" class="text-sm text-gray-400 hover:text-gray-200">Ustawienia</router-link>
      </div>
      <div class="flex items-center gap-3 text-sm text-gray-500">
        <span>{{ auth.name }} ({{ auth.identity }})</span>
        <button @click="auth.logout()" class="text-red-400 hover:text-red-300">Wyloguj</button>
      </div>
    </nav>
    <main class="max-w-5xl mx-auto px-4 py-6">
      <router-view />
    </main>
  </div>
</template>
