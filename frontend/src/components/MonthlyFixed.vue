<!--
  当前账单上的「固定费」—— 房租/电费/燃气/水费/网费 在这里一次填完。

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
  <div v-if="data" class="wrap bill-section">
    <q-item dense class="section-head">
      <q-item-section>{{ t('monthly.title') }}</q-item-section>
      <!-- 没有保存按钮：离开输入框就存。这里只报状态。
           dirtyCount > 0 只会在存失败时出现 —— 那时必须显眼，别让人以为存好了 -->
      <q-item-section side class="text-caption" :class="dirtyCount ? 'text-negative' : 'text-grey-6'">
        <div class="row items-center">
          <q-spinner v-if="busy" size="14px" class="q-mr-xs" />
          {{ busy ? t('monthly.saving') : dirtyCount ? t('monthly.unsaved', { n: dirtyCount }) : t('monthly.autoSaved') }}
        </div>
      </q-item-section>
      <q-item-section side class="amount text-grey-9">{{ formatYen(total) }}</q-item-section>
      <!-- 占位：已出账那页这里是个 chevron。留出同样宽度，两页的合计才对齐 -->
      <q-item-section side><q-icon name="chevron_right" size="18px" class="invisible" /></q-item-section>
    </q-item>

    <q-list separator>
      <q-expansion-item
        v-for="row in rows"
        :key="row.category_id"
        dense
        expand-icon-class="text-grey-5"
        header-style="min-height: var(--nagaya-fee-row-h)"
        @update:model-value="(open: boolean) => !open && saveQueued(row)"
      >
        <template #header>
          <q-item-section avatar>
            <q-avatar size="30px" :style="{ background: row.color }" text-color="white">
              <q-icon :name="row.icon" size="16px" />
            </q-avatar>
          </q-item-section>
          <!-- 状态字（参考 8/31 出账 / 有 2 笔 / 会删掉）写在名字**旁边**，不另起一行：
               另起一行的话有状态的行比没状态的高一截，一列高高低低 -->
          <q-item-section>
            <!-- 不用 flex：items-baseline 会按两种字号各自的基线去对齐，
                 把行盒撑高 1px、名字再偏 0.5px —— 于是有状态的行和没状态的行，
                 名字在一列里上下跳。普通行内文字就没这问题，撑不撑得起由 strut 说了算 -->
            <q-item-label class="name-line">
              {{ row.name }}
              <!-- 同一分类本期有好几笔时，这一行只显示得下一笔。**得给条路进去** ——
                   否则多出来的那几笔在界面上既打不开也删不掉，钱却实实在在算在账单里 -->
              <!-- 已经录了的行状态位本来就是空的（黑色实数自己说明了「录了」），
                   正好用来说清**这笔算谁垫的** —— 这是这一屏唯一会悄悄出错的地方 -->
              <span
                v-if="!stateText(row) && payerName(row)"
                class="state text-grey-6"
              >{{ payerName(row) }}</span>
              <button
                v-else-if="row.entry_count > 1"
                class="state dup-link"
                :class="stateClass(row)"
                @click.stop="openCategoryEntries(row)"
              >
                {{ stateText(row) }}
              </button>
              <span
                v-else-if="stateText(row)"
                class="state"
                :class="stateClass(row)"
              >{{ stateText(row) }}</span>
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
              @blur="saveQueued(row)"
            />
          </q-item-section>
        </template>

        <div class="q-px-md q-pb-md">
          <!-- 谁付的。改它 ＝ 定下「这一项以后都算谁垫的」，同时把本期已录的那笔
               一并改过来 —— 这两件事在固定费上本来就是一回事 -->
          <div class="payer-row">
            <div class="text-caption text-grey-6 q-mb-xs">{{ t('entry.payer') }}</div>
            <MemberPicker
              :model-value="payerOf(row)"
              :members="meta.activeMembersSelfFirst"
              @update:model-value="(id: number) => setPayer(row, id)"
            />
          </div>
          <SplitEditor
            :amount="valueOf(row)"
            :members="meta.activeMembersSelfFirst"
            :payer-id="payerOf(row)"
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
import { useRouter } from 'vue-router'

import { ApiError, api } from 'src/api/client'
import type { Category, MonthlyData, MonthlyRow } from 'src/api/types'
import MemberPicker from 'src/components/MemberPicker.vue'
import SplitEditor from 'src/components/SplitEditor.vue'
import { formatYen } from 'src/i18n'
import { useAuth } from 'src/stores/auth'
import { useBills } from 'src/stores/bills'
import { useMeta } from 'src/stores/meta'

