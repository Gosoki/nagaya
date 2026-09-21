<!-- 账目列表：按日期分组。点一条进去改。
     **没有左滑删除**：整屏都是可拨的行，拨一下就删掉一笔钱太容易误触；
     而且横向手势在账单那几页是用来翻页的，两处含义不一致更糟。
     要删就点进那一笔，编辑页上有删除按钮（带确认）。 -->
<template>
  <q-page class="q-pb-xl">
    <!-- 筛选条吸顶：列表很长，翻到一半想换个筛法不该先滚回去 -->
    <div class="filter-bar row items-center no-wrap q-gutter-xs q-px-md q-py-sm">
      <button v-for="f in filters" :key="f.key" class="chip" :class="{ on: f.value !== null }">
        {{ f.label }}
        <q-icon name="arrow_drop_down" size="18px" />
        <q-menu auto-close>
          <q-list style="min-width: 140px">
            <q-item clickable @click="f.set(null)">
              <q-item-section>{{ t('filter.all') }}</q-item-section>
            </q-item>
            <q-item v-for="o in f.options" :key="String(o.value)" clickable @click="f.set(o.value)">
              <q-item-section>{{ o.label }}</q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </button>
      <q-space />
      <!-- 筛完不给合计等于只筛了一半：「伙食这三个月花了多少」才是要问的 -->
      <div v-if="anyFilter" class="text-caption text-grey-7 no-wrap">
        {{ t('filter.sum') }} {{ formatYen(filteredTotal) }}
      </div>
      <q-btn
        v-if="anyFilter"
        dense flat round size="sm" icon="close" color="grey-7"
        @click="clearFilters"
      />
    </div>

    <q-pull-to-refresh @refresh="onRefresh">
      <div v-if="!visible.length" class="text-center text-grey-6 q-mt-xl">
        {{ anyFilter ? t('filter.empty') : t('balance.empty') }}
      </div>

      <template v-for="group in grouped" :key="group.date">
        <div class="date-head">{{ group.date }}</div>

        <!-- 那天出过的账单：在流水里留个印子，点进去看每人该付多少 -->
        <q-list v-if="!anyFilter && statementsOn(group.date).length" separator>
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
          <!-- .entry-row 是 E2E 的锚点：数账目行时不能把「出了一次账单」那种行算进来 -->
          <q-item v-for="e in group.items" :key="e.id" class="entry-row" clickable @click="openEntry(e)">
              <q-item-section avatar>
                <q-avatar size="30px" :style="{ background: colorOf(e) }" text-color="white">
                  <q-icon :name="iconOf(e)" size="16px" />
                </q-avatar>
              </q-item-section>

              <q-item-section>
                <q-item-label>{{ labelOf(e) }}</q-item-label>
                <q-item-label caption class="ellipsis">
                  {{ meta.byId[e.payer_id]?.display_name }}
                  <span v-if="e.kind === 'settlement'"> → {{ meta.byId[e.to_member_id ?? 0]?.display_name }}</span>
                  <span v-else> · {{ sharesText(e) }}</span>
                </q-item-label>
              </q-item-section>

              <q-item-section side class="text-weight-medium" :class="e.amount_jpy < 0 ? 'text-positive' : 'text-grey-9'">
                {{ formatYen(e.amount_jpy) }}
              </q-item-section>
          </q-item>
        </q-list>
      </template>
    </q-pull-to-refresh>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { api } from 'src/api/client'
import type { Entry, EntryKind, Statement } from 'src/api/types'
import { jstDateOf } from 'src/date'
import { formatYen } from 'src/i18n'
import { useLedger } from 'src/stores/ledger'
import { KIND_COLOR } from 'src/theme'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const meta = useMeta()
const ledger = useLedger()

const statements = ref<Statement[]>([])
const router = useRouter()

onMounted(async () => {
  statements.value = await api.get<Statement[]>('/api/statements')
})

/** 某一天出过的账单。cut_at 是 UTC 时间戳，得按**日本时间**归日 —— 见 src/date.ts */
const statementsOn = (date: string) =>
  statements.value.filter((st) => jstDateOf(st.cut_at) === date)

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

/**
 * 筛选。三个条件都是「不选＝不限」，交集生效。
 *
 * 在前端过滤：数据本来就整批拉下来了（store 里 500 条），切筛选是瞬时的，
 * 不用每换一次都往返一趟服务器。
 */
const fKind = ref<EntryKind | null>(null)
const fCategory = ref<number | null>(null)
const fPayer = ref<number | null>(null)

