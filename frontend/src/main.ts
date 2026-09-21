import { Quasar, Notify } from 'quasar'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'

import App from './App.vue'
import { i18n } from './i18n'
import { router } from './router'

createApp(App)
  .use(Quasar, { plugins: { Notify }, config: { notify: { position: 'top' } } })
  .use(createPinia())
  .use(i18n)
  .use(router)
  .mount('#app')