interface Row extends MonthlyRow {
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
const bills = useBills()
const router = useRouter()
const auth = useAuth()

const data = ref<MonthlyData | null>(null)
const rows = ref<Row[]>([])
const busy = ref(false)

/** 没给这一项定过、也没有全局设置时的兜底 */
const fallbackPayerId = computed(
  () => meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null,
)

/**
 * 这一笔算谁垫的。按「谁最有发言权」排：
 *   1. 本期已经录了 → 就是当初记的那个人，谁也别动它
 *   2. 这一项定过默认垫付人 → 用它（房租永远从同一张卡扣）
 *   3. 全局的「默认垫付人」设置
 *   4. 当前登录的人
 *
 * 少了第 2 条的话，这一屏就是「谁填的算谁」：别人刷的卡被随手填进去，
 * 账本当场错一整笔房租的钱，而屏幕上一点提示都没有。
 */
function payerOf(row: Row): number | null {
  return row.payer_id ?? row.default_payer_id ?? fallbackPayerId.value
}

const payerName = (row: Row) => {
  const id = payerOf(row)
  return id === null ? '' : (meta.byId[id]?.display_name ?? '')
}

const formatPlain = (n: number) => n.toLocaleString('en-US')
const valueOf = (row: Row) => Number(row.text.replace(/\D/g, '')) || 0

/**
 * 重新拉数据。**保留还没保存的输入。**
 *
 * 原来是整体重建 rows，于是「填了三个金额 → 在底部加一项」会把那三个框
 * 全部清空、退回灰色占位 —— 而灰色数字就在同一个位置，用户唯一能察觉的
 * 线索是字体颜色。保存失败后的重载也是同一个坑。
 */
/** 看的是哪一张 —— 和账单页共用同一套缓存 key */
const cacheKey = computed(() => (historic.value ? `st:${props.statementId}` : 'draft'))

function build(d: MonthlyData) {
  const keep = new Map(rows.value.filter((r) => r.dirty).map((r) => [r.category_id, r]))
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
}

async function load() {
  build(await bills.loadMonthly(cacheKey.value))
  await hydratePayers()
}

/**
 * 已录行的原始付款人：分摊预览要按它算余数，否则预览和落库差 1 円。
 *
 * 账单页早就把这张单子的明细取过了，能直接借来用 —— 借得到就一个请求都不发，
 * 面板整块同步出来。借不到（比如直接进固定费那一屏）才自己去取。
 */
async function hydratePayers() {
  const ids = rows.value.filter((r) => r.entry_id !== null).map((r) => r.entry_id)
  if (!ids.length) return
  const shared = bills.views[cacheKey.value]?.entries
  const entries =
    shared ?? (await api.get<{ id: number; payer_id: number }[]>('/api/entries?limit=200'))
  const byId = new Map(entries.map((e) => [e.id, e.payer_id]))
  for (const r of rows.value) {
    if (r.entry_id !== null) r.payer_id = byId.get(r.entry_id) ?? null
  }
}

onMounted(() => {
  // 缓存先上屏，再后台校正。load() 本身会保留还没保存的输入，所以校正不会抹掉手输的值
  const cached = bills.monthly[cacheKey.value]
  if (cached) {
    build(cached)
    void hydratePayers()
  }
  void load()
})

/** 去账目页看这个分类本期的全部几笔 —— 面板上只显示得下一笔 */
function openCategoryEntries(row: Row) {
  void router.push({ name: 'entries', query: { category: String(row.category_id) } })
}

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
  // 只报「还有几笔没显示出来」。原来那句写全了整个来龙去脉，四十来个字，
  // 在 40px 高、右边还杵着输入框的一行里根本放不下，被省略号截掉大半 ——
  // 而这句话现在是个入口，点进去就看得到全部
  if (row.entry_count > 1) return t('monthly.duplicate', { n: row.entry_count - 1 })
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
 * 本期固定费合计。
 *
 * 底数用后端给的那个，不是把行加起来 —— 同一分类本期有两笔时，面板一行只显示
 * 得下一笔，加出来会少一笔，跟账单上的「本期固定费」当场对不上。
 * 再叠上「已经输进去但还没存」的差额，这样边填边看也是准的。
 */
const total = computed(() => {
  const base = data.value?.total ?? 0
  const pending = rows.value
    .filter((r) => r.dirty)
    .reduce((sum, r) => sum + ((r.text ? valueOf(r) : 0) - (r.amount ?? 0)), 0)
  return base + pending
})

/**
 * 存一行。**离开输入框就调它**，没有保存按钮。
 *
 * 逐行存而不是整屏一把存：一行失败只影响那一行，它自己留在 dirty 状态继续显示错误，
 * 别的行该存的已经存好了。整屏一把存的老做法在部分失败时会把没存上的输入一起清掉。
 */
/**
 * 保存是**排队**的，不是「正忙就算了」。
 *
 * 原来第一行写 `if (busy.value) return`：在第一行的请求还没回来时去填第二行，
 * 第二行的保存被直接丢掉；离屏时的 flush() 撞上同一个标志会把**每一行**都丢掉，
 * 而那时组件已经在卸载，输入的金额就真没了。
 */
let queue: Promise<void> = Promise.resolve()

function saveQueued(row: Row): Promise<void> {
  queue = queue.then(() => saveRow(row)).catch(() => {})
  return queue
}

async function saveRow(row: Row) {
  if (!row.dirty) return
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
          payer_id: payerOf(row),
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
    // 版本冲突：手里这份 version 已经过期，不重新取的话再点多少次都是同一个 409。
    // load() 会保留还没保存的输入，所以刷一下不会把人填的东西抹掉
    if (e instanceof ApiError && e.code === 'version_conflict') {
      await load().catch(() => {})
    }
  } finally {
    busy.value = false
  }
}

