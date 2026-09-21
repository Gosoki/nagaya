<!--
  固定费单独一屏 —— 账单来了随时填，不用等到出账单。
  出账单只是「划一条线，把这一刻之前的都算进来」，两件事分开。
-->
<template>
  <q-page class="q-pb-xl">
    <div v-if="period">
      <MonthlyFixed :period-id="period.id" :readonly="period.status === 'closed'" @saved="noop" />
    </div>
    <div v-else class="text-center text-grey-6 q-mt-xl">{{ t('bill.noPeriod') }}</div>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { currentPeriod } from 'src/api/periods'
import type { Period } from 'src/api/types'
import MonthlyFixed from 'src/components/MonthlyFixed.vue'

const { t } = useI18n()
const period = ref<Period | null>(null)
const noop = () => {}

onMounted(async () => {
  period.value = await currentPeriod()
})
</script>
