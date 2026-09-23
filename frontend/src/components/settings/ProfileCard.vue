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
      <!-- 点头像换图片。**颜色那一排永远留着** —— 它不只是「没照片时的替身」：
           「谁付的」那排按钮选中时用的就是这个颜色，换了照片照样在用 -->
      <q-item class="profile-row">
        <q-item-section avatar>
          <button class="avatar-btn" :aria-label="t('profile.pickPhoto')" @click="pickFile">
            <MemberAvatar :member-id="auth.me.id" size="48px" />
            <q-icon v-if="!uploading" name="photo_camera" size="14px" class="cam" />
            <q-spinner v-else size="14px" class="cam" color="white" />
          </button>
          <!-- 带个类名：这一页上不止一个文件输入（还有「应用图标」那张卡），
               靠「第几个」去指必然会在插卡片时错位 -->
          <input
            ref="fileEl"
            class="hidden avatar-file"
            type="file"
            accept="image/*"
            @change="onFile"
          />
        </q-item-section>
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <div class="col">{{ t('profile.photo') }}</div>
            <q-btn
              v-if="auth.me.avatar"
              dense flat no-caps size="sm" color="grey-7"
              :label="t('profile.removePhoto')"
              @click="removePhoto"
            />
          </q-item-label>
          <q-item-label caption>{{ t('profile.photoHint') }}</q-item-label>
          <div class="swatches q-mt-sm">
            <button
              v-for="c in MEMBER_COLORS"
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
              @blur="saveText('display_name', $event.target as HTMLInputElement)"
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
              @blur="saveText('name', $event.target as HTMLInputElement)"
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
              class="mini-seg"
              :options="[{ label: '中文', value: 'zh' }, { label: '日本語', value: 'ja' }]"
              @update:model-value="(v: string) => save({ lang: v })"
            />
          </q-item-label>
        </q-item-section>
      </q-item>

      <!-- 深浅色、主题色：跟着账号走，换台设备登录还是这一套（src/prefs.ts） -->
      <q-item class="profile-row">
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <div class="col">{{ t('profile.scheme') }}</div>
            <q-btn-toggle
              :model-value="scheme"
              dense unelevated no-caps
              toggle-color="primary"
              class="mini-seg scheme-toggle"
              :options="[
                { label: t('profile.schemeAuto'), value: 'auto' },
                { label: t('profile.schemeLight'), value: 'light' },
                { label: t('profile.schemeDark'), value: 'dark' },
              ]"
              @update:model-value="(v: string) => savePref('scheme', v)"
            />
          </q-item-label>
          <q-item-label caption>{{ t('profile.schemeHint') }}</q-item-label>
        </q-item-section>
      </q-item>

      <!-- 主题色：导航、按钮、链接、选中的颜色。三种账目的颜色不跟它走（src/themeColor.ts） -->
      <q-item class="profile-row">
        <q-item-section>
          <q-item-label>{{ t('profile.themeColor') }}</q-item-label>
          <div class="swatches q-mt-sm">
            <button
              v-for="c in THEME_COLORS"
              :key="c.id"
              class="swatch theme-swatch"
              :class="{ on: themeColor === c.id }"
              :style="{ background: c.light }"
              :aria-label="t(`profile.themeColors.${c.id}`)"
              :aria-pressed="themeColor === c.id"
              :title="t(`profile.themeColors.${c.id}`)"
              @click="savePref('theme_color', c.id)"
            />
          </div>
          <q-item-label caption class="q-mt-xs">{{ t('profile.themeColorHint') }}</q-item-label>
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
          </div>
        </q-item-section>
      </q-item>

      <!-- 只退这一台。token 管 90 天，界面上原来没有任何下车的地方 ——
           借别人手机看过一次账，那台手机就一直是登录状态 -->
      <q-item class="profile-row">
        <q-item-section>
          <q-item-label class="row items-center no-wrap">
            <div class="col">{{ t('profile.logout') }}</div>
            <q-btn dense flat no-caps color="negative" :label="t('profile.logout')" @click="signOut" />
          </q-item-label>
          <q-item-label caption>{{ t('profile.logoutHint') }}</q-item-label>
        </q-item-section>
      </q-item>
    </q-list>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { errorText } from 'src/api/client'
import { schemePref as scheme } from 'src/colorScheme'
import { THEME_COLORS, themeColor } from 'src/themeColor'
import { MEMBER_COLORS } from 'src/palette'
import { setPref } from 'src/prefs'
import { shrinkSquare } from 'src/shrinkImage'
import MemberAvatar from 'src/components/MemberAvatar.vue'
import { useAuth } from 'src/stores/auth'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const router = useRouter()
const auth = useAuth()
const meta = useMeta()

const open = ref(false)
const oldPw = ref('')
const newPw = ref('')
const busy = ref(false)

const fileEl = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

function pickFile() {
  fileEl.value?.click()
}

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''              // 清掉，下次选同一张照片也能再触发 change
  if (!file) return
  uploading.value = true
  try {
    // 先在手机上裁方缩小（后端存的就是 192 的方图），传上去只有十几 KB。
    // 照片多大都行，不用再挡 —— 原来超过 5MB 就拒，而手机拍的动辄七八 MB
    let small: File
    try {
      small = await shrinkSquare(file, 192, 'image/jpeg')
    } catch {
      $q.notify({ type: 'negative', message: t('errors.avatar_not_image'), timeout: 4000 })
      return
    }
    const saved = await auth.uploadAvatar(small)
    meta.members = meta.members.map((m) => (m.id === saved.id ? saved : m))
  } catch (err) {
    $q.notify({ type: 'negative', message: errorText(err), timeout: 5000 })
  } finally {
    uploading.value = false
  }
}

