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
import { installThemeColor } from './themeColor'
import { watchForUpdate } from './update'
import { detectLang, i18n, quasarLang } from './i18n'
import { router } from './router'

// 新版 service worker 接管之后什么时候换页面：见 src/update.ts
watchForUpdate()

const app = createApp(App)
  // 不给 lang 的话所有弹框的按钮都是英文的 CANCEL / OK，
  // 夹在一屏中文里格外扎眼。切日语时 setLang() 会跟着换
  .use(Quasar, {
    plugins: { Notify, Dialog, Dark },
    lang: quasarLang(detectLang()),
    // 提示走屏幕**上方**：下方一打字就被输入法盖住 —— 记完一笔键盘多半还开着，
    // 「已记下」正好落在键盘底下，跟没提示一样。顶上那条要躲开刘海/灵动岛和顶栏，
    // 具体离顶边多高由 CSS 定（tokens.css，量出来的顶栏高度）
    config: { notify: { position: 'top' } },
  })

/**
 * 弹框的按钮和勾选框一律用主色。Quasar 的对话框插件在深色模式下默认换成
 * 琥珀色 —— 「确定」一片黄，看着像警告。插件没有全局默认色的配置，
 * 只能在它装好之后包一层（useQuasar() 拿到的是同一个 $q）
 */
const $q = app.config.globalProperties.$q
const plainDialog = $q.dialog
$q.dialog = (opts) => plainDialog({ color: 'primary', ...opts })

app.use(createPinia()).use(i18n).use(router).mount('#app')

installColorScheme()
installThemeColor()
