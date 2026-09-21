<!-- 底栏那格叫「更多」：装的是三样不常点、但都得有个去处的东西。
       流水  一笔一笔的账 —— 「上个月买了什么」
       备忘  不随某一笔账走的事 —— 「水费隔月收」「备用钥匙在鞋柜第二层」
       设置  分摊余数归谁、默认垫付人这些规矩 —— 早就进了数据库，一直缺个面板

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
    <q-tab name="memo" :label="t('entries.tabMemo')" />
    <q-tab name="settings" :label="t('entries.tabSettings')" />
  </q-tabs>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useMemos } from 'src/stores/memos'

const { t } = useI18n()
const memos = useMemos()
</script>
