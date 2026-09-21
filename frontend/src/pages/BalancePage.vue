<!--
  余额看板 —— 第二个 tab。

  按 D5 排版：钱主要从一个人卡上出，所以只要债权人只有一个，
  就以他为主视角「大家欠 A 多少」；一旦变成互相都有账，自动退回通用卡片。
-->
<template>
  <q-page class="q-pa-md">
    <div v-if="creditor" class="column items-center q-mb-lg">
      <div class="text-grey-7">{{ creditor.display_name }}</div>
      <div class="text-h4 text-weight-medium">{{ formatYen(balances[String(creditor.id)] ?? 0) }}</div>
      <div class="text-caption text-grey-6">{{ t('balance.isOwed', { name: creditor.display_name }) }}</div>
    </div>

    <q-list v-if="creditor" bordered separator class="rounded-borders">
      <q-item v-for="m in debtors" :key="m.id">
        <q-item-section avatar>
          <q-avatar size="32px" :style="{ background: m.color }" text-color="white">
            {{ m.display_name.slice(0, 1) }}
          </q-avatar>
        </q-item-section>
        <q-item-section>
          {{ t('balance.owes', { name: m.display_name, payer: creditor.display_name }) }}
        </q-item-section>
        <q-item-section side class="text-weight-medium text-grey-9">
          {{ formatYen(-(balances[String(m.id)] ?? 0)) }}
        </q-item-section>
      </q-item>
      <q-item v-if="!debtors.length">
        <q-item-section class="text-grey-6">{{ t('balance.settled') }}</q-item-section>
      </q-item>
    </q-list>

    <!-- 互相都有账时的通用排版 -->
    <div v-else class="row q-col-gutter-sm">
      <div v-for="m in meta.members" :key="m.id" class="col-6">
        <q-card flat bordered class="q-pa-md text-center">
          <q-avatar size="34px" :style="{ background: m.color }" text-color="white">
            {{ m.display_name.slice(0, 1) }}
          </q-avatar>
          <div class="text-caption text-grey-7 q-mt-xs">{{ m.display_name }}</div>
          <div
            class="text-subtitle1 text-weight-medium"
            :class="(balances[String(m.id)] ?? 0) < 0 ? 'text-negative' : 'text-positive'"
          >
            {{ formatYen(balances[String(m.id)] ?? 0) }}
          </div>
        </q-card>
      </div>
    </div>

    <div class="q-mt-lg">
      <q-btn
        class="full-width"
        color="primary"
        size="lg"
        no-caps
        unelevated
        icon="receipt"
        :label="t('bill.open')"
        :to="{ name: 'bill' }"
      />
    </div>

    <div class="text-center text-caption text-grey-6 q-mt-lg">
      <div v-if="currentPeriod">
        {{ t('balance.periodTotal', { label: currentPeriod.label }) }}
        {{ formatYen(periodTotal) }}
        <span v-if="currentPeriod.status === 'open'"> · {{ t('balance.unsettled') }}</span>
      </div>
      <div v-else>{{ t('balance.empty') }}</div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Period } from 'src/api/types'
import { api } from 'src/api/client'
import { formatYen } from 'src/i18n'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'
import { onMounted, ref } from 'vue'

const { t } = useI18n()
const meta = useMeta()
const ledger = useLedger()

const balances = computed(() => ledger.balances)
const periods = ref<Period[]>([])

onMounted(async () => {
  periods.value = await api.get<Period[]>('/api/periods')
})

/** 只有一个债权人时走「大家欠他」的排版 */
const creditor = computed(() => {
  const positives = meta.members.filter((m) => (balances.value[String(m.id)] ?? 0) > 0)
  return positives.length === 1 ? positives[0] : null
})

const debtors = computed(() =>
  meta.members
    .filter((m) => (balances.value[String(m.id)] ?? 0) < 0)
    .sort((a, b) => (balances.value[String(a.id)] ?? 0) - (balances.value[String(b.id)] ?? 0)),
)

const currentPeriod = computed(() => periods.value[0] ?? null)

const periodTotal = computed(() =>
  ledger.entries
    .filter((e) => e.period_id === currentPeriod.value?.id && e.kind === 'expense')
    .reduce((s, e) => s + e.amount_jpy, 0),
)
</script>
