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
    config: { notify: { position: 'top' } },
  })
  .use(createPinia())
  .use(i18n)
  .use(router)
  .mount('#app')
