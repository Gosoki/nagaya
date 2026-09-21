<!--
  账单这一节的壳子。

  **三个页签共用 /bill 一个地址**：点页签只换 store 里的 tab，不走路由 ——
  地址不动、组件不重建、返回键里也不会堆出一串账单页，切换就是一次重渲染。

  深链还留着：账目里点一笔的所属账单、固定费那一屏的返回，都是 /bill/:id 进来的。
  进来之后立刻把地址收回 /bill，免得地址栏和屏幕上说的不是一回事。
-->
<template>
  <q-page v-touch-swipe.capture.mouse.mouseCapture.horizontal="onSwipe" class="page">
    <!-- 页签在布局的固定 header 上。翻某一张旧账单时那里不显示页签，这儿换成返回条 -->
    <div v-if="bills.detail !== null" class="page-head">
      <q-btn dense flat round icon="arrow_back" @click="bills.detail = null" />
      <div class="col text-weight-medium">{{ t('bill.tabPast') }}</div>
    </div>

    <BillView v-if="shown" :view-key="shown" />
    <BillHistoryList v-else @open="(id) => (bills.detail = id)" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import BillHistoryList from 'src/components/BillHistoryList.vue'
import BillView from 'src/components/BillView.vue'
import { useBillSwipe } from 'src/composables/billSwipe'
import { type BillKey, useBills } from 'src/stores/bills'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const bills = useBills()
const onSwipe = useBillSwipe()

/** 该显示哪一张账单；null ＝ 显示「以前」那个列表 */
const shown = computed<BillKey | null>(() => {
  if (bills.detail !== null) return `st:${bills.detail}`
  return bills.tab === 'past' ? null : bills.tab
})

/** 从别处带着 :statementId 进来：收下它，然后把地址收回 /bill */
function adoptRouteParam() {
  const id = Number(route.params.statementId) || null
  if (id === null) return
  bills.detail = id
  bills.tab = 'past'                       // 返回条退回来时落在「以前」那一列
  void router.replace({ name: 'bill' })
}

onMounted(adoptRouteParam)
watch(() => route.params.statementId, adoptRouteParam)
</script>

<style scoped>
.page {
  /* 给账单页那条固定操作条留位，否则滚到底时最后一块会被它盖住 */
  padding-bottom: calc(var(--nagaya-footer-h) + 78px + env(safe-area-inset-bottom));
}
</style>
