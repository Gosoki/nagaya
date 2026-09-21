<!-- 外壳：内容在上，导航在下。
     主操作一律放屏幕下半部的拇指区（SPEC §7.4），顶部只放不常点的东西。 -->
<template>
  <q-layout view="hHh lpR fFf">
    <q-header v-if="drafts.count" class="bg-transparent">
      <DraftBanner />
    </q-header>

    <q-page-container>
      <router-view v-if="meta.members.length" />
      <div v-else class="column flex-center" style="height: 60vh">
        <q-spinner-dots size="40px" color="primary" />
      </div>
    </q-page-container>

    <q-footer class="bg-white text-grey-8 footer-safe">
      <!-- 必须是 q-route-tab：q-tab 不认 :to，点了不会导航也不报错 -->
      <q-tabs
        dense
        no-caps
        indicator-color="transparent"
        active-color="primary"
        class="text-grey-6"
      >
        <q-route-tab
          :to="{ name: 'add' }"
          exact
          icon="add_circle"
          :label="t('nav.add')"
        />
        <q-route-tab
          :to="{ name: 'bill' }"
          icon="receipt"
          :label="t('nav.bill')"
        />
        <q-route-tab
          :to="{ name: 'entries' }"
          icon="receipt_long"
          :label="t('nav.entries')"
        />
      </q-tabs>
    </q-footer>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import DraftBanner from 'src/components/DraftBanner.vue'
import { useAuth } from 'src/stores/auth'
import { useDrafts } from 'src/stores/drafts'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const meta = useMeta()
const auth = useAuth()
const ledger = useLedger()
const drafts = useDrafts()

onMounted(async () => {
  if (!auth.me) await auth.restore()
  await meta.load()
  await ledger.refresh()
})
</script>

<style scoped>
/* 刘海屏/手势条：底栏内缩到安全区以内，否则最后一个 tab 会被手势条压住 */
.footer-safe {
  padding-bottom: env(safe-area-inset-bottom);
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
</style>
