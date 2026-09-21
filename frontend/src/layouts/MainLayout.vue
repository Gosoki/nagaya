<!-- 外壳：内容在上，导航在下。
     主操作一律放屏幕下半部的拇指区（SPEC §7.4），顶部只放不常点的东西。 -->
<template>
  <q-layout view="hHh lpR fFf">
    <!-- 顶栏固定在布局上，不放进页面里：账单三页之间切换时它不该跟着卸载重建，
         切页只换中间那块内容，上下两条都不动 -->
    <q-header v-if="drafts.count || onBillTabs || route.name === 'entries'" class="bg-white text-dark">
      <DraftBanner v-if="drafts.count" />
      <BillTabs v-if="onBillTabs" />
      <EntriesTabs v-if="route.name === 'entries'" />
    </q-header>

    <q-page-container>
      <router-view v-if="meta.members.length" />
      <!-- 起不来就得说出来。原来只有一个转圈：拉不到基础数据时它会一直转下去，
           人只能看着一个永远不会停的动画 —— 而这恰好是断网时的默认下场 -->
      <div v-else-if="bootFailed" class="column flex-center q-pa-xl text-center" style="height: 60vh">
        <q-icon name="cloud_off" size="40px" color="grey-5" />
        <div class="text-grey-7 q-my-md">{{ t('common.offlineBoot') }}</div>
        <q-btn outline no-caps color="primary" :label="t('common.retry')" @click="boot" />
      </div>
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
import { useI18n } from 'vue-i18n'

import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BillTabs from 'src/components/BillTabs.vue'
import EntriesTabs from 'src/components/EntriesTabs.vue'
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
  // 账单那一节没有「首页路由」可回 —— 它两页共用一个地址。
  // 点底栏的账单＝回到最近那张，而不是停在上次翻开的某张旧账单上
  if (name === 'bill') bills.detail = null
  if (route.name !== name) void router.push({ name })
}

/** 账单那两页才显示页签 */
const onBillTabs = computed(() => route.name === 'bill')

const bootFailed = ref(false)

async function boot() {
  bootFailed.value = false
  try {
    if (!auth.me) await auth.restore()
    await meta.load()          // 失败时它自己会回退到本地缓存
  } catch {
    bootFailed.value = true
    return
  }
  // 账本刷新失败**不该挡住界面**：离线时照样要能把这一笔填完存成草稿
  try {
    await ledger.refresh()
  } catch {
    /* 离线。草稿那条路不依赖它 */
  }
}

onMounted(boot)
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
  /* 「本期固定费」那一块的尺寸。同一块东西有两套实现 —— 未出账那页是可编辑面板，
     已出账那页是只读列表 —— 两边长得必须一样。数写在这儿一份，免得又各自走散 */
  --nagaya-fee-row-h: 40px;
  --nagaya-fee-amount-fs: 16px;
  /* 金额列离右边多远。未出账那页那儿站着展开箭头，已出账那页用内边距占出来 */
  --nagaya-fee-amount-gap: 50px;
  /* 「加一条 / 加一项」那种收尾行的高度。备忘和固定费设置两处共用 */
  --nagaya-add-row-h: 50px;
}
/* 账单上的一「块」：固定费、本期其他、每人、转账方案各算一块。
   块与块之间用 8px 的灰带断开 —— 1px 细线在手机上分不出「同一块里的两行」
   和「两块之间」，整页会糊成一长条 */
.bill-section { border-bottom: 8px solid #f2f2f2; }
/* 每一块的标题条。未出账和已出账两页、四个块共用这一份，免得又各写各的。
   高度写死 44：只有「本期固定费」那条右边带着 16px 的合计，撑出 44 高，
   别的标题条只有 14px 的字、自然高度 41 —— 不钉死的话同一页上四条不齐 */
.section-head {
  min-height: 44px;
  padding-top: 16px;
  padding-bottom: 4px;
}
.section-head .q-item__section--main { font-size: 14px; font-weight: 500; }

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
