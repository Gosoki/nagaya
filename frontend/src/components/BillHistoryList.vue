<!-- 更早的账单，新的在前。**不含最近那一张** —— 它在「已出账」那页，
     两处都列会让人以为是两张。每行直接给金额和结清状态，翻旧账最常问的
     就是「那个月多少钱、转清了没」，不该点进去才看得到。 -->
<template>
  <div class="q-pb-xl">
    <div v-if="!statements.length && bills.statements" class="text-center text-grey-6 q-mt-xl">
      {{ t('bill.noPast') }}
    </div>

    <q-list separator>
      <q-item v-for="st in statements" :key="st.id" clickable @click="open(st.id)">
        <q-item-section avatar>
          <q-avatar size="30px" color="primary" text-color="white">
            <q-icon name="receipt_long" size="16px" />
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ st.label }}</q-item-label>
          <q-item-label caption>
            {{ t('bill.coversRange', { from: st.covers_from, to: st.covers_to }) }}
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <div class="text-weight-medium text-grey-9">{{ formatYen(st.total_expense) }}</div>
          <q-badge
            v-if="st.settled"
            color="positive"
            class="q-mt-xs"
            :label="t('bill.settledBadge')"
          />
          <div v-else class="text-caption text-grey-6 q-mt-xs">{{ t('bill.unsettled') }}</div>
        </q-item-section>
        <q-item-section side><q-icon name="chevron_right" color="grey-5" size="18px" /></q-item-section>
      </q-item>
    </q-list>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import { justSwiped } from 'src/composables/billSwipe'
import { formatYen } from 'src/i18n'
import { useBills } from 'src/stores/bills'

const { t } = useI18n()
const bills = useBills()
const emit = defineEmits<{ open: [id: number] }>()

// 最近那一张归「已出账」管，这里从第二张开始
const statements = computed(() => (bills.statements ?? []).slice(1))
// 列表走共用缓存：账单页已经取过就直接上屏，这一跳不白屏。照样后台校正
onMounted(() => void bills.loadStatements().catch(() => {}))

function open(id: number) {
  if (justSwiped()) return       // 刚划完那一下不是点击，见 billSwipe.ts
  emit('open', id)
}
</script>
