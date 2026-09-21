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
        { path: 'entries', name: 'entries', component: () => import('src/pages/EntriesPage.vue') },
        // 固定费独立一屏：账单来了随时填，不用等到出账单
        { path: 'monthly', name: 'monthly', component: () => import('src/pages/MonthlyPage.vue') },
        // 账单就是第二个 Tab。它已经包含了每人的应担/已垫付/应收应付和转账方案，
        // 原来的「余额」页是它的子集，留着只会让人问「这两个有什么区别」
        { path: 'bill/:statementId?', name: 'bill', component: () => import('src/pages/BillPage.vue') },
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
