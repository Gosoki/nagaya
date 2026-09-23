<!--
  添加到主屏幕 —— 设置页最底下那一块。点开就是这台手机、这个浏览器该怎么点。

  从主屏打开的那份 app 里也照样列着：标「已添加」，内容换成「给别的手机加」——
  拿着自己的手机教室友是最常见的用法。
-->
<template>
  <div class="bill-section">
    <q-item clickable dense class="section-head" @click="open = !open">
      <q-item-section>{{ t('install.title') }}</q-item-section>
      <q-item-section v-if="standalone" side class="text-caption text-grey-6">{{ t('install.done') }}</q-item-section>
      <q-item-section side>
        <q-icon :name="open ? 'expand_less' : 'expand_more'" color="grey-5" size="20px" />
      </q-item-section>
    </q-item>

    <div v-if="open" class="guide q-px-md q-pb-md">
      <div class="text-caption text-grey-7 q-mb-sm">{{ standalone ? t('install.already') : t('install.why') }}</div>

      <div v-for="g in groups" :key="g.key" class="group">
        <div v-if="groups.length > 1" class="group-title">{{ t(`install.${g.key}`) }}</div>
        <ol class="steps">
          <li v-for="(s, i) in g.steps" :key="s" class="row no-wrap">
            <span class="num">{{ i + 1 }}</span>
            <span class="col">{{ t(`install.${s}`) }}</span>
          </li>
        </ol>
      </div>

      <!-- 地址：在电脑上看到这一屏、或者要念给室友听的时候用。长按就能复制 -->
      <div v-if="standalone || platform === 'other'" class="address row items-center no-wrap">
        <span class="text-grey-7 q-mr-sm">{{ t('install.address') }}</span>
        <span class="col url">{{ origin }}</span>
      </div>

      <div class="notes text-caption text-grey-7">
        <div v-if="showLoginNote">{{ t('install.noteLogin') }}</div>
        <div>{{ t('install.noteName') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { installPlatform, isStandalone } from 'src/installGuide'

const { t } = useI18n()

const open = ref(false)
const standalone = isStandalone()
const platform = installPlatform(navigator.userAgent, navigator.maxTouchPoints)
const origin = window.location.origin

const IOS = ['iosSafari1', 'iosSafari2', 'iosSafari3']
const ANDROID = ['android1', 'android2']

/**
 * 列哪几组步骤。认得出是哪种浏览器就只给那一种；
 * 已经在主屏上、或者在电脑上看的，iPhone 和安卓两组都给（是给别的手机看的）
 */
const groups = computed(() => {
  if (standalone || platform === 'other') {
    return [
      { key: 'iphone', steps: IOS },
      { key: 'android', steps: ANDROID },
    ]
  }
  const steps = {
    'ios-safari': IOS,
    'ios-other': ['iosOther1', 'iosOther2', 'iosSafari3'],
    'in-app': ['inApp1', 'inApp2'],
    android: ANDROID,
  }[platform]
  return [{ key: platform, steps }]
})

/** 「从主屏打开要再登录一次」只有 iPhone 上是这样（主屏的 app 和 Safari 各存各的） */
const showLoginNote = computed(
  () => standalone || platform === 'other' || platform === 'ios-safari' || platform === 'ios-other',
)
</script>

<style scoped>
.group + .group { margin-top: 12px; }
.group-title { font-weight: 600; margin-bottom: 6px; }
.steps { list-style: none; margin: 0; padding: 0; }
.steps li { gap: 10px; padding: 4px 0; line-height: 1.5; }
.num {
  flex: none;
  width: 22px;
  height: 22px;
  margin-top: 1px;
  border-radius: 11px;
  background: var(--nagaya-accent-bg);
  color: var(--nagaya-accent);
  font-size: var(--nagaya-fs-meta);
  font-weight: 600;
  line-height: 22px;
  text-align: center;
}
.address {
  margin-top: 12px;
  padding: 8px 10px;
  border-radius: var(--nagaya-r-sm);
  background: var(--nagaya-fill);
  font-size: var(--nagaya-fs-label);
}
.url { user-select: all; -webkit-user-select: all; word-break: break-all; }
.notes { margin-top: 12px; line-height: 1.5; }
.notes > div + div { margin-top: 4px; }
</style>
