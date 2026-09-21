<!-- 账目分两页：
       流水  一笔一笔的账 —— 「上个月买了什么」
       备忘  不随某一笔账走的事 —— 「水费隔月收」「备用钥匙在鞋柜第二层」

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
  </q-tabs>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useMemos } from 'src/stores/memos'

const { t } = useI18n()
const memos = useMemos()
</script>