const anyFilter = computed(
  () => fKind.value !== null || fCategory.value !== null || fPayer.value !== null,
)

function clearFilters() {
  fKind.value = null
  fCategory.value = null
  fPayer.value = null
}

const visible = computed(() =>
  ledger.entries.filter(
    (e) =>
      (fKind.value === null || e.kind === fKind.value) &&
      (fCategory.value === null || e.category_id === fCategory.value) &&
      (fPayer.value === null || e.payer_id === fPayer.value),
  ),
)

/** 转账不算进合计：它是钱在两个人之间挪，不是花出去的 */
const filteredTotal = computed(() =>
  visible.value.reduce((sum, e) => sum + (e.kind === 'settlement' ? 0 : e.amount_jpy), 0),
)

const filters = computed(() => [
  {
    key: 'kind',
    value: fKind.value,
    label: fKind.value === null ? t('filter.kind') : t(`kind.${fKind.value}`),
    options: (['expense', 'income', 'settlement'] as const).map((k) => ({
      value: k,
      label: t(`kind.${k}`),
    })),
    set: (v: unknown) => (fKind.value = v as EntryKind | null),
  },
  {
    key: 'category',
    value: fCategory.value,
    label:
      fCategory.value === null
        ? t('filter.category')
        : (meta.categoryById[fCategory.value]?.name ?? t('filter.category')),
    options: meta.categories
      .filter((c) => !c.archived)
      .map((c) => ({ value: c.id, label: c.name })),
    set: (v: unknown) => (fCategory.value = v as number | null),
  },
  {
    key: 'payer',
    value: fPayer.value,
    label: fPayer.value === null ? t('filter.payer') : (meta.byId[fPayer.value]?.display_name ?? ''),
    options: meta.activeMembersSelfFirst.map((m) => ({ value: m.id, label: m.display_name })),
    set: (v: unknown) => (fPayer.value = v as number | null),
  },
])

const grouped = computed(() => {
  const map = new Map<string, Entry[]>()
  for (const e of visible.value) {
    const list = map.get(e.date) ?? []
    list.push(e)
    map.set(e.date, list)
  }
  // 出过账单的日子即使当天没有账目也要出现在时间线上（筛选时不补，那几行已经藏了）
  for (const st of anyFilter.value ? [] : statements.value) {
    const d = jstDateOf(st.cut_at)
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
  e.kind === 'expense' ? (categoryOf(e)?.color ?? '#90a4ae') : KIND_COLOR[e.kind]
const iconOf = (e: Entry) =>
  e.kind === 'settlement' ? 'swap_horiz' : e.kind === 'income' ? 'savings' : (categoryOf(e)?.icon ?? 'receipt_long')

const labelOf = (e: Entry) =>
  e.title || categoryOf(e)?.name || t(`kind.${e.kind}`)

/**
 * 分摊摘要。**绝大多数账就是均分**，把「Go ¥1,833 / Kan ¥1,834 / Zen ¥1,833」
 * 原样列出来，每一行都被撑成两行，还把真正该被看见的那几笔特殊分摊淹掉了。
 * 所以均分只说一句「均分」，分得不一样才把数字摆出来。
 */
function sharesText(e: Entry): string {
  const rows = Object.entries(e.shares).filter(([, v]) => v !== 0)
  if (!rows.length) return ''
  const names = rows.map(([id]) => meta.byId[Number(id)]?.display_name ?? id)
  const values = rows.map(([, v]) => v)
  // 除不尽时余数落在某个人头上，差 1 円 —— 那仍然是均分
  if (Math.max(...values) - Math.min(...values) <= 1) {
    return rows.length === meta.activeMembers.length
      ? t('entry.splitEven')
      : t('entry.splitEvenAmong', { names: names.join(' / ') })
  }
  return rows.map((r, i) => `${names[i]} ${formatYen(r[1])}`).join(' / ')
}

async function onRefresh(done: () => void) {
  await ledger.refresh()
  done()
}

</script>

<style scoped>
/* 筛选条吸顶。列表很长，翻到一半想换个筛法不该先滚回顶上 */
.filter-bar {
  position: sticky;
  top: 0;
  z-index: 2;
  background: #fff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}
.chip {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 4px 0 10px;
  border: none;
  border-radius: 16px;
  background: #f2f2f5;
  color: #555;
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;
}
.chip.on { background: var(--q-primary); color: #fff; }

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