/** 离开这一屏时把还没存的行兜底存掉 —— 比如填完直接切了 Tab */
async function flush() {
  for (const row of rows.value) await saveQueued(row)
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

/**
 * 改这一笔算谁垫的。
 *
 * **当前草稿**：改两处 —— 分类的常驻默认（以后都按它），和本期已录的那一笔。
 *
 * **翻旧账单**：只改那一笔，不碰分类默认。修正「上个月的网费其实是 Zen 付的」
 * 是一次更正，不是在说「网费以后都算 Zen 的」。
 * 改完钱自己会平回来：余额是全局累计的，差额进下一张的「上期结转」，
 * 而这张单子上会挂出「出账后被改过」的提示 —— 不锁历史，但改动必须看得见。
 */
async function setPayer(row: Row, payerId: number) {
  if (payerOf(row) === payerId) return
  busy.value = true
  try {
    if (!historic.value) {
      const saved = await api.patch<Category>(`/api/categories/${row.category_id}`, {
        default_payer_id: payerId,
      })
      meta.categories = meta.categories.map((c) => (c.id === saved.id ? saved : c))
      row.default_payer_id = payerId
    }

    if (row.entry_id !== null) {
      const e = await api.patch<{ version: number }>(
        `/api/entries/${row.entry_id}?version=${row.version}`,
        { payer_id: payerId },
      )
      row.version = e.version
      row.payer_id = payerId
      emit('saved')             // 谁垫的变了，账单上的应收应付跟着变
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e), timeout: 5000 })
    await load().catch(() => {})
  } finally {
    busy.value = false
  }
}

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
/* 标题条上的合计：跟下面每一行的金额同字号、同一条竖线 */
.section-head .amount { font-size: var(--nagaya-fee-amount-fs); font-variant-numeric: tabular-nums; }
/* 金额列对齐：右边距 ＝ 行内边距 16 + 展开箭头 24 + 这一格的左内边距。
   要凑到 --nagaya-fee-amount-gap，这里就该留下减掉那 40px 的部分 */
.wrap :deep(.q-expansion-item .q-item__section--side:last-child) {
  padding-left: calc(var(--nagaya-fee-amount-gap) - 40px);
}
.amount-input {
  width: 116px;
  border: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.18);
  outline: none;
  background: transparent;
  text-align: right;
  font-size: var(--nagaya-fee-amount-fs);
  font-variant-numeric: tabular-nums;
  /* **不能用 inherit**：会继承 Quasar 次级文字色 rgba(0,0,0,.54)，
     跟 #c8c8c8 的占位只差一档。而「正常已录不显示标签」的全部理由
     就是「实数本身看得出录了」—— 前提是它真的够黑 */
  color: rgba(0, 0, 0, 0.87);
  /* 行高压到和账单上「本期其他」一样。输入框比行矮 6px ——
     当初写 44px 是因为行有 52px 高、上下各留出一条点了会误展开的带；
     行矮下来之后那条带只剩几像素，真正的解法本来就是压行而不是撑框 */
  height: calc(var(--nagaya-fee-row-h) - 6px);
  /* 顶上这 2px 是用来抵消底下那条 1px 下划线的。
     box-sizing 是 border-box，下划线占掉一行内容高度，文字在剩下的 33px 里居中，
     于是整体上浮 1px —— 实测数字比已出账那页高 1px。补 2px 顶内边距把内容区
     的中心往下挪 1px，框和下划线都不动 */
  padding: 2px 2px 0;
}
/* 灰色占位＝上次的参考，不是值。改过的才变实色 */
.amount-input::placeholder { color: #c8c8c8; }
.amount-input.dirty { border-bottom-color: var(--q-primary); font-weight: 600; }
.amount-input.to-delete { color: #c10015; text-decoration: line-through; }
/* 块尾那一行。已出账那页是同高的空占位，高度写在同一个变量里 */
.name-line { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* line-height 压到 1：12px 的状态字不许顶大行盒，行高交给 14px 名字的 strut 定 */
.state { font-size: 12px; line-height: 1; margin-left: 6px; }
/* 「本期有 N 笔」是个入口，长得要像能点 */
.dup-link {
  border: none;
  background: none;
  padding: 0;
  font-family: inherit;
  text-decoration: underline;
  cursor: pointer;
}
.add-row {
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  min-height: var(--nagaya-fee-foot-h);
}
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
