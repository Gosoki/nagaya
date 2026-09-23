<!-- 账目列表：按日期分组。点一条进去改。
     **没有左滑删除**：整屏都是可拨的行，拨一下就删掉一笔钱太容易误触；
     而且横向手势在账单那几页是用来翻页的，两处含义不一致更糟。
     要删就点进那一笔，编辑页上有删除按钮（带确认）。 -->
<template>
  <q-page class="q-pb-xl">
    <SettingsPanel v-if="memos.tab === 'settings'" />
    <template v-else>
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
      <!-- 筛完不给合计等于只筛了一半：「伙食这三个月花了多少」才是要问的。
           但一次只拉得到最近 500 笔，更早的没在手里 —— 那就把话说明白，
           绝不能让人以为这个合计是全部 -->
      <div v-if="anyFilter" class="text-caption text-grey-7 no-wrap">
        {{ t('filter.sum') }} {{ formatYen(filteredTotal) }}
        <span v-if="ledger.truncated" class="text-warning">{{ t('filter.partial') }}</span>
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
        <!-- 一天一张卡片：那天出过的账单（如果有）在上，流水在下 -->
        <div class="card day-card">

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
              <q-item-label>{{ t('bill.statementItem') }} · {{ statementLabel(st) }}</q-item-label>
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

              <q-item-section side class="text-weight-medium num" :class="e.amount_jpy < 0 ? 'text-positive' : 'text-grey-9'">
                {{ formatYen(e.amount_jpy) }}
              </q-item-section>
          </q-item>
        </q-list>
        </div>
      </template>
    </q-pull-to-refresh>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { ApiError } from 'src/api/client'
import type { Entry, EntryKind, Statement } from 'src/api/types'
import { jstDateOf } from 'src/date'
import { formatYen } from 'src/i18n'
import { FALLBACK } from 'src/palette'
import SettingsPanel from 'src/components/SettingsPanel.vue'
import { useBills } from 'src/stores/bills'
import { useLedger } from 'src/stores/ledger'
import { useMemos } from 'src/stores/memos'
import { KIND_COLOR } from 'src/theme'
import { useMeta } from 'src/stores/meta'
import { statementLabel } from 'src/statement'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const ledger = useLedger()
const bills = useBills()
const memos = useMemos()

const statements = ref<Statement[]>([])
const router = useRouter()
const route = useRoute()

onMounted(async () => {
  // 带着 ?category= 进来的（固定费面板上「本期有 N 笔」点进来）：直接筛好。
  // **页签也要拨回流水**：这一屏显示哪块由 memos.tab 决定，而它记在 sessionStorage 里 ——
  // 只要这次会话去过「更多 → 设置」，这个链接就把人送到设置面板上，
  // 一笔账都看不到。而固定费项目的增删改就在设置那一屏，停在 settings 是常态
  const wanted = Number(route.query.category)
  if (wanted) {
    memos.tab = 'ledger'
    fCategory.value = wanted
  }
  // 和账单页共用同一份（同时只取一发）
  statements.value = await bills.loadStatements()
})

/** 某一天出过的账单。cut_at 是 UTC 时间戳，得按**日本时间**归日 —— 见 src/date.ts */
/**
 * 按日本时间的那一天归好。原来每个日期组都把全部单子过滤一遍、每张都格式化一次日期，
 * 模板里还调两次 —— 5 年的数据一次重画要 1.8 万次日期格式化（实测 17ms）
 */
const statementsByDay = computed(() => {
  const out = new Map<string, Statement[]>()
  for (const st of statements.value) {
    const day = jstDateOf(st.cut_at)
    const list = out.get(day)
    if (list) list.push(st)
    else out.set(day, [st])
  }
  return out
})
const NONE: Statement[] = []
const statementsOn = (date: string) => statementsByDay.value.get(date) ?? NONE

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

/**
 * 转账不算进合计：它是钱在两个人之间挪，不是花出去的。
 *
 * **除非你就是在看转账**：专门筛了「转账」还给个恒为 ¥0 的合计，那不是
 * 「转账不计入」的意思，那看着就是坏了。
 */
const onlySettlements = computed(() => fKind.value === 'settlement')
const filteredTotal = computed(() =>
  visible.value.reduce(
    (sum, e) => sum + (e.kind === 'settlement' && !onlySettlements.value ? 0 : e.amount_jpy),
    0,
  ),
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
  e.kind === 'expense' ? (categoryOf(e)?.color ?? FALLBACK) : KIND_COLOR[e.kind]
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
  // done() 必须在 finally 里：断网时 refresh 抛异常，原来那个圈就一直转下去，
  // 而下拉刷新最常用的场合恰恰是「好像没更新，我拉一下」—— 也就是网不好的时候
  try {
    await ledger.refresh()
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
  } finally {
    done()
  }
}

</script>

<style scoped>
/* 筛选条吸顶。列表很长，翻到一半想换个筛法不该先滚回顶上 */
.filter-bar {
  position: sticky;
  /* 吸在页签条的**下沿**。写 0 的话它会滚到固定顶栏底下去，
     于是「翻到一半想换个筛法不该先滚回顶上」这句注释说的效果正好反过来 —— 
     实测要往回滚三千多像素才找得回来 */
  /* 用量出来的顶栏高度（含安全区、离线细带、草稿横幅），不用常数：
     顶栏里多出一条带子时，常数会让筛选条钻到它底下去 */
  top: var(--nagaya-header-h);
  z-index: 2;
  background: var(--nagaya-bg);
}
.chip {
  display: inline-flex;
  align-items: center;
  /* 44 是拇指的底线。32 高的 chip 一排三个挨着，点错概率不低，
     而点错的代价是「筛出来的合计变了但人没察觉」 */
  height: 44px;
  padding: 0 8px 0 14px;
  border: none;
  border-radius: var(--nagaya-r-pill);
  background: var(--nagaya-surface);
  box-shadow: var(--nagaya-shadow);
  color: var(--nagaya-ink-2);
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;
}
.chip.on { background: var(--q-primary); color: #fff; }

.statement-row { background: var(--nagaya-accent-bg); }
/* 日期是卡片上方的一行小字，不再是一条灰带 */
.date-head {
  padding: 16px 28px 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--nagaya-ink-3);
}
.day-card { margin-top: 0; }
</style>
