import { Dialog, Notify, Quasar } from 'quasar'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
// **必须排在 quasar 之后**：里面有几条覆盖 Quasar 灰阶工具类的规则，
// 两边都带 !important，靠 import 顺序决胜
import './css/tokens.css'

import App from './App.vue'
import { detectLang, i18n, quasarLang } from './i18n'
import { router } from './router'

createApp(App)
  // 不给 lang 的话所有弹框的按钮都是英文的 CANCEL / OK，
  // 夹在一屏中文里格外扎眼。切日语时 setLang() 会跟着换
  .use(Quasar, {
    plugins: { Notify, Dialog },
    lang: quasarLang(detectLang()),
    // 提示走屏幕下方：顶上那条会被刘海/灵动岛切掉半截，而「记好了」这种话
    // 看不全等于没提示。具体离底边多高由 CSS 定（要躲开底栏和固定操作条）
    config: { notify: { position: 'bottom' } },
  })
  .use(createPinia())
  .use(i18n)
  .use(router)
  .mount('#app')