async function removePhoto() {
  try {
    const saved = await auth.removeAvatar()
    meta.members = meta.members.map((m) => (m.id === saved.id ? saved : m))
  } catch (err) {
    $q.notify({ type: 'negative', message: errorText(err), timeout: 5000 })
  }
}

/** 深浅色、主题色。点下去当场换上，再存进账号；存不上就换回去 */
function savePref(key: 'scheme' | 'theme_color', value: string) {
  setPref(key, value).catch((e) => {
    $q.notify({ type: 'negative', message: errorText(e), timeout: 5000 })
  })
}

function toggle() {
  open.value = !open.value
  oldPw.value = ''
  newPw.value = ''
}

async function save(patch: Record<string, unknown>): Promise<boolean> {
  try {
    const saved = await auth.updateMe(patch)
    // 头像和名字全站到处在用（账单、账目、分摊面板），本地那份也得跟上
    meta.members = meta.members.map((m) => (m.id === saved.id ? saved : m))
    return true
  } catch (e) {
    $q.notify({ type: 'negative', message: errorText(e), timeout: 5000 })
    return false
  }
}

/**
 * 失焦即存。**存不上就把框里的字改回服务器那一份。**
 *
 * 这两格是非受控写法（`:value` + `@blur`）：保存被拒时 `auth.me.name` 根本没变，
 * Vue 比对 vnode prop 发现一样就不去 patch DOM —— 用户输的那串字于是一直留在
 * 屏幕上，看着像是存上了。而登录名是唯一没有自救手段的凭据：记错了，
 * 换台设备就进不来。清空后失焦原来更静，一句话都没有。
 */
async function saveText(field: 'name' | 'display_name', el: HTMLInputElement) {
  const value = el.value.trim()
  const current = auth.me?.[field] ?? ''
  if (!value) {
    el.value = current
    $q.notify({ type: 'warning', message: t('errors.name_required'), timeout: 3000 })
    return
  }
  if (value === current) {
    el.value = current                      // 只是首尾多敲了空格
    return
  }
  if (!(await save({ [field]: value }))) el.value = auth.me?.[field] ?? ''
}

/** 只退这一台。换人用、或者借别人手机看过账，得有地方下车 */
function signOut() {
  $q.dialog({
    title: t('profile.logout'),
    message: t('profile.logoutConfirm'),
    cancel: true,
    ok: { label: t('profile.logout'), color: 'negative', flat: true },
  }).onOk(() => {
    auth.logout()
    meta.forget()          // 上一位的成员/分类/设置别留给下一位
    void router.push({ name: 'login' })
  })
}

/**
 * 改密码。**两步必须分开报错** —— 它们的含义正好相反：
 *   第一步失败 ＝ 密码**没改**（旧密码填错之类），原样报出来就行；
 *   第二步失败 ＝ 密码**已经改了**、手里这张 token 也作废了，只是没换到新的。
 * 原来两步共用一句 `e.text`，于是第二步失败时人看到的是一句错误提示，
 * 转身拿**旧密码**去重登 —— 而旧密码已经不作数了。
 */
async function savePassword() {
  busy.value = true
  const fresh = newPw.value
  const who = auth.me!.name
  try {
    await auth.updateMe({ password: fresh, old_password: oldPw.value })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorText(e), timeout: 5000 })
    busy.value = false
    return
  }
  try {
    // 改完密码手里这张 token 就作废了（后端按密码指纹认 session，
    // 改密码就是为了把别的设备踢下去）。用新密码当场换一张，别把自己也踢出去
    await auth.login(who, fresh)
    toggle()
    $q.notify({ type: 'positive', message: t('profile.passwordChanged'), timeout: 2000 })
  } catch {
    // 先 logout 再跳：路由守卫看到 localStorage 里还有那张死 token 会把 /login
    // 改道回首页，人就一直卡在一个假的已登录界面里
    auth.logout()
    $q.notify({
      type: 'warning',
      timeout: 0,
      multiLine: true,
      message: t('profile.passwordChangedRelogin'),
      actions: [{ label: t('common.confirm'), color: 'white' }],
    })
    void router.push({ name: 'login' })
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.profile-row { padding-top: 8px; padding-bottom: 8px; }
/* 头像按钮：右下角压一个小相机，告诉人这儿点得动 */
.avatar-btn {
  position: relative;
  border: none;
  background: none;
  padding: 0;
  cursor: pointer;
  line-height: 0;
}
.cam {
  position: absolute;
  right: -2px;
  bottom: -2px;
  background: var(--q-primary);
  color: #fff;
  border: 2px solid var(--nagaya-surface);
  border-radius: 50%;
  padding: 3px;
  box-sizing: content-box;
}
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
  box-shadow: 0 0 0 2px var(--nagaya-surface) inset, 0 0 0 2px var(--nagaya-ink-2);
}
.field {
  height: 36px;
  border: none;
  border-radius: var(--nagaya-r-sm);
  outline: none;
  background: var(--nagaya-fill);
  font: inherit;
  font-size: 16px;           /* 16 是 iOS 的底线：再小一点，聚焦时整页会被放大 */
  color: inherit;
  padding: 0 10px;
  text-align: right;
  width: 150px;
}
.field:focus { box-shadow: inset 0 0 0 1.5px var(--nagaya-accent); }
.field.full { width: 100%; text-align: left; }
</style>
