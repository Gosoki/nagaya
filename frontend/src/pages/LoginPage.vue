<template>
  <!-- 用普通容器而不是 q-page：登录页没有 QLayout 包着，
       QPage 必须是 QLayout 的后代，否则 Quasar 直接拒绝渲染（整页空白）。 -->
  <div class="login-page column flex-center text-white q-pa-md">
    <!-- 这屋自己的名字和图标也要出现在门口：设置里改完，登录页还挂着
         别人家的「長」字，第一眼就不像自己家的东西。
         名字和图标从**清单**里拿 —— 那个地址不要登录（本来就是给浏览器读的），
         而设置接口要，这儿还没人登录 -->
    <div class="column items-center q-mb-xl">
      <div class="logo">
        <img v-if="logo" :src="logo" class="logo-img" alt="" />
        <template v-else>長</template>
      </div>
      <div class="text-h5 q-mt-md">{{ appName || t('app.name') }}</div>
      <div class="text-caption text-white-7">{{ t('app.tagline') }}</div>
    </div>

    <q-form class="full-width" style="max-width: 360px" @submit="submit">
      <q-input
        v-model="name"
        dark
        filled
        :label="t('login.name')"
        autocomplete="username"
        autocapitalize="off"
        autocorrect="off"
        spellcheck="false"
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
        unelevated
        class="full-width submit"
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
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError } from 'src/api/client'
import { setLang } from 'src/i18n'
import { useAuth } from 'src/stores/auth'

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuth()

/**
 * 门口这块招牌。取自公开的清单（`/api/appearance/manifest.webmanifest`）——
 * 那是给浏览器读的地址，本来就不要登录；而 /api/settings 要，这儿还没人登录。
 * 拉不到就用打包时那套（断网、后端还没起来），门照样要能进。
 */
const appName = ref('')
const logo = ref('')

onMounted(async () => {
  try {
    const res = await fetch('/api/appearance/manifest.webmanifest')
    if (!res.ok) return
    const mf = (await res.json()) as { name?: string; icons?: { src: string }[] }
    appName.value = mf.name ?? ''
    // 自定义图标才换那个「長」字；没设过的话 icons 指的是打包时那几张
    const src = mf.icons?.[0]?.src ?? ''
    if (src.startsWith('/api/appearance/icon/')) logo.value = src.replace('/192.png', '/180.png')
  } catch {
    /* 断网/后端没起来：用打包时那套 */
  }
})

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
    // 只有后端真的说「不认识你」才是密码不对。断网、服务器没起来、500 都不是 ——
    // 原来一律显示「用户名或密码不对」，于是没网的时候人会一遍遍去改密码
    error.value =
      e instanceof ApiError
        ? e.status === 401
          ? t('login.failed')
          : e.text
        : String(e)
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
  /* 品牌色一整面，自上而下压暗一点 —— 深浅色模式下都是它：
     门口就该是这屋自己的颜色，不跟着系统变 */
  background: linear-gradient(170deg, var(--nagaya-brand) 0%, var(--nagaya-brand-deep) 100%);
  min-height: 100vh;
  min-height: 100dvh;          /* 手机浏览器地址栏收起时也铺满 */
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
}
.logo {
  width: 88px;
  height: 88px;
  border-radius: 22px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 54px;
  line-height: 1;
}
.logo-img { width: 88px; height: 88px; object-fit: cover; }
.text-white-7 { opacity: 0.7; }
/* 输入框：一块圆角的半透明白，不要 Quasar filled 底下那条线 */
.login-page :deep(.q-field--filled .q-field__control) {
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.12);
}
.login-page :deep(.q-field--filled .q-field__control::before),
.login-page :deep(.q-field--filled .q-field__control::after) { display: none; }
/* 进门那个按钮：字用品牌藏青，深色模式下主色会被提亮，这里不跟 */
.login-page .submit.text-primary { border-radius: 14px; font-weight: 600; color: var(--nagaya-brand) !important; }
</style>
