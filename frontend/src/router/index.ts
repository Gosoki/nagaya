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
        // 改一笔账 —— 跟「记一笔」同一屏，只是带着 id 进去。
        // 已出账的也能改：钱是全局累计的，差额自己进下一张的「上期结转」
        { path: 'entry/:id', name: 'entry-edit', component: () => import('src/pages/AddEntryPage.vue') },
        // 固定费独立一屏：账单来了随时填，不用等到出账单
        { path: 'monthly/:statementId?', name: 'monthly', component: () => import('src/pages/MonthlyPage.vue') },
        // 账单就是第二个 Tab。它已经包含了每人的应担/已垫付/应收应付和转账方案，
        // 原来的「余额」页是它的子集，留着只会让人问「这两个有什么区别」
        // 账单三页（未出账/已出账/以前）**共用这一个地址**，点页签只换状态不换 URL。
        // :statementId 只是个入口：从账目或固定费屏点进某一张时带着它进来，
        // 页面收下之后会把地址 replace 回 /bill
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

/**
 * 页面是懒加载的：新版发布后，还开着的旧页面点 Tab 会去取一个已经被删掉的 chunk，
 * 动态 import 抛错、导航被 reject —— 界面上就是**点了没反应**，没有任何提示。
 *
 * 这时唯一正确的动作是重新加载：index.html 是 no-cache 的，刷一下就拿到新版。
 * 加个标记防止「刷了还是失败」时无限循环。
 */
const RELOADED = 'nagaya.reloadedForChunk'
router.onError((err) => {
  const stale = /dynamically imported module|Importing a module script failed|Failed to fetch/i.test(
    String(err),
  )
  if (!stale) return
  if (sessionStorage.getItem(RELOADED)) return      // 已经刷过一次还不行，别再刷
  try {
    sessionStorage.setItem(RELOADED, '1')
  } catch {
    /* 隐私模式下存不了就算了，大不了不防重 */
  }
  location.reload()
})
router.afterEach(() => {
  try {
    sessionStorage.removeItem(RELOADED)             // 成功导航过就把标记清掉
  } catch {
    /* ignore */
  }
})
