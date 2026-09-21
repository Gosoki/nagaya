<!--
  当前账单上的「固定费」—— 家賃/電気/ガス/水道/ネット 在这里一次填完。

  账单来了随时填，不用等到出账单。点「出账单」只是划一条线，把这一刻之前记的
  全部归到那张单子上。

  ## 两条要命的约束

  1. **上次的金额只作灰色占位，不是值。**
     账本里预填的数字很危险 —— 长得跟亲手填的一模一样，某个月忘了改就
     带着上月的电费把账单发出去了，谁都看不出来。不动它就等于没录。

  2. **改金额绝不能顺手改掉别的字段。**
     这一屏没有付款人选择器。以前 PATCH 复用 EntryIn（payer_id 必填），
     面板被迫带上「默认垫付人」，于是 Kan 垫的电费被 Go 改一下金额就算到了
     Go 头上，两人余额各错一个电费钱。现在 PATCH 只发真正改过的字段。
-->
<template>
  <div v-if="data" class="wrap">
    <div class="row items-center q-px-md q-pt-md q-pb-xs">
      <div class="text-subtitle2">{{ t('monthly.title') }}</div>
      <q-space />
      <!-- 没有保存按钮：离开输入框就存。这里只报状态。
           dirtyCount > 0 只会在存失败时出现 —— 那时必须显眼，别让人以为存好了 -->
      <div class="text-caption row items-center" :class="dirtyCount ? 'text-negative' : 'text-grey-6'">
        <q-spinner v-if="busy" size="14px" class="q-mr-xs" />
        {{ busy ? t('monthly.saving') : dirtyCount ? t('monthly.unsaved', { n: dirtyCount }) : t('monthly.autoSaved') }}
      </div>
    </div>

    <q-list separator>
      <q-expansion-item
        v-for="row in rows"
        :key="row.category_id"
        dense
        expand-icon-class="text-grey-5"
        header-style="min-height:52px"
        @update:model-value="(open: boolean) => !open && saveRow(row)"
      >
        <template #header>
          <q-item-section avatar>
            <q-avatar size="30px" :style="{ background: row.color }" text-color="white">
              <q-icon :name="row.icon" size="16px" />
            </q-avatar>
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ row.name }}</q-item-label>
            <q-item-label v-if="stateText(row)" caption :class="stateClass(row)">
              {{ stateText(row) }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <input
              class="amount-input"
              :class="{ dirty: row.dirty, 'to-delete': willDelete(row) }"
              type="text"
              inputmode="numeric"
              :placeholder="row.hint === null ? '' : formatPlain(row.hint)"
              :value="row.text"
              @click.stop
              @input="onInput(row, $event)"
              @blur="saveRow(row)"
            />
          </q-item-section>
        </template>

        <div class="q-px-md q-pb-md">
          <SplitEditor
            :amount="valueOf(row)"
            :members="meta.activeMembers"
            :payer-id="row.payer_id ?? defaultPayerId"
            :seed-rule="row.rule"
            @change="(rule, valid, diff) => onRule(row, rule, valid, diff)"
          />
          <!-- 删除入口放在展开区里，不放行头：行头有金额输入框，误触成本太高。
               翻旧账单时不给删：那是归档整个分类，不是这一屏该干的事 -->
          <q-btn
            v-if="!historic"
            dense flat no-caps size="sm" color="negative" icon="delete_outline"
            class="q-mt-sm"
            :label="t('monthly.removeItem')"
            @click="removeItem(row)"
          />
        </div>
      </q-expansion-item>
    </q-list>

    <!--
      自己加一项。打字就是全部操作 —— 不用进什么「分类管理」。
      加完之后它就是一项固定费：下个月自己出现在这张表里，还带着这次的金额当参考。
    -->
    <div v-if="!historic" class="row items-center q-px-md q-py-sm add-row">
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
        dense flat no-caps color="primary"
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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
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
  default_rule_json: Record<string, unknown> | null
  entry_id: number | null
  amount: number | null
  version: number | null
  rule: Record<string, unknown> | null
  date: string | null
  hint: number | null
  hint_label: string | null
  /** 本期这个分类一共有几笔。>1 说明这一行没显示全 */
  entry_count: number
}
interface MonthlyData {
  default_date: string
  rows: ApiRow[]
}
interface Row extends ApiRow {
  text: string
  dirty: boolean
  rule_override: Record<string, unknown> | null
  rule_valid: boolean
  rule_diff: number
  /** 已录账目的原始付款人。面板不改它，只拿来喂给分摊预览 */
  payer_id: number | null
}

