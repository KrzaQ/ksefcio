import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import InvoicesView from './views/InvoicesView.vue'
import InvoiceDetailView from './views/InvoiceDetailView.vue'
import BasketView from './views/BasketView.vue'
import SettingsView from './views/SettingsView.vue'
import { useAuthStore } from './stores/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    { path: '/invoices', name: 'invoices', component: InvoicesView },
    { path: '/invoices/:id', name: 'invoice-detail', component: InvoiceDetailView, props: true },
    { path: '/basket', name: 'basket', component: BasketView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/', redirect: '/invoices' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.isAuthenticated) {
    return { name: 'login' }
  }
})
