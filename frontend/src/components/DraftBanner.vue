<!-- 没提交的草稿横幅。压在页面顶部，点一下补交。 -->
<template>
  <q-banner v-if="drafts.count" dense class="bg-warning text-white draft-banner">
    <template #avatar>
      <q-icon name="cloud_off" />
    </template>
    {{ t('draft.pending', { n: drafts.count }) }}
    <template #action>
      <q-btn flat dense no-caps :loading="busy" :label="t('draft.submit')" @click="submit" />
      <q-btn flat dense no-caps :label="t('draft.discard')" @click="discard" />
    </template>
  </q-banner>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

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
      $q.notify({ type: 'negative', timeout: 8000, message: rejected.join('\n') })
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
.draft-banner { padding-top: env(safe-area-inset-top); }
</style>