/** 传了就是在翻一张出过的账单：只读那张单子上真有的几项，不能加也不能删 —— */
/*  加出来的是新账目，会落进当前草稿，不会进这张单子。 */
const props = defineProps<{ statementId?: number | null }>()
const emit = defineEmits<{ saved: [] }>()
const historic = computed(() => props.statementId != null)

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const auth = useAuth()

const data = ref<MonthlyData | null>(null)
const rows = ref<Row[]>([])
const busy = ref(false)

const defaultPayerId = computed(
  () => meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null,
)

const formatPlain = (n: number) => n.toLocaleString('en-US')
const valueOf = (row: Row) => Number(row.text.replace(/\D/g, '')) || 0

/**
 * 重新拉数据。**保留还没保存的输入。**
 *
 * 原来是整体重建 rows，于是「填了三个金额 → 在底部加一项」会把那三个框
 * 全部清空、退回灰色占位 —— 而灰色数字就在同一个位置，用户唯一能察觉的
 * 线索是字体颜色。保存失败后的重载也是同一个坑。
 */
async function load() {
  const keep = new Map(rows.value.filter((r) => r.dirty).map((r) => [r.category_id, r]))
  const d = await api.get<MonthlyData>(
    historic.value ? `/api/monthly?statement_id=${props.statementId}` : '/api/monthly',
  )
  data.value = d
  rows.value = d.rows.map((r) => {
    const held = keep.get(r.category_id)
    return reactive({
      ...r,
      text: held ? held.text : r.amount === null ? '' : formatPlain(r.amount),
      dirty: Boolean(held),
      rule_override: held?.rule_override ?? null,
      rule_valid: held?.rule_valid ?? true,
      rule_diff: held?.rule_diff ?? 0,
      payer_id: null,
    })
  })
  await hydratePayers()
}

/** 已录行的原始付款人：分摊预览要按它算余数，否则预览和落库差 1 円 */
async function hydratePayers() {
  const ids = rows.value.filter((r) => r.entry_id !== null).map((r) => r.entry_id)
  if (!ids.length) return
  const entries = await api.get<{ id: number; payer_id: number }[]>('/api/entries?limit=200')
  const byId = new Map(entries.map((e) => [e.id, e.payer_id]))
  for (const r of rows.value) {
    if (r.entry_id !== null) r.payer_id = byId.get(r.entry_id) ?? null
  }
}

onMounted(load)

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

/**
 * 这一行的状态说明。**正常录好的不出声** —— 黑色实数本身就说明录了，
 * 五行里重复五次「已录」只是噪音。只有需要你注意的才说话。
 */
function stateText(row: Row): string {
  if (row.entry_count > 1) return t('monthly.duplicate', { n: row.entry_count })
  if (willDelete(row)) return t('monthly.willDelete')
  if (row.entry_id !== null) return ''            // 正常已录：不出声
  if (row.hint === null) return ''                // 从没录过也没参考：留空，别写「没录过」占位
  return t('monthly.hintFrom', { label: row.hint_label ?? '' })
}
const stateClass = (row: Row) =>
  row.entry_count > 1
    ? 'text-warning'
    : willDelete(row)
      ? 'text-negative'
      : row.entry_id !== null
        ? 'text-positive'
        : 'text-grey-6'

