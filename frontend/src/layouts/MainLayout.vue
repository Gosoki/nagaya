<!-- 外壳：内容在上，导航在下。
     主操作一律放屏幕下半部的拇指区（SPEC §7.4），顶部只放不常点的东西。 -->
<template>
  <q-layout view="hHh lpR fFf">
    <!-- 顶栏固定在布局上，不放进页面里：账单三页之间切换时它不该跟着卸载重建，
         切页只换中间那块内容，上下两条都不动 -->
    <q-header v-if="drafts.count || onBillTabs" class="bg-white text-dark">
      <DraftBanner v-if="drafts.count" />
      <BillTabs v-if="onBillTabs" />
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

import { computed } from 'vue'
import { useRoute } from 'vue-router'

import BillTabs from 'src/components/BillTabs.vue'
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
const route = useRoute()

/** 账单那三页才显示页签。从「以前」点进某一张（/bill/3）时换成返回条，不算 */
const onBillTabs = computed(
  () =>
    (route.name === 'bill' && !route.params.statementId) ||
    route.name === 'bill-current' ||
    route.name === 'bill-past',
)

onMounted(async () => {
  if (!auth.me) await auth.restore()
  await meta.load()
  await ledger.refresh()
})
</script>

<!-- 非 scoped：底栏高度给固定操作条用。
     两个页面都曾把它写死成 50px，而实际是 57px（56 tabs + 1 border），
     于是主操作按钮和 Tab 只隔 1px，拇指偏一点就点错。 -->
<style>
:root {
  --nagaya-footer-h: 57px;
  /* 手机是主场。平板/电脑上不收一下的话，列表会被拉成「名字贴最左、
     数字贴最右」中间一片空白 —— 收到一个手机宽度居中，全站一致 */
  --nagaya-max-w: 480px;
  /* 顶栏统一高度：页签、返回条都用它，和底部 Tab（57px）呼应 */
  --nagaya-head-h: 52px;
}
/* 二级页面的返回条。原来三个页面各写各的，最矮的只有 42px，挤在一起显得小气 */
.page-head {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: var(--nagaya-head-h);
  padding: 0 4px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  font-size: 16px;
}
.q-page {
  max-width: var(--nagaya-max-w);
  margin: 0 auto;
}
</style>

<style scoped>
/* 刘海屏/手势条：底栏内缩到安全区以内，否则最后一个 tab 会被手势条压住 */
.footer-safe {
  padding-bottom: env(safe-area-inset-bottom);
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
</style>
