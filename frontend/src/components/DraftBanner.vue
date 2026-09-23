<!-- 没提交的草稿横幅。压在页面顶部，点一下补交。 -->
<template>
  <!-- 颜色和离线那条细带同一套（--nagaya-warn*）：原来是琥珀底白字，对比度 2.6:1，
       太阳底下看不清；深色模式下也不跟着变 -->
  <q-banner v-if="drafts.count" dense class="draft-banner">
    <template #avatar>
      <q-icon name="cloud_off" />
    </template>
    {{ t('draft.pending', { n: drafts.count }) }}
    <template #action>
      <q-btn flat dense no-caps :loading="busy" :label="t('draft.submit')" @click="submit" />
      <q-btn flat dense no-caps :disable="busy" :label="t('draft.discard')" @click="discard" />
    </template>
  </q-banner>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { escapeHtml } from 'src/html'
import { useDrafts } from 'src/stores/drafts'
import { useLedger } from 'src/stores/ledger'

const { t } = useI18n()
const $q = useQuasar()
const drafts = useDrafts()
const ledger = useLedger()
const busy = ref(false)


async function submit() {
  busy.value = true
  try {
    const { ok, offline, rejected } = await drafts.submitAll()
    if (ok) await ledger.refresh().catch(() => {})
    // 被后端明确拒绝的，把它那句话原样说出来 —— 那条草稿会一直卡在这儿，
    // 而「连不上服务器」既是错的，也不告诉人该去改哪儿
    if (rejected.length) {
      // 一行一条，还要说清是几条。Quasar 的 message 是纯文本节点，`\n` 在 HTML 里
      // 折叠成一个空格 —— 几句原因于是挤成一长串，看不出是几笔、哪笔。
      // 同一个原因的多条草稿也别重复说，数出来更清楚
      const times = new Map<string, number>()
      for (const text of rejected) times.set(text, (times.get(text) ?? 0) + 1)
      $q.notify({
        type: 'negative',
        timeout: 8000,
        multiLine: true,
        html: true,
        message: [...times]
          .map(([text, n]) => escapeHtml(n > 1 ? t('draft.rejectedTimes', { text, n }) : text))
          .join('<br>'),
      })
    } else if (offline) {
      $q.notify({ type: 'negative', message: t('errors.network') })
    } else if (ok) {
      $q.notify({ type: 'positive', message: t('entry.saved'), timeout: 1200 })
    }
  } finally {
    busy.value = false
  }
}

function discard() {
  $q.dialog({ title: t('draft.discard'), message: t('draft.pending', { n: drafts.count }), cancel: true })
    .onOk(() => drafts.clear())
}
</script>

<style scoped>
/* 安全区由顶栏统一让（MainLayout），这里再让一次就是让两遍 */
</style>

<style scoped>
.draft-banner {
  background: var(--nagaya-warn-bg);
  color: var(--nagaya-warn);
}
.draft-banner :deep(.q-btn) { color: var(--nagaya-warn); font-weight: 600; }
</style>
