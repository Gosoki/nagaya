<!--
  个人设置 —— 「设置」那一页的第一块。
  上面那块是三个人共用的规矩，这一块只关自己：头像色、昵称、登录名、语言、密码。

  语言原来**只有登录页上有得换**，登录之后就再也找不到了。
-->
<template>
  <div v-if="auth.me" class="bill-section">
    <q-item dense class="section-head">
      <q-item-section>{{ t('profile.title') }}</q-item-section>
    </q-item>

    <q-list separator>
      <!-- 头像：这个 App 的头像就是一个带首字的色圆，所以「换头像」＝换颜色 -->
      <q-item class="profile-row">
        <q-item-section avatar>
          <q-avatar size="40px" :style="{ background: auth.me.color }" text-color="white">
            {{ auth.me.display_name.slice(0, 1) }}
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ t('profile.color') }}</q-item-label>
          <div class="swatches q-mt-xs">
            <button
              v-for="c in COLORS"
              :key="c"
              class="swatch"
              :class="{ on: auth.me.color.toLowerCase() === c }"
              :style="{ background: c }"
              :aria-label="c"
              @click="save({ color: c })"
            />
          </div>
        </q-item-section>
      </q-item>

      <q-item class="profile-row">
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <div class="col">{{ t('profile.displayName') }}</div>
            <input
              class="field"
              type="text"
              maxlength="20"
              :value="auth.me.display_name"
              @blur="saveText('display_name', ($event.target as HTMLInputElement).value)"
            />
          </q-item-label>
          <q-item-label caption>{{ t('profile.displayNameHint') }}</q-item-label>
        </q-item-section>
      </q-item>

      <q-item class="profile-row">
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <div class="col">{{ t('profile.loginName') }}</div>
            <input
              class="field"
              type="text"
              maxlength="20"
              autocapitalize="off"
              :value="auth.me.name"
              @blur="saveText('name', ($event.target as HTMLInputElement).value)"
            />
          </q-item-label>
          <q-item-label caption>{{ t('profile.loginNameHint') }}</q-item-label>
        </q-item-section>
      </q-item>

      <q-item class="profile-row">
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <div class="col">{{ t('profile.lang') }}</div>
            <q-btn-toggle
              :model-value="auth.me.lang"
              dense unelevated no-caps
              toggle-color="primary"
              :options="[{ label: '中文', value: 'zh' }, { label: '日本語', value: 'ja' }]"
              @update:model-value="(v: string) => save({ lang: v })"
            />
          </q-item-label>
        </q-item-section>
      </q-item>

      <q-item class="profile-row">
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <div class="col">{{ t('profile.password') }}</div>
            <q-btn
              dense flat no-caps color="primary"
              :label="open ? t('common.cancel') : t('profile.change')"
              @click="toggle"
            />
          </q-item-label>
          <div v-if="open" class="q-mt-sm">
            <input
              v-model="oldPw"
              class="field full"
              type="password"
              autocomplete="current-password"
              :placeholder="t('profile.oldPassword')"
            />
            <input
              v-model="newPw"
              class="field full q-mt-sm"
              type="password"
              autocomplete="new-password"
              :placeholder="t('profile.newPassword')"
            />
            <q-btn
              class="q-mt-sm"
              dense unelevated no-caps color="primary"
              :disable="!oldPw || newPw.length < 6"
              :loading="busy"
              :label="t('common.save')"
              @click="savePassword"
            />
            <div class="text-caption text-grey-6 q-mt-xs">{{ t('profile.passwordHint') }}</div>
          </div>
        </q-item-section>
      </q-item>
    </q-list>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from 'src/api/client'
import { useAuth } from 'src/stores/auth'
import { useMeta } from 'src/stores/meta'

/** 头像色候选。够分得开就行 —— 三个人要一眼认出谁是谁 */
const COLORS = [
  '#3d4785', '#26a69a', '#ef6c00', '#c62828', '#6a1b9a',
  '#00838f', '#2e7d32', '#ad1457', '#4e342e', '#455a64',
]

const { t } = useI18n()
const $q = useQuasar()
const auth = useAuth()
const meta = useMeta()

const open = ref(false)
const oldPw = ref('')
const newPw = ref('')
const busy = ref(false)

function toggle() {
  open.value = !open.value
  oldPw.value = ''
  newPw.value = ''
}

async function save(patch: Record<string, unknown>) {
  try {
    const saved = await auth.updateMe(patch)
    // 头像和名字全站到处在用（账单、账目、分摊面板），本地那份也得跟上
    meta.members = meta.members.map((m) => (m.id === saved.id ? saved : m))
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
  }
}

function saveText(field: 'name' | 'display_name', raw: string) {
  const value = raw.trim()
  if (!value || value === auth.me?.[field]) return
  void save({ [field]: value })
}

async function savePassword() {
  busy.value = true
  try {
    await auth.updateMe({ password: newPw.value, old_password: oldPw.value })
    toggle()
    $q.notify({ type: 'positive', message: t('profile.passwordChanged'), timeout: 2000 })
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.profile-row { padding-top: 8px; padding-bottom: 8px; }
.swatches { display: flex; flex-wrap: wrap; gap: 8px; }
.swatch {
  width: 30px;
  height: 30px;
  border-radius: 15px;
  border: 2px solid transparent;
  padding: 0;
  cursor: pointer;
}
/* 选中的那个：外面套一圈底色的环，深色浅色上都看得见 */
.swatch.on {
  box-shadow: 0 0 0 2px #fff inset, 0 0 0 2px rgba(0, 0, 0, 0.55);
}
.field {
  border: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.18);
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 15px;            /* 低于 16px iOS 聚焦时会放大整页 */
  color: inherit;
  padding: 2px 2px 0;
  text-align: right;
  width: 150px;
}
.field.full { width: 100%; text-align: left; }
</style>
