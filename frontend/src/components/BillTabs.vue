<!-- 账单分三页，按一笔账的生命周期排：
       未出账  还没归到任何账单上的流水 —— 「还要填什么、该出账了没」
       已出账  已经出账、正在收钱的那一张 —— 「谁还没转」
       以前    更早的账单 —— 「上个月到底多少」
     这三件事看的时候心态完全不同，混在一页里哪件都别扭。

     **不是路由页签**：三页共用 /bill 一个地址，点一下只换 store 里的 tab。
     地址不动、组件不重建，切换就是一次普通的重渲染。 -->
<template>
  <q-tabs
    v-model="bills.tab"
    no-caps
    class="bill-tabs text-grey-7"
    active-color="primary"
    indicator-color="primary"
  >
    <q-tab name="draft" :label="t('bill.tabDraft')" />
    <q-tab name="current" :label="t('bill.tabOpen')" />
    <q-tab name="past" :label="t('bill.tabPast')" />
  </q-tabs>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useBills } from 'src/stores/bills'

const { t } = useI18n()
const bills = useBills()
</script>

<style scoped>
.bill-tabs {
  max-width: var(--nagaya-max-w);     /* 跟页面一样收窄居中，宽屏上别摊开 */
  margin: 0 auto;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}
/* 跟记一笔那屏的顶栏一样高，也跟底部 Tab 那一栏呼应 */
.bill-tabs :deep(.q-tab) {
  min-height: var(--nagaya-head-h);
  font-size: 16px;
}
</style>
