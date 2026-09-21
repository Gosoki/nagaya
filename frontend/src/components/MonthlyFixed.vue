<!--
  账单页顶部的「本期固定费」—— 家賃/電気/ガス/水道/ネット 在这里一次填完。

  为什么放在账单页而不是单开一屏：这几项的数字本来就是**出账单时才有**的，
  单开一页等于让人一个月多走一趟。合并成一个仪式：打开账单 → 填数字 →
  账单自己算出来 → 复制贴 LINE → 结清。

  两条要命的设计约束：

  1. **上期金额只做灰色占位，不是预填的值。**
     账本里预填的数字很危险 —— 长得跟亲手填的一模一样，某个月忘了改就
     带着上月的电费把账单发出去了，谁都看不出来。所以它是 placeholder，
     不动它就等于没录，这个月该项就是 0。

  2. **记入日必须落在这张账单自己的期间内。**
     归期只看 entry.date。在 10/10 填 9 月账单时若用「今天」，那笔家賃
     会落进 10 月期，9 月账单上凭空少一笔且零报错。默认日期由后端算好
     （今天在期内就用今天，否则用期末），并在界面上明写算进哪一期。
-->
<template>
  <div v-if="data" class="wrap">
    <div class="row items-center q-px-md q-pt-md q-pb-xs">
      <div class="text-subtitle2">{{ t('monthly.title') }}</div>
      <q-space />
      <q-btn
        dense
        no-caps
        unelevated
        :color="dirtyCount ? 'primary' : 'grey-4'"
        :text-color="dirtyCount ? 'white' : 'grey-7'"
        :disable="!dirtyCount || readonly"
        :loading="busy"
        :label="dirtyCount ? t('monthly.save', { n: dirtyCount }) : t('monthly.nothingChanged')"
        @click="save"
      />
    </div>

    <div class="text-caption text-grey-6 q-px-md q-pb-sm">
      {{ t('monthly.recordedOn', { date: data.default_date, label: data.label }) }}
    </div>

    <q-list separator>
      <template v-for="row in rows" :key="row.category_id">
        <q-expansion-item dense expand-icon-class="text-grey-5">
          <template #header>
            <q-item-section avatar>
              <q-avatar size="30px" :style="{ background: row.color }" text-color="white">
                <q-icon :name="row.icon" size="16px" />
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ row.name }}</q-item-label>
              <q-item-label caption :class="stateClass(row)">{{ stateText(row) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <input
                class="amount-input"
                :class="{ dirty: row.dirty, 'to-delete': willDelete(row) }"
                type="text"
                inputmode="numeric"
                :disabled="readonly"
                :placeholder="row.hint === null ? '' : formatPlain(row.hint)"
                :value="row.text"
                @click.stop
                @input="onInput(row, $event)"
              />
            </q-item-section>
          </template>

          <div class="q-px-md q-pb-md">
            <SplitEditor
              :amount="Number(row.text.replace(/\D/g, '')) || 0"
              :members="meta.activeMembers"
              :payer-id="payerId"
              :seed-rule="row.rule"
              @change="(rule, valid, diff) => onRule(row, rule, valid, diff)"
            />
            <div class="row items-center q-mt-sm q-gutter-sm">
              <div class="text-caption text-grey-7">{{ t('monthly.coversPeriod') }}</div>
              <q-btn dense flat no-caps size="sm" class="text-grey-8" :label="row.period_start ?? '—'">
                <q-popup-proxy cover>
                  <q-date v-model="row.period_start" mask="YYYY-MM-DD" minimal @update:model-value="row.dirty = true" />
                </q-popup-proxy>
              </q-btn>
              <span class="text-grey-5">〜</span>
              <q-btn dense flat no-caps size="sm" class="text-grey-8" :label="row.period_end ?? '—'">
                <q-popup-proxy cover>
                  <q-date v-model="row.period_end" mask="YYYY-MM-DD" minimal @update:model-value="row.dirty = true" />
                </q-popup-proxy>
              </q-btn>
              <q-btn
                v-if="row.period_start || row.period_end"
                dense flat round size="sm" icon="close"
                @click="row.period_start = null; row.period_end = null; row.dirty = true"
              />
            </div>

            <!-- 删除入口放在展开区里，不放行头：行头有金额输入框，误触成本太高 -->
            <q-btn
              dense flat no-caps size="sm" color="negative" icon="delete_outline"
              class="q-mt-sm"
              :disable="readonly"
              :label="t('monthly.removeItem')"
              @click="removeItem(row)"
            />
          </div>
        </q-expansion-item>
      </template>
    </q-list>

    <!--
      自己加一项。打字就是全部操作 —— 不用进什么「分类管理」。
      加完之后它就是一项固定费：下个月自己出现在这张表里，还带着这次的金额当参考。
      （只想记一次、不留痕的东西，是日常「记一笔」那屏的活。）
    -->
    <div v-if="!readonly" class="row items-center q-px-md q-py-sm add-row">
      <q-icon name="add" size="18px" class="text-grey-6 q-mr-sm" />
      <input
        v-model="newName"
        class="new-name col"
        type="text"
        maxlength="20"
        :placeholder="t('monthly.addPlaceholder')"
        @keyup.enter="addItem"
      />
      <q-btn
        dense
        flat
        no-caps
        color="primary"
        :disable="!newName.trim()"
        :loading="adding"
        :label="t('monthly.addItem')"
        @click="addItem"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, api } from 'src/api/client'
import SplitEditor from 'src/components/SplitEditor.vue'
import { useAuth } from 'src/stores/auth'
import { useMeta } from 'src/stores/meta'

interface ApiRow {
  category_id: number
  name: string
  icon: string
  color: string
  entry_id: number | null
  amount: number | null
  version: number | null
  rule: Record<string, unknown> | null
  period_start: string | null
  period_end: string | null
  date: string | null
  /** 这个分类上次记的金额，**只作灰色占位**。按分类回溯，不是简单取上一期 */
  hint: number | null
  hint_label: string | null
}
interface MonthlyData {
  period_id: number
  label: string
  status: 'open' | 'closed'
  default_date: string
  rows: ApiRow[]
}
interface Row extends ApiRow {
  text: string
  dirty: boolean
  rule_override: Record<string, unknown> | null
  rule_valid: boolean
  rule_diff: number
}

const props = defineProps<{ periodId: number; readonly: boolean }>()
const emit = defineEmits<{ saved: [] }>()

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const auth = useAuth()

const data = ref<MonthlyData | null>(null)
const rows = ref<Row[]>([])
const busy = ref(false)

const payerId = computed(
  () => meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null,
)

const formatPlain = (n: number) => n.toLocaleString('en-US')

async function load() {
  const d = await api.get<MonthlyData>(`/api/periods/${props.periodId}/monthly`)
  data.value = d
  rows.value = d.rows.map((r) =>
    reactive({
      ...r,
      text: r.amount === null ? '' : formatPlain(r.amount),
      dirty: false,
      rule_override: null,
      rule_valid: true,
      rule_diff: 0,
    }),
  )
}
onMounted(load)
watch(() => props.periodId, load)

function onInput(row: Row, e: Event) {
  const digits = (e.target as HTMLInputElement).value.replace(/\D/g, '')
  const n = Math.min(Number(digits || 0), 99_999_999)
  row.text = digits ? formatPlain(n) : ''
  row.dirty = true
  ;(e.target as HTMLInputElement).value = row.text
}

function onRule(row: Row, rule: Record<string, unknown> | null, valid: boolean, diff: number) {
  if (rule) {
    row.rule_override = rule
    row.dirty = true
  }
  row.rule_valid = valid
  row.rule_diff = diff
}

/** 本来有值、被清空了 —— 保存时删掉那笔。软删，进回收站，捞得回来 */
const willDelete = (row: Row) => row.entry_id !== null && row.text === ''

function stateText(row: Row): string {
  if (willDelete(row)) return t('monthly.willDelete')
  if (row.entry_id !== null) return t('monthly.recorded')
  if (row.hint === null) return t('monthly.noHint')
  return t('monthly.hintFrom', { label: row.hint_label ?? '' })
}
function stateClass(row: Row): string {
  if (willDelete(row)) return 'text-negative'
  return row.entry_id !== null ? 'text-positive' : 'text-grey-6'
}

const dirtyCount = computed(
  () => rows.value.filter((r) => r.dirty && r.text !== String(r.amount ?? '')).length,
)

async function save() {
  if (props.readonly) return
  const invalid = rows.value.find((r) => r.dirty && !r.rule_valid)
  if (invalid) {
    // 说清差多少。家賃这类固定金额分类改了总额却没改每人金额时会撞到这里，
    // 光说「不平」不告诉差额，人只能一个个去试
    $q.notify({
      type: 'negative',
      message: `${invalid.name}: ${t('split.notBalanced', { n: formatPlain(invalid.rule_diff) })}`,
      timeout: 5000,
    })
    return
  }
  busy.value = true
  let failed = 0
  // 串行：SQLite 单写者，并发写容易撞 database is locked
  for (const row of rows.value) {
    if (!row.dirty) continue
    const value = Number(row.text.replace(/\D/g, '')) || 0
    try {
      if (willDelete(row)) {
        await api.del(`/api/entries/${row.entry_id}`)
      } else if (row.entry_id !== null) {
        await api.patch(`/api/entries/${row.entry_id}?version=${row.version}`, {
          kind: 'expense',
          date: row.date ?? data.value!.default_date,
          amount_jpy: value,
          payer_id: payerId.value,
          category_id: row.category_id,
          title: row.name,
          period_start: row.period_start,
          period_end: row.period_end,
          rule: row.rule_override,
        })
      } else if (value > 0) {
        await api.post('/api/entries', {
          kind: 'expense',
          date: data.value!.default_date,
          amount_jpy: value,
          payer_id: payerId.value,
          category_id: row.category_id,
          title: row.name,
          period_start: row.period_start,
          period_end: row.period_end,
          rule: row.rule_override,
        })
      }
    } catch (e) {
      failed += 1
      $q.notify({
        type: 'negative',
        message: `${row.name}: ${e instanceof ApiError ? e.text : String(e)}`,
        timeout: 5000,
      })
    }
  }
  busy.value = false
  await load()
  emit('saved')
  if (failed) $q.notify({ type: 'warning', message: t('monthly.partialFail', { n: failed }) })
}

/**
 * 删掉一项固定费 —— **归档，不是真删**。
 *
 * 真删不行：这个分类底下可能已经有历史账目，外键会挡住；就算绕过去，
 * 账目页也会失名（归档过的分类，反查表里还留着名字和图标）。
 * 归档只是「以后不再出现在这张表里」，历史一个数字都不动，而且随时能加回来。
 *
 * 本期已经录了金额的话要说清楚：那笔账**不会跟着消失**，仍然算在账单里。
 * 想连账一起去掉，是把金额清空再保存（那条路是软删账目）。
 */
function removeItem(row: Row) {
  const extra =
    row.amount !== null
      ? ` ${t('monthly.removeKeepsEntry', { amount: formatPlain(row.amount) })}`
      : ''
  $q.dialog({
    title: t('monthly.removeItem'),
    message: t('monthly.removeConfirm', { name: row.name }) + extra,
    cancel: true,
  }).onOk(async () => {
    try {
      await api.patch(`/api/categories/${row.category_id}`, { archived: true })
      await meta.load()
      await load()
      $q.notify({
        type: 'positive',
        message: t('monthly.removed', { name: row.name }),
        timeout: 6000,
        // 给条后悔路：手滑删掉家賃只要点一下就回来
        actions: [
          {
            label: t('common.undo'),
            color: 'white',
            handler: async () => {
              await api.patch(`/api/categories/${row.category_id}`, { archived: false })
              await meta.load()
              await load()
            },
          },
        ],
      })
    } catch (e) {
      $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
    }
  })
}

const newName = ref('')
const adding = ref(false)

/** 建一个新的固定项。名字就是分类名，monthly 直接置位，下个月自动出现 */
async function addItem() {
  const name = newName.value.trim()
  if (!name || adding.value) return
  adding.value = true
  try {
    await api.post('/api/categories', {
      name,
      monthly: true,
      display_order: 100 + rows.value.length,
    })
    newName.value = ''
    await meta.load()        // 分类表变了，别处（日常网格、反查名字）也要跟着更新
    await load()
    $q.notify({ type: 'positive', message: t('monthly.added'), timeout: 2000 })
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
  } finally {
    adding.value = false
  }
}

defineExpose({ reload: load })
</script>

<style scoped>
.wrap { border-bottom: 8px solid #f2f2f2; }
.amount-input {
  width: 116px;
  border: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.18);
  outline: none;
  background: transparent;
  text-align: right;
  font-size: 16px;
  padding: 4px 2px;
  font-variant-numeric: tabular-nums;
  color: inherit;
}
/* 灰色占位＝上期参考，不是值。改过的才变实色 */
.amount-input::placeholder { color: #c8c8c8; }
.amount-input.dirty { border-bottom-color: var(--q-primary); font-weight: 600; }
.amount-input.to-delete { color: #c10015; text-decoration: line-through; }
.add-row { border-top: 1px solid rgba(0, 0, 0, 0.06); }
.new-name {
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  padding: 6px 0;
  color: inherit;
}
.new-name::placeholder { color: #bbb; }
</style>
