<!-- 账单分两页，按一笔账的生命周期排：
       未出账  还没归到任何账单上的流水 —— 「还要填什么、该出账了没」
       已出账  出过的单子 —— 默认是最近那张（「谁还没转」），
               更早的从标题那个名字翻，不再单独占一页
     这两件事看的时候心态完全不同，混在一页里哪件都别扭。

     **不是路由页签**：两页共用 /bill 一个地址，点一下只换 store 里的 tab。
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
  </q-tabs>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useBills } from 'src/stores/bills'

const { t } = useI18n()
const bills = useBills()
</script>

<!-- .bill-tabs 的样式在 src/css/tokens.css 里 —— 「更多」那组页签共用同一份 -->
