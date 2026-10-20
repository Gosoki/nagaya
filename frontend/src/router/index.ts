import { Notify } from 'quasar'
import { createRouter, createWebHistory } from 'vue-router'

import { getToken, setUnauthorizedHandler } from 'src/api/client'
import { i18n } from 'src/i18n'
import { applyUpdateIfReady, entryChanged } from 'src/update'

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
        // 账单两页（未出账/已出账）**共用这一个地址**，点页签只换状态不换 URL。
        // :statementId 只是个入口：从账目或固定费屏点进某一张时带着它进来，
        // 页面收下之后会把地址 replace 回 /bill
        { path: 'bill/:statementId?', name: 'bill', component: () => import('src/pages/BillPage.vue') },
      ],
    },
    // 对不上的地址（手打错了、早就撤掉的旧页面）回首页。后端对所有不带后缀的路径都回 index.html，
    // 不兜的话这里什么都不渲染 —— 主屏模式下没有地址栏，整页空白、连底栏都没有，只能杀掉重开
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  // 没登录就去登录页，**记着本来要去哪**：群里贴的账单链接点开是登录页，
  // 登录完应该回到那张账单，而不是落在记一笔
  if (to.name !== 'login' && !getToken()) {
    return to.fullPath === '/' ? { name: 'login' } : { name: 'login', query: { next: to.fullPath } }
  }
  if (to.name === 'login' && getToken()) return { name: 'add' }
  return true
})

setUnauthorizedHandler(() => {
  // 已经在登录页（输错密码也是 401）就别再跳：跳一次会把 ?next= 冲掉，
  // 群里贴的账单链接点开、输错一次密码，登录完就回不到那张账单了
  const here = router.currentRoute.value
  if (here.name === 'login') return
  // **记着本来在哪**（和上面守卫同一个做法）：token 过期、改密码被踢下线，这条路常走 ——
  // 人多半正点开群里那张账单，登录完却落在记一笔，那张单子就找不回来了
  void router.push(here.fullPath === '/' ? { name: 'login' } : { name: 'login', query: { next: here.fullPath } })
})

/**
 * 页面是懒加载的：新版发布后，还开着的旧页面点 Tab 会去取一个已经被删掉的 chunk，
 * 动态 import 抛错、导航被 reject —— 界面上就是**点了没反应**，没有任何提示。
 *
 * 这时唯一正确的动作是重新加载：index.html 是 no-cache 的，刷一下就拿到新版。
 * 加个标记防止「刷了还是失败」时无限循环。
 */
const RELOADED = 'nagaya.reloadedForChunk'
// 「Unable to preload CSS」是 Vite 先等页面的 CSS 那一步失败时抛的 —— 每个页面都带 CSS，
// 第一下失败的总是它。原来认不出，于是发版后第一次点页签照样没反应
const CHUNK_FAILED = /dynamically imported module|Importing a module script failed|Failed to fetch|Unable to preload CSS/i
router.onError((err) => {
  if (!CHUNK_FAILED.test(String(err))) return
  void (async () => {
    // **断网和「版本旧了」报的是同一句错**，先问服务器一声：
    //   取不到 → 断网。别刷新：局域网 http 下没有 SW 兜底，刷出来就是浏览器的断网页，
    //            屏幕上没存的输入全丢，「断了网照样能存草稿」那条路也就断了。说一句就好
    //   入口没变 → 偶发失败，再点一下就行，不刷
    //   入口变了 → 这一页真是旧版，旧 chunk 已经没了，刷
    const changed = await entryChanged()
    if (changed === null) {
      Notify.create({ type: 'negative', message: i18n.global.t('errors.network') })
      return
    }
    if (!changed) return
    try {
      if (sessionStorage.getItem(RELOADED)) return    // 已经刷过一次还不行，别再刷
      sessionStorage.setItem(RELOADED, '1')
    } catch {
      // 存不了就没法防「刷了还是失败」的死循环 —— 那就干脆不自动刷
      return
    }
    location.reload()
  })()
})
router.afterEach((to) => {
  try {
    sessionStorage.removeItem(RELOADED)             // 成功导航过就把标记清掉
  } catch {
    /* ignore */
  }
  // 有新版等着就趁这次切页换上（切页本来就丢当前页的状态，不额外丢东西）
  applyUpdateIfReady(to.fullPath)
})
