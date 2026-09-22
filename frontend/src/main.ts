import { Dark, Dialog, Notify, Quasar } from 'quasar'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
// **必须排在 quasar 之后**：里面有几条覆盖 Quasar 灰阶工具类的规则，
// 两边都带 !important，靠 import 顺序决胜
import './css/tokens.css'
import './css/skin.css'

import App from './App.vue'
import { installColorScheme } from './colorScheme'
import { detectLang, i18n, quasarLang } from './i18n'
import { router } from './router'

/**
 * 新版 service worker 一接管就整页重载。
 *
 * SW 里写了 skipWaiting + clientsClaim，新版会立刻上岗 —— 但**已经打开的这一页
 * 仍然跑着旧 JS**，要等下一次导航才换。装到主屏之后尤其要命：从多任务里恢复
 * 不算一次导航，人可能连着好几天看的都是旧界面，改了什么都看不到。
 *
 * 首装那一次不重载：那时页面本来就是新的，刷一下纯属白闪。
 */
const hadController = Boolean(navigator.serviceWorker?.controller)
let reloading = false
navigator.serviceWorker?.addEventListener('controllerchange', () => {
  if (!hadController || reloading) return
  reloading = true
  location.reload()
})

createApp(App)
  // 不给 lang 的话所有弹框的按钮都是英文的 CANCEL / OK，
  // 夹在一屏中文里格外扎眼。切日语时 setLang() 会跟着换
  .use(Quasar, {
    plugins: { Notify, Dialog, Dark },
    lang: quasarLang(detectLang()),
    // 提示走屏幕下方：顶上那条会被刘海/灵动岛切掉半截，而「记好了」这种话
    // 看不全等于没提示。具体离底边多高由 CSS 定（要躲开底栏和固定操作条）
    config: { notify: { position: 'bottom' } },
  })
  .use(createPinia())
  .use(i18n)
  .use(router)
  .mount('#app')

installColorScheme()
