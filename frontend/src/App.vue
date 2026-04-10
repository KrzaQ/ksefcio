<script setup lang="ts">
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
</script>

<template>
  <div class="min-h-screen">
    <nav v-if="auth.isAuthenticated" class="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-4">
        <router-link to="/invoices" class="font-semibold text-gray-900">ksefcio</router-link>
        <router-link to="/invoices" class="text-sm text-gray-600 hover:text-gray-900">Faktury</router-link>
        <router-link to="/basket" class="text-sm text-gray-600 hover:text-gray-900">Koszyk</router-link>
        <router-link to="/settings" class="text-sm text-gray-600 hover:text-gray-900">Ustawienia</router-link>
      </div>
      <div class="flex items-center gap-3 text-sm text-gray-500">
        <span>{{ auth.name }} ({{ auth.identity }})</span>
        <button @click="auth.logout()" class="text-red-600 hover:text-red-800">Wyloguj</button>
      </div>
    </nav>
    <main class="max-w-5xl mx-auto px-4 py-6">
      <router-view />
    </main>
  </div>
</template>
