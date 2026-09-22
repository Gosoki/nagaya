<!--
  这屋的 App 叫什么、图标长什么样。

  **为什么值得有这一屏**：这东西是自托管的，一户一个实例。加到手机主屏之后，
  图标和名字就是「这是哪个屋的账本」的全部标识 —— 默认那个「長」字对
  住在長屋 的人合适，对别人不合适，而改它本来要去改代码再重新打包一次。

  名字和「有没有自定义图标」两项走的是普通设置（跟着备份一起走）；
  图标本体存在后端库里，也跟着备份走。
-->
<template>
  <div class="bill-section">
    <!-- 默认收起来：名字和图标是「定一次就不再动」的东西，
         而设置页天天要来的是上面的个人设置。收起时右边显示当前叫什么 -->
    <q-item clickable dense class="section-head" @click="open = !open">
      <q-item-section>{{ t('appearance.title') }}</q-item-section>
      <q-item-section side class="text-caption text-grey-6 ellipsis">
        {{ name || t('appearance.namePlaceholder') }}
      </q-item-section>
      <q-item-section side>
        <q-icon :name="open ? 'expand_less' : 'expand_more'" color="grey-5" size="20px" />
      </q-item-section>
    </q-item>

    <q-item v-if="open" class="profile-row">
      <q-item-section avatar>
        <!-- 点它换图。和换头像一个手势，这一页上两处别是两套 -->
        <button class="icon-btn" :aria-label="t('appearance.pick')" @click="pickFile">
          <img v-if="iconUrl" :src="iconUrl" class="icon-img" alt="" />
          <q-icon v-else name="apps" size="26px" class="text-grey-6" />
          <q-icon v-if="!busy" name="photo_camera" size="14px" class="cam" />
          <q-spinner v-else size="14px" class="cam" color="white" />
        </button>
        <input ref="fileEl" class="hidden icon-file" type="file" accept="image/*" @change="onFile" />
      </q-item-section>
      <q-item-section>
        <q-item-label class="row items-center no-wrap">
          <div class="col">{{ t('appearance.icon') }}</div>
          <q-btn
            v-if="iconUrl"
            dense flat no-caps size="sm" color="grey-7"
            :label="t('appearance.removeIcon')"
            @click="removeIcon"
          />
        </q-item-label>
        <q-item-label caption>{{ t('appearance.iconHint') }}</q-item-label>
      </q-item-section>
    </q-item>

    <q-item v-if="open" class="profile-row">
      <q-item-section>
        <q-item-label class="row items-center no-wrap">
          <div class="col">{{ t('appearance.name') }}</div>
          <input
            class="field"
            type="text"
            maxlength="20"
            :value="name"
            :placeholder="t('appearance.namePlaceholder')"
            @blur="saveName($event.target as HTMLInputElement)"
          />
        </q-item-label>
      </q-item-section>
    </q-item>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, api } from 'src/api/client'
import { applyAppearance, iconSrc } from 'src/appearance'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()

const fileEl = ref<HTMLInputElement | null>(null)
const busy = ref(false)
const open = ref(false)

const name = computed(() => meta.setting<string>('app_name', ''))
const iconVersion = computed(() => meta.setting<number>('app_icon_version', 0))
const iconUrl = computed(() => (iconVersion.value ? iconSrc(180, iconVersion.value) : ''))

function pickFile() {
  fileEl.value?.click()
}

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''            // 同一张图再选一次也要能触发 change
  if (!file) return
  busy.value = true
  try {
    await api.upload<{ version: number }>('/api/appearance/icon', file)
    await after()
  } catch (err) {
    $q.notify({ type: 'negative', message: err instanceof ApiError ? err.text : String(err), timeout: 5000 })
  } finally {
    busy.value = false
  }
}

async function removeIcon() {
  busy.value = true
  try {
    await api.del('/api/appearance/icon')
    await after()
  } catch (err) {
    $q.notify({ type: 'negative', message: err instanceof ApiError ? err.text : String(err), timeout: 5000 })
  } finally {
    busy.value = false
  }
}

async function saveName(el: HTMLInputElement) {
  const value = el.value.trim()
  if (value === name.value) return
  try {
    await api.put('/api/settings/app_name', { value })
    await after()
  } catch (err) {
    // 存不上就把框里的字改回服务器那一份 —— 非受控输入，不写回的话
    // 屏幕上留着一个服务器从没接受过的名字
    el.value = name.value
    $q.notify({ type: 'negative', message: err instanceof ApiError ? err.text : String(err), timeout: 5000 })
  }
}

/** 改完当场生效：页签标题、页签小图、主屏清单，不用等下次开 App */
async function after() {
  await meta.load()
  applyAppearance(meta.setting<string>('app_name', ''), meta.setting<number>('app_icon_version', 0))
}
</script>

<style scoped>
.icon-btn {
  position: relative;
  width: 48px;
  height: 48px;
  padding: 0;                 /* <button> 自带 2px 6px 3px：不清掉，48px 的图会被挤出内容盒，整块偏右下 */
  border: none;
  border-radius: var(--nagaya-r-md);
  background: var(--nagaya-fill);
  display: grid;
  place-items: center;
  cursor: pointer;
  overflow: visible;
}
.icon-img {
  width: 48px;
  height: 48px;
  border-radius: var(--nagaya-r-md);
  object-fit: cover;
}
/* 相机角标压在右下角，和换头像那个一模一样 */
.cam {
  position: absolute;
  right: -4px;
  bottom: -4px;
  padding: 3px;
  border-radius: 50%;
  background: var(--nagaya-accent);
  color: #fff;
}
/* 和「个人」那几个可填的框一套写法：固定宽 + 一条底线。
   原来写的是 flex:1 —— 旁边的标签是 Quasar 的 .col（flex-grow 10000），
   剩余空间按 1:10000 分，这个框实际宽度约等于 0，又没底线，屏幕上就没了 */
.field {
  width: 150px;
  border: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.18);
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 16px;           /* 16 是 iOS 的底线：再小一点，聚焦时整页会被放大 */
  color: inherit;
  text-align: right;
  padding: 2px 2px 0;
}
.field::placeholder { color: var(--nagaya-ink-4); }
</style>