/** 还没存上的行数（存失败才会 >0）。和 saveRow 用同一个判据 */
const dirtyCount = computed(() => rows.value.filter((r) => r.dirty).length)

/**
 * 存一行。**离开输入框就调它**，没有保存按钮。
 *
 * 逐行存而不是整屏一把存：一行失败只影响那一行，它自己留在 dirty 状态继续显示错误，
 * 别的行该存的已经存好了。整屏一把存的老做法在部分失败时会把没存上的输入一起清掉。
 */
async function saveRow(row: Row) {
  if (!row.dirty || busy.value) return
  if (!row.rule_valid) {
    $q.notify({
      type: 'negative',
      message: `${row.name}: ${t('split.notBalanced', { n: formatPlain(row.rule_diff) })}`,
      timeout: 5000,
    })
    return
  }
  const value = valueOf(row)
  busy.value = true
  try {
    if (willDelete(row)) {
      await api.del(`/api/entries/${row.entry_id}`)
      row.entry_id = null
      row.version = null
      row.amount = null
    } else if (row.entry_id !== null) {
      // **只发真正改过的字段**。尤其不发 payer_id —— 这一屏没有付款人选择器，
      // 带上它就等于把别人垫的钱悄悄改到自己头上
      const saved = await api.patch<{ id: number; version: number; amount_jpy: number }>(
        `/api/entries/${row.entry_id}?version=${row.version}`,
        {
          amount_jpy: value,
          ...(row.rule_override
            ? { rule: row.rule_override, member_ids: meta.activeMembers.map((m) => m.id) }
            : {}),
        },
      )
      row.version = saved.version
      row.amount = saved.amount_jpy
    } else if (value > 0) {
      const saved = await api.post<{ id: number; version: number; amount_jpy: number }>(
        '/api/entries',
        {
          kind: 'expense',
          date: data.value!.default_date,
          amount_jpy: value,
          payer_id: defaultPayerId.value,
          category_id: row.category_id,
          title: row.name,
          rule: row.rule_override,
          // 和分摊预览用的是同一批人，避免预览与落库分摊到不同的人头上
          member_ids: meta.activeMembers.map((m) => m.id),
        },
      )
      row.entry_id = saved.id
      row.version = saved.version
      row.amount = saved.amount_jpy
    } else {
      row.dirty = false          // 空着又没录过：没什么可存的
      return
    }
    row.dirty = false
    row.rule_override = null
    emit('saved')                // 账单总额/转账方案跟着刷新
  } catch (e) {
    // 失败就留在 dirty，输入原样保着，人能看见也能改了重来
    $q.notify({
      type: 'negative',
      message: `${row.name}: ${e instanceof ApiError ? e.text : String(e)}`,
      timeout: 5000,
    })
  } finally {
    busy.value = false
  }
}

/** 离开这一屏时把还没存的行兜底存掉 —— 比如填完直接切了 Tab */
async function flush() {
  for (const row of rows.value) await saveRow(row)
}
onBeforeUnmount(flush)

/**
 * 删掉一项固定费 —— **归档，不是真删**。
 * 那个分类底下可能已经有历史账目，真删外键会挡住，账目页也会失名。
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
    await meta.load()
    await load() // load 会保住还没保存的输入，不会把整屏清空
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
  font-variant-numeric: tabular-nums;
  /* **不能用 inherit**：会继承 Quasar 次级文字色 rgba(0,0,0,.54)，
     跟 #c8c8c8 的占位只差一档。而「正常已录不显示标签」的全部理由
     就是「实数本身看得出录了」—— 前提是它真的够黑 */
  color: rgba(0, 0, 0, 0.87);
  height: 44px;              /* 触控目标；原来 33px，相邻两行之间留出一条会误展开的带 */
  padding: 0 2px;
}
/* 灰色占位＝上次的参考，不是值。改过的才变实色 */
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
