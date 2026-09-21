<!-- 账目列表：按日期分组。左滑删除（软删，进回收站）。 -->
<template>
  <q-page class="q-pb-xl">
    <q-pull-to-refresh @refresh="onRefresh">
      <div v-if="!ledger.entries.length" class="text-center text-grey-6 q-mt-xl">
        {{ t('balance.empty') }}
      </div>

      <template v-for="group in grouped" :key="group.date">
        <div class="date-head">{{ group.date }}</div>
        <q-list separator>
          <q-slide-item
            v-for="e in group.items"
            :key="e.id"
            right-color="negative"
            @right="() => remove(e)"
          >
            <template #right>
              <q-icon name="delete" />
            </template>

            <q-item>
              <q-item-section avatar>
                <q-avatar size="34px" :style="{ background: colorOf(e) }" text-color="white">
                  <q-icon :name="iconOf(e)" size="18px" />
                </q-avatar>
              </q-item-section>

              <q-item-section>
                <q-item-label>{{ labelOf(e) }}</q-item-label>
                <q-item-label caption>
                  {{ meta.byId[e.payer_id]?.display_name }}
                  <span v-if="e.kind === 'settlement'"> → {{ meta.byId[e.to_member_id ?? 0]?.display_name }}</span>
                  <span v-else> · {{ sharesText(e) }}</span>
                </q-item-label>
              </q-item-section>

              <q-item-section side class="text-weight-medium" :class="e.amount_jpy < 0 ? 'text-positive' : 'text-grey-9'">
                {{ formatYen(e.amount_jpy) }}
              </q-item-section>
            </q-item>
          </q-slide-item>
        </q-list>
      </template>
    </q-pull-to-refresh>
  </q-page>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from 'src/api/client'
import type { Entry } from 'src/api/types'
import { formatYen } from 'src/i18n'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const ledger = useLedger()

const grouped = computed(() => {
  const map = new Map<string, Entry[]>()
  for (const e of ledger.entries) {
    const list = map.get(e.date) ?? []
    list.push(e)
    map.set(e.date, list)
  }
  return [...map.entries()].map(([date, items]) => ({ date, items }))
})

const categoryOf = (e: Entry) => meta.categories.find((c) => c.id === e.category_id)
const colorOf = (e: Entry) =>
  e.kind === 'settlement' ? '#78909c' : (categoryOf(e)?.color ?? '#90a4ae')
const iconOf = (e: Entry) =>
  e.kind === 'settlement' ? 'swap_horiz' : (categoryOf(e)?.icon ?? 'receipt_long')

const labelOf = (e: Entry) =>
  e.title || categoryOf(e)?.name || t(`kind.${e.kind}`)

/** 分摊摘要：只显示实际分到钱的人，权重 0 的不占地方 */
function sharesText(e: Entry): string {
  return Object.entries(e.shares)
    .filter(([, v]) => v !== 0)
    .map(([id, v]) => `${meta.byId[Number(id)]?.display_name ?? id} ${formatYen(v)}`)
    .join(' / ')
}

async function onRefresh(done: () => void) {
  await ledger.refresh()
  done()
}

async function remove(e: Entry) {
  try {
    await ledger.remove(e)
  } catch (err) {
    $q.notify({ type: 'negative', message: err instanceof ApiError ? err.text : String(err) })
  }
}
</script>

<style scoped>
.date-head {
  padding: 10px 16px 4px;
  font-size: 12px;
  color: #888;
  background: #fafafa;
  position: sticky;
  top: 0;
  z-index: 1;
}
</style>
