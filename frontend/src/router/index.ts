import { createRouter, createWebHistory } from 'vue-router'

import { getToken, setUnauthorizedHandler } from 'src/api/client'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('src/pages/LoginPage.vue') },
    {
      path: '/',
      component: () => import('src/layouts/MainLayout.vue'),
      children: [
        // D16：PWA 打开的默认页就是「记一笔」，启动即光标就位
        { path: '', name: 'add', component: () => import('src/pages/AddEntryPage.vue') },
        { path: 'balance', name: 'balance', component: () => import('src/pages/BalancePage.vue') },
        { path: 'entries', name: 'entries', component: () => import('src/pages/EntriesPage.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.name !== 'login' && !getToken()) return { name: 'login' }
  if (to.name === 'login' && getToken()) return { name: 'add' }
  return true
})

setUnauthorizedHandler(() => {
  void router.push({ name: 'login' })
})
