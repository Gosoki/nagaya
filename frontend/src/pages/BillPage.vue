<!--
  账单这一节的壳子。

  **两个页签共用 /bill 一个地址**：点页签只换 store 里的 tab，不走路由 ——
  地址不动、组件不重建、返回键里也不会堆出一串账单页，切换就是一次重渲染。

  深链还留着：账目里点一笔的所属账单、固定费那一屏的返回，都是 /bill/:id 进来的。
  进来之后立刻把地址收回 /bill，免得地址栏和屏幕上说的不是一回事。
-->
<template>
  <q-page v-touch-swipe.capture.mouse.mouseCapture.horizontal="onSwipe" class="page">
    <BillView :view-key="shown" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BillView from 'src/components/BillView.vue'
import { useBillSwipe } from 'src/composables/billSwipe'
import { type BillKey, useBills } from 'src/stores/bills'

const route = useRoute()
const router = useRouter()
const bills = useBills()
const onSwipe = useBillSwipe()

/** 该显示哪一张账单。「已出账」默认最近那张，翻过就看翻到的那张 */
const shown = computed<BillKey>(() => {
  if (bills.tab === 'draft') return 'draft'
  return bills.detail === null ? 'current' : `st:${bills.detail}`
})

/** 从别处带着 :statementId 进来：收下它，然后把地址收回 /bill */
function adoptRouteParam() {
  const id = Number(route.params.statementId) || null
  if (id === null) return
  bills.detail = id
  bills.tab = 'current'                    // 出过的单子都在「已出账」这一页
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
