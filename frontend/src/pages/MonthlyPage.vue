<!--
  固定费单独一屏 —— 账单来了随时填，不用等到出账单。
  出账单只是「划一条线，把这一刻之前的都算进来」，两件事分开。

  带上 :statementId 就是翻一张出过的账单的固定费：只列它真有的那几项。
-->
<template>
  <q-page class="q-pb-xl">
    <div v-if="statementId !== null" class="page-head">
      <q-btn dense flat round icon="arrow_back" @click="goBack" />
      <div class="col text-weight-medium">{{ label }}</div>
    </div>
    <MonthlyFixed :statement-id="statementId" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MonthlyFixed from 'src/components/MonthlyFixed.vue'
import { statementLabel } from 'src/statement'
import { useBills } from 'src/stores/bills'

const route = useRoute()
const router = useRouter()

const statementId = computed(() =>
  route.params.statementId ? Number(route.params.statementId) : null,
)
const label = ref('')

onMounted(async () => {
  if (statementId.value === null) return
  const sts = await useBills().loadStatements()      // 和账单页共用同一份
  label.value = statementLabel(sts.find((s) => s.id === statementId.value))
})

function goBack() {
  if (window.history.length > 1) router.back()
  else void router.push({ name: 'bill', params: { statementId: String(statementId.value) } })
}
</script>
