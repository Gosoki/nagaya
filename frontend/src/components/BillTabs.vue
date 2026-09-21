<!-- 账单分三页，按一笔账的生命周期排：
       未出账  还没归到任何账单上的流水 —— 「还要填什么、该出账了没」
       已出账  已经出账、正在收钱的那一张 —— 「谁还没转」
       以前    更早的账单 —— 「上个月到底多少」
     这三件事看的时候心态完全不同，混在一页里哪件都别扭。 -->
<template>
  <q-tabs
    no-caps
    class="bill-tabs text-grey-7"
    active-color="primary"
    indicator-color="primary"
  >
    <!-- 必须是 q-route-tab：q-tab 不认 :to，点了不会导航也不报错 -->
    <q-route-tab :to="{ name: 'bill' }" exact :label="t('bill.tabDraft')" />
    <q-route-tab :to="{ name: 'bill-current' }" :label="t('bill.tabOpen')" />
    <q-route-tab :to="{ name: 'bill-past' }" :label="t('bill.tabPast')" />
  </q-tabs>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<style scoped>
.bill-tabs {
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}
/* 跟记一笔那屏的顶栏一样高，也跟底部 Tab 那一栏呼应 */
.bill-tabs :deep(.q-tab) {
  min-height: var(--nagaya-head-h);
  font-size: 16px;
}
</style>
