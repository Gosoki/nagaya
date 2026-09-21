<template>
  <!-- 用普通容器而不是 q-page：登录页没有 QLayout 包着，
       QPage 必须是 QLayout 的后代，否则 Quasar 直接拒绝渲染（整页空白）。 -->
  <div class="login-page column flex-center bg-primary text-white q-pa-md">
    <div class="column items-center q-mb-xl">
      <div class="logo">長</div>
      <div class="text-h5 q-mt-md">{{ t('app.name') }}</div>
      <div class="text-caption text-white-7">{{ t('app.tagline') }}</div>
    </div>

    <q-form class="full-width" style="max-width: 360px" @submit="submit">
      <q-input
        v-model="name"
        dark
        filled
        :label="t('login.name')"
        autocomplete="username"
        class="q-mb-md"
      />
      <q-input
        v-model="password"
        dark
        filled
        type="password"
        :label="t('login.password')"
        autocomplete="current-password"
        class="q-mb-lg"
      />
      <q-btn
        type="submit"
        color="white"
        text-color="primary"
        class="full-width"
        size="lg"
        no-caps
        :loading="busy"
        :label="t('login.submit')"
      />
      <div v-if="error" class="text-center q-mt-md text-yellow-3">{{ error }}</div>
    </q-form>

    <q-btn flat dense no-caps class="q-mt-xl text-white-7" @click="toggleLang">
      {{ locale === 'zh' ? '日本語' : '中文' }}
    </q-btn>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError } from 'src/api/client'
import { setLang } from 'src/i18n'
import { useAuth } from 'src/stores/auth'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuth()

const name = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await auth.login(name.value, password.value)
    await router.push({ name: 'add' })
  } catch (e) {
    error.value = e instanceof ApiError ? t('login.failed') : String(e)
  } finally {
    busy.value = false
  }
}

function toggleLang() {
  setLang(locale.value === 'zh' ? 'ja' : 'zh')
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  min-height: 100dvh;          /* 手机浏览器地址栏收起时也铺满 */
  padding-bottom: env(safe-area-inset-bottom);
}
.logo {
  width: 88px;
  height: 88px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 54px;
  line-height: 1;
}
.text-white-7 { opacity: 0.7; }
</style>
