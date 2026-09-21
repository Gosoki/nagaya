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
      <!-- 不用 q-route-tab：它的高亮跟着 vue-router 的 matched 链走，而
           /bill/current、/bill/past 是和 /bill 平级的路由、不是它的子路由，
           于是站在那两页上底栏三个 Tab 一个都不亮。
           这里改成「路由 → 所属分区」自己算，点击自己导航 -->
      <q-tabs
        :model-value="navSection"
        dense
        no-caps
        indicator-color="transparent"
        active-color="primary"
        class="text-grey-6"
      >
        <q-tab name="add" icon="add_circle" :label="t('nav.add')" @click="go('add')" />
        <q-tab name="bill" icon="receipt" :label="t('nav.bill')" @click="go('bill')" />
        <q-tab name="entries" icon="receipt_long" :label="t('nav.entries')" @click="go('entries')" />
      </q-tabs>
    </q-footer>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BillTabs from 'src/components/BillTabs.vue'
import DraftBanner from 'src/components/DraftBanner.vue'
import { useAuth } from 'src/stores/auth'
import { useBills } from 'src/stores/bills'
import { useDrafts } from 'src/stores/drafts'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const meta = useMeta()
const auth = useAuth()
const bills = useBills()
const ledger = useLedger()
const drafts = useDrafts()
const route = useRoute()
const router = useRouter()

/**
 * 「账单」这一格代表的是一整个分区，不只是 /bill 那一页 —— 固定费那一屏
 * 只能从账单页进去，站在那儿底栏也该亮着「账单」。
 * 新加账单相关的路由时记得加进来 —— test/nav-section.spec.ts 会盯着。
 */
const BILL_SECTION = ['bill', 'monthly']

const navSection = computed(() => {
  const name = String(route.name ?? '')
  if (BILL_SECTION.includes(name)) return 'bill'
  return name === 'entries' ? 'entries' : 'add'
})

/** 点已经亮着的那一格：回到这一分区的首页（站在首页上就什么都不做） */
function go(name: string) {
  // 账单那一节没有「首页路由」可回 —— 它三页共用一个地址。
  // 点底栏的账单＝回到页签那层，而不是停在上次翻开的某张旧账单上
  if (name === 'bill') bills.detail = null
  if (route.name !== name) void router.push({ name })
}

/** 账单那三页才显示页签。翻某一张旧账单时页面自己换成返回条，这里不显示 */
const onBillTabs = computed(() => route.name === 'bill' && bills.detail === null)

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
