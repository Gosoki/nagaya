<!-- 账目列表：按日期分组。点一条去改，左滑删除（软删，进回收站）。 -->
<template>
  <q-page class="q-pb-xl">
    <q-pull-to-refresh @refresh="onRefresh">
      <div v-if="!ledger.entries.length" class="text-center text-grey-6 q-mt-xl">
        {{ t('balance.empty') }}
      </div>

      <template v-for="group in grouped" :key="group.date">
        <div class="date-head">{{ group.date }}</div>

        <!-- 那天出过的账单：在流水里留个印子，点进去看每人该付多少 -->
        <q-list v-if="statementsOn(group.date).length" separator>
          <q-item
            v-for="st in statementsOn(group.date)"
            :key="'st' + st.id"
            clickable
            class="statement-row"
            @click="openStatement(st.id)"
          >
            <q-item-section avatar>
              <q-avatar size="30px" color="primary" text-color="white">
                <q-icon name="task_alt" size="16px" />
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ t('bill.statementItem') }} · {{ st.label }}</q-item-label>
              <q-item-label caption>{{ st.covers_from }} 〜 {{ st.covers_to }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-icon name="chevron_right" color="grey-6" />
            </q-item-section>
          </q-item>
        </q-list>

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

            <q-item clickable @click="openEntry(e)">
              <q-item-section avatar>
                <q-avatar size="30px" :style="{ background: colorOf(e) }" text-color="white">
                  <q-icon :name="iconOf(e)" size="16px" />
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
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { ApiError } from 'src/api/client'
import { api } from 'src/api/client'
import type { Entry, Statement } from 'src/api/types'
import { formatYen } from 'src/i18n'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const ledger = useLedger()

const statements = ref<Statement[]>([])
const router = useRouter()

onMounted(async () => {
  statements.value = await api.get<Statement[]>('/api/statements')
})

/** 某一天出过的账单（按 cut_at 的日期归） */
const statementsOn = (date: string) =>
  statements.value.filter((st) => st.cut_at.slice(0, 10) === date)

/**
 * 点一条就去改它。已出账的也能改，差额进下一张账单的「上期结转」。
 *
 * **固定费走固定费那一屏**，不进单笔编辑页：家賃/水电煤网是一整屏一起看、
 * 一起改的东西，从账目里单独点开一笔跟从账单点开的是两套界面，没有道理。
 */
function openEntry(e: Entry) {
  if (categoryOf(e)?.monthly) {
    void router.push(
      e.statement_id
        ? { name: 'monthly', params: { statementId: String(e.statement_id) } }
        : { name: 'monthly' },
    )
    return
  }
  void router.push({ name: 'entry-edit', params: { id: String(e.id) } })
}

function openStatement(id: number) {
  void router.push({ name: 'bill', params: { statementId: String(id) } })
}

const grouped = computed(() => {
  const map = new Map<string, Entry[]>()
  for (const e of ledger.entries) {
    const list = map.get(e.date) ?? []
    list.push(e)
    map.set(e.date, list)
  }
  // 出过账单的日子即使当天没有账目也要出现在时间线上
  for (const st of statements.value) {
    const d = st.cut_at.slice(0, 10)
    if (!map.has(d)) map.set(d, [])
  }
  return [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([date, items]) => ({ date, items }))
})

// 用含归档的反查表：归档过的分类，它名下的历史账目也要能显示原来的名字和图标
const categoryOf = (e: Entry) =>
  e.category_id === null ? undefined : meta.categoryById[e.category_id]
const colorOf = (e: Entry) =>
  e.kind === 'settlement' ? '#78909c' : e.kind === 'income' ? '#43a047' : (categoryOf(e)?.color ?? '#90a4ae')
const iconOf = (e: Entry) =>
  e.kind === 'settlement' ? 'swap_horiz' : e.kind === 'income' ? 'savings' : (categoryOf(e)?.icon ?? 'receipt_long')

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
.statement-row { background: #f5f7ff; }
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
