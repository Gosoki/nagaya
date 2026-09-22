<!-- 底栏那格叫「更多」：装的是两样不常点、但都得有个去处的东西。
       流水  一笔一笔的账 —— 「上个月买了什么」
       设置  分摊余数归谁、默认垫付人这些规矩 —— 早就进了数据库，一直缺个面板

     **备忘不在这儿**：它搬去「记一笔」那屏，和支出/收入/转账同一条选择条的第四格。
     备忘的全部价值在于将来某一刻突然需要，而「更多 → 第二页」是个想不起来去看的地方。

     **不是路由页签**：两页共用 /entries 一个地址，点一下只换 store 里的 tab，
     和账单那两页一个做法。 -->
<template>
  <q-tabs
    v-model="memos.tab"
    no-caps
    class="bill-tabs text-grey-7"
    active-color="primary"
    indicator-color="primary"
  >
    <q-tab name="ledger" :label="t('entries.tabLedger')" />
    <q-tab name="settings" :label="t('entries.tabSettings')" />
  </q-tabs>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useMemos } from 'src/stores/memos'

const { t } = useI18n()
const memos = useMemos()
</script>
