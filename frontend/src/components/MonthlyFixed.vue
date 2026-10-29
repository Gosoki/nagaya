<!--
  当前账单上的「固定费」—— 房租/电费/燃气/水费/网费 在这里一次填完。

  账单来了随时填，不用等到出账单。点「出账单」只是划一条线，把这一刻之前记的
  全部归到那张单子上。

  ## 两条要命的约束

  1. **不填就是 0，而且照样能出账。**
     这一屏不摆「上期是多少」当参考 —— 参考值就在输入框那个位置，
     长得跟亲手填的没两样，某个月忘了改就带着上月的电费把账单发出去了。
     每期真的不变的项（房租这种）去设置里开「和上期一样」：展开那一行，里面有个
     「照上期 ¥…」，**人点一下**才记成黑字实数（出账对话框里也有一个勾）。
     原来是打开账单页就自动记 —— 看一眼和记了几笔钱分不开。
     没开的项空着就空着，按 0 结。

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
      <q-item-section
        side
        class="text-caption save-state"
        :class="[dirtyCount ? 'text-negative' : 'text-grey-6', { idle: !busy && !dirtyCount }]"
      >
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
          <!-- 状态字（有 2 笔 / 会删掉 / 已归档）写在名字**旁边**，不另起一行：
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
              <!-- 「照上期」不在这一行上，在展开区里（见下面 carry-row）：这一行一点就是记钱，
                   滚动时拇指一蹭就记上一个月房租。出账对话框里那个「先按上期记上」的勾还在，忘了点也漏不掉 -->
              <!-- 服务器上这一项在我没看见时被记了 / 被改了，和我没存上的不一样：最要紧，排第一。
                   是个入口 —— 点了问用哪个，不替人选（见 mergeHeld） -->
              <button
                v-if="row.conflict"
                class="state dup-link text-warning"
                @click.stop="saveQueued(row)"
              >{{ t('monthly.conflictShort', { amount: formatYen(row.conflict.amount ?? 0) }) }}</button>
              <!-- 开了开关却照抄不了（垫付人搬走了、来了新室友、上期有好几笔）：一直写在这儿，填了就消失 -->
              <span
                v-else-if="!stateText(row) && isCarryBlocked(row)"
                class="state text-warning"
              >{{ blockedText(row) }}</span>
              <!-- 起步分摊没写到新室友、日常分类里可能已经记过这一项：都是「请看一眼」，
                   排在垫付人前面（垫付人在展开区的「谁付的」里照样看得到）。展开区里说全 -->
              <span
                v-else-if="!stateText(row) && missingNames(row)"
                class="state text-warning"
              >{{ t('monthly.ruleMissingShort', { names: missingNames(row) }) }}</span>
              <span
                v-else-if="!stateText(row) && elsewhere(row).length"
                class="state text-warning"
              >{{ row.entry_id === null ? t('monthly.elsewhereShort') : t('monthly.dupElsewhereShort') }}</span>
              <span
                v-else-if="!stateText(row) && payerName(row)"
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
              :aria-label="row.name"
              type="text"
              inputmode="numeric"
              placeholder="0"
              :value="row.text"
              @click.stop
              @focus="($event.target as HTMLInputElement).select()"
              @input="onInput(row, $event)"
              @compositionend="onInput(row, $event)"
              @blur="saveQueued(row)"
            />
          </q-item-section>
        </template>

        <div class="q-px-md q-pb-md">
          <!-- 「照上期」：开了「和上期一样」的项，展开了就**一直在**，本期填没填都在 ——
               还没填的点了就按上期记上；填过、数和上期一样的写「已照上期」（点不动）；
               数不一样的点了改回上期的数。这儿地方够，金额直接写在按钮上 -->
          <div v-if="carryShown(row)" class="carry-row">
            <button class="carry-chip" :disabled="carrying || isAtLast(row)" @click="applyLast(row)">
              {{
                isAtLast(row)
                  ? t('monthly.carriedAlready', { amount: formatYen(row.last_amount ?? 0) })
                  : `${t('monthly.carryOne')} ${formatYen(row.last_amount ?? 0)}`
              }}
            </button>
          </div>
          <!-- 最近几期都一样、却没开「和上期一样」：提示一下，点了只开开关、不记钱 ——
               开了之后上面那颗「照上期 ¥…」才出现，记不记还是人再点一次（D36）。
               **不写金额**：没开的项上期多少一分都不许漏过来（D21） -->
          <div v-if="suggestShown(row)" class="carry-row">
            <button class="hint-chip" :disabled="busy" @click="turnOnSameAsLast(row)">
              {{ t('monthly.suggestSameAsLast', { k: hintK }) }}
            </button>
          </div>
          <!-- 行头只放得下几个字，为什么要人看一眼在这里说全 -->
          <div v-if="lastMultiText(row)" class="text-caption text-warning q-mb-sm">{{ lastMultiText(row) }}</div>
          <div v-if="missingNames(row)" class="text-caption text-warning q-mb-sm">
            {{ t('monthly.ruleMissing', { names: missingNames(row) }) }}
          </div>
          <!-- 记在日常分类里、备注带着这一项名字的账：点了去那一笔看。只是「是不是它」，
               不替人搬分类，也不因此把这一项当成已经填过 -->
          <button
            v-for="m in elsewhere(row)"
            :key="m.entry_id"
            class="elsewhere-link text-caption text-warning q-mb-sm"
            @click="openEntry(m.entry_id)"
          >{{ elsewhereText(row, m) }}</button>
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
            :members="rowMembers.get(row.category_id) ?? meta.activeMembersSelfFirst"
            :payer-id="payerOf(row)"
            :entry-id="row.entry_id"
            :seed-rule="row.rule"
            @change="(rule, valid, diff) => onRule(row, rule, valid, diff)"
          />
          <!-- 删除入口放在展开区里，不放行头：行头有金额输入框，误触成本太高。
               翻旧账单时不给删：那是归档整个分类，不是这一屏该干的事 -->
          <q-btn
            v-if="!historic && !row.archived"
            dense flat no-caps size="sm" color="negative" icon="delete_outline"
            class="q-mt-sm"
            :label="t('monthly.removeItem')"
            @click="removeItem(row)"
          />
        </div>
      </q-expansion-item>
    </q-list>

  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError, api, errorText } from 'src/api/client'
import type { CarryResult, Category, Member, MonthlyData, MonthlyRow } from 'src/api/types'
import MemberPicker from 'src/components/MemberPicker.vue'
import SplitEditor from 'src/components/SplitEditor.vue'
import { newClientKey } from 'src/clientKey'
import {
  amountOf,
  carryShown as carryShownIn,
  eachLive,
  isAtLast,
  isCarryBlocked as carryBlockedIn,
  jumpFactor,
  lastAction,
  mergeHeld,
  payerOf as payerIn,
  saveSig,
  settleSaved,
} from 'src/core/monthlyRows'
import { seedToRatio } from 'src/core/seed'
import { todayJst } from 'src/date'
import { digitsOf, yenOf } from 'src/digits'
import { formatYen } from 'src/i18n'
import { useBills } from 'src/stores/bills'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'
import { holdReload } from 'src/unsaved'

interface Row extends MonthlyRow {
  text: string
  dirty: boolean
  rule_override: Record<string, unknown> | null
  rule_valid: boolean
  rule_diff: number
  /** 已录那一笔是谁垫的（后端随行给的，和 entry_id 同一次查出来）。分摊预览按它算余数 */
  payer_id: number | null
  /**
   * 服务器上这一项在我没看见的时候变了（室友刚记了一笔、或者同一笔被人改过），
   * 而且和我没存上的不一样 —— 这里是服务器那边现在的样子。挂着它的行**不自动写**，
   * 要人选用哪个（core/monthlyRows.mergeHeld）
   */
  conflict: { amount: number | null; payer_id: number | null } | null
  /** 上一次撞量级闸（409 amount_jump）时后端给的倍数和方向。存上了就清 */
  jump: { ratio?: unknown; direction?: unknown } | null
  /** 人确认过「就是这个数」的那个金额。框里还是它才带 confirm_jump —— 改了数要重新确认 */
  jump_ok: number | null
  /**
   * 刚被「清空＝删除」那一笔的分摊规则和日期。
   *
   * 清空再重打本来只是「改个金额」，可走的是 delete + create 两步：
   * create 时 rule 传 null，后端就换成了分类默认规则 —— 而展开区里显示的
   * 还是原来那条（seed-rule 还是 row.rule，没动过就不会 emit）。
   * 于是屏幕上写着 1:1:0、存进去的是均分，两边对不上且一声不吭。
   */
  deleted_rule: Record<string, unknown> | null
  deleted_date: string | null
  /**
   * 新记这一笔的幂等键，和发出去的内容绑在一起。响应丢在路上、这一行留着 dirty，
   * 下一次失焦再 POST 同样的内容时带同一个键 —— 后端认得出，不记第二笔
   */
  post_key: string | null
  post_sig: string
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
const ledger = useLedger()
const router = useRouter()

const data = ref<MonthlyData | null>(null)
const rows = ref<Row[]>([])

/**
 * 没碰过分摊时存哪条规则 —— 和 SplitEditor 预览的是同一份（src/core/seed.ts）。
 * 新记的这一笔参与人是今天在籍的人，和预览、和 POST 带的 member_ids 一致。
 * 没有起步规则才发 null：后端用全局默认，和预览的「全员同权」是一回事
 */
function untouchedRule(seed: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!seed) return null
  return {
    mode: 'ratio',
    ...seedToRatio(seed, meta.activeMembers.map((m) => String(m.id))),
    remainder_to: (seed.remainder_to as string | undefined) || meta.setting<string>('remainder_to', 'payer'),
  }
}

/**
 * 每一行分摊给谁。**已录的那一笔按它自己的参与人**（规则里点了名的那几个人），
 * 没录的按今天在籍的人 —— 和记一笔那屏改旧账时同一个写法（AddEntryPage.splitMembers）。
 * 原来一律用今天在籍的人：有人月中搬走之后回来改一下这期的电费，
 * 一碰分摊就把他从这笔里剔掉了，而他明明住到了月底
 */
const rowMembers = computed(() => {
  const out = new Map<number, Member[]>()
  for (const r of rows.value) {
    if (r.entry_id === null || !r.rule) continue
    const named = (r.rule.exact ?? r.rule.weights) as Record<string, unknown> | undefined
    const list = Object.keys(named ?? {})
      .map((k) => meta.byId[Number(k)])
      .filter((m): m is Member => Boolean(m))
      .sort((a, b) => a.display_order - b.display_order || a.id - b.id)
    if (list.length) out.set(r.category_id, list)
  }
  return out
})
const busy = ref(false)

/** 没给这一项定过、也没有全局设置时的兜底（全局那位得今天还住在这儿） */
const fallbackPayerId = computed(() => meta.defaultPayerOn(todayJst()))
const activeIds = computed(() => meta.activeMembers.map((m) => m.id))

/** 这一笔算谁垫的。按「谁最有发言权」排，次序和理由见 core/monthlyRows.payerOf */
const payerOf = (row: Row): number | null =>
  payerIn(row, { historic: historic.value, active: activeIds.value, fallback: fallbackPayerId.value })

const payerName = (row: Row) => {
  const id = payerOf(row)
  return id === null ? '' : (meta.byId[id]?.display_name ?? '')
}

const formatPlain = (n: number) => n.toLocaleString('en-US')
const valueOf = (row: Row) => amountOf(row.text)

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
  // 留住两种行：**还没保存的**（输入不能被抹掉），和**刚被清空删掉的**
  // （deleted_rule 要活到用户重新填上那一刻 —— 那一步是「改个金额」，
  //  不该顺手把分摊换成分类默认）。只按 dirty 挑的话，删完 dirty 已经置回 false，
  //  重载一次那条规则就没了
  const keep = new Map(
    rows.value.filter((r) => r.dirty || r.deleted_rule).map((r) => [r.category_id, r]),
  )
  const taken: string[] = []
  const same: string[] = []
  const conflicted: string[] = []
  data.value = d
  rows.value = d.rows.map((r) => {
    let held = keep.get(r.category_id)
    // 这一行正在存（请求还在路上）：**原样留着这个对象**。换成新对象的话，
    // 存完的结果写回的是旧对象，新的这一行还是 dirty、没有 entry_id ——
    // 下一次失焦或离屏就把同一笔钱再 POST 一遍
    if (held && saving.has(r.category_id)) return held
    const merge = mergeHeld(held, r)
    if (merge === 'taken') {
      // **手里那一笔被出账带走了**（有人在另一台上出了账）：这一行现在是新一期的
      // 空行。没存上的输入不能留 —— 留着的话，下一次失焦/离开这一屏就把它当成
      // 新的一笔记进下一期，而人以为自己改的是刚才那笔
      taken.push(r.name)
      held = undefined
    } else if (merge === 'same') {
      // 服务器上已经是我要填的那个数了（室友记了同一个数，或者我自己的 POST 其实成功了、
      // 只是回应丢在路上）：用服务器那份，不再写
      same.push(`${r.name} ${formatYen(r.amount ?? 0)}`)
      held = undefined
    } else if (merge === 'server' && held?.dirty) {
      held = undefined             // 我这边是个空着的新行，服务器上有了：没什么要留的
    } else if (merge === 'conflict' && !held?.conflict) {
      conflicted.push(r.name)
    }
    // 冲突的行：输入留着、标红，entry_id/version 换成服务器那一笔现在的 ——
    // 但**不自动写**（saveRow 见到 conflict 就停下来问人）。人选「用我这边的」，
    // 写的就是服务器上现在那一笔、带着它现在的 version，乐观锁照样守着
    const conflict = merge === 'conflict' ? { amount: r.amount, payer_id: r.payer_id ?? null } : null
    return reactive({
      ...r,
      // 这期刚清空删掉的那一笔：重打金额是「改个金额」，起步规则就是它自己的，
      // 不是服务器按上期给的那条 —— 预览和保存必须是同一条
      rule: r.entry_id === null && held?.deleted_rule ? held.deleted_rule : r.rule,
      text: held?.dirty ? held.text : r.amount === null ? '' : formatPlain(r.amount),
      dirty: Boolean(held?.dirty),
      rule_override: held?.rule_override ?? null,
      rule_valid: held?.rule_valid ?? true,
      rule_diff: held?.rule_diff ?? 0,
      // 已录那一笔是谁垫的：后端和 entry_id 同一次查出来。原来是从账单页的明细缓存里借
      // （最多 200 笔、还可能是旧的），借不到就退回去猜 —— 屏幕上写着一个猜的人，
      // 照着它点「改正」还会顺手改掉分类的默认垫付人
      payer_id: r.payer_id ?? null,
      deleted_rule: held?.deleted_rule ?? null,
      deleted_date: held?.deleted_date ?? null,
      post_key: held?.dirty ? held.post_key : null,
      post_sig: held?.dirty ? held.post_sig : '',
      conflict,
      jump: held?.dirty ? held.jump : null,
      jump_ok: held?.dirty ? held.jump_ok : null,
    })
  })
  if (taken.length) {
    $q.notify({ type: 'warning', timeout: 6000, message: t('monthly.takenByCut', { names: taken.join('、') }) })
  }
  if (same.length) {
    $q.notify({ type: 'info', timeout: 6000, message: t('monthly.sameAsServer', { list: same.join('、') }) })
  }
  // 离屏途中（leave 的兜底存撞了 409 → 重取）就不叫人「点那一行」了：那一行已经不在屏幕上，
  // 最后那条「没存上」的提示会把它列出来
  if (conflicted.length && !leaving) {
    $q.notify({ type: 'warning', timeout: 8000, message: t('monthly.conflictFound', { names: conflicted.join('、') }) })
  }
}

async function load() {
  build(await bills.loadMonthly(cacheKey.value))
}

/**
 * 缓存那份被别处刷新了（切回前台、别的页记了账、室友出了账）：照着重建。
 * 原来这个面板只在挂载时取一次 —— 室友出账之后切回来，上面的合计已经清零，
 * 这一块还挂着上一期的房租，人以为这期录过了就不填。build 会留住没存的输入
 */
watch(
  () => bills.monthly[cacheKey.value],
  (d) => {
    if (!d || d === data.value) return
    build(d)
  },
)

onMounted(() => {
  // 缓存先上屏，再后台校正。load() 本身会保留还没保存的输入，所以校正不会抹掉手输的值
  const cached = bills.monthly[cacheKey.value]
  if (cached) build(cached)
  void load()
})

/** 抄不了、还空着的行（行头写着为什么）/ 展开区那颗「照上期 ¥…」露不露 —— 判据见 core/monthlyRows */
const isCarryBlocked = (r: Row) => carryBlockedIn(r, historic.value)
const carryShown = (r: Row) => carryShownIn(r, historic.value)
const carrying = ref(false)

/** 行头那句「为什么要自己填」。上期有好几笔的单说 —— 写成「人变了」是错的提示 */
const blockedText = (row: Row) =>
  row.carry_blocked === 'last_multi' ? t('monthly.carryLastMulti') : t('monthly.carryStale')

/** 上期这一项记了好几笔：展开区说全（几笔、合计多少）。只对还没录的行说 */
function lastMultiText(row: Row): string {
  const d = row.carry_blocked_detail
  if (historic.value || row.carry_blocked !== 'last_multi' || !d || row.entry_id !== null) return ''
  return t('monthly.lastMultiDetail', { n: d.count, total: formatYen(d.total) })
}

/**
 * 起步分摊点了名、却没写到的今天在籍的人（新室友）—— 照这样存，他在这一项上担 0。
 * 只对还没录、也没动过分摊的行说；补多少只有住的人知道，这里不替人补
 */
function missingNames(row: Row): string {
  if (historic.value || row.entry_id !== null || row.rule_override !== null) return ''
  return (row.rule_missing_member_ids ?? [])
    .map((id) => meta.byId[id]?.display_name)
    .filter(Boolean)
    .join('、')
}

type Elsewhere = NonNullable<MonthlyRow['maybe_elsewhere']>[number]
/** 草稿里记在日常分类、备注带着这一项名字的那几笔（翻旧账单时后端不给） */
const elsewhere = (row: Row): Elsewhere[] => (historic.value ? [] : (row.maybe_elsewhere ?? []))
function elsewhereText(row: Row, m: Elsewhere): string {
  // 没挂分类的支出（兜底分类没设时记的）就叫它「支出」，别留个空的「·电费」
  const p = { category: m.category_name ?? t('kind.expense'), title: m.title, amount: formatYen(m.amount) }
  return row.entry_id === null ? t('monthly.elsewhereEmpty', p) : t('monthly.elsewhereFilled', p)
}
function openEntry(id: number) {
  void router.push({ name: 'entry-edit', params: { id: String(id) } })
}

/** 「最近 k 期都一样 —— 以后照上期？」露不露。k 在设置里（0 ＝ 关，后端就不给） */
const hintK = computed(() => meta.setting<number>('same_as_last_hint_k', 3))
const suggestShown = (row: Row) =>
  !historic.value && Boolean(row.suggest_same_as_last) && !row.same_as_last && !row.archived

/**
 * 照提示打开「和上期一样」。**只开开关，不记钱**：开了之后这一行展开区里出现「照上期 ¥…」，
 * 记不记仍由人再点一次（D36）。最近几期一样不等于下期也一样（涨租那期就不一样），
 * 所以这一步也不替人做
 */
async function turnOnSameAsLast(row: Row) {
  busy.value = true
  try {
    const saved = await api.patch<Category>(`/api/categories/${row.category_id}`, { same_as_last: true })
    meta.categories = meta.categories.map((c) => (c.id === saved.id ? saved : c))
    bills.monthlyWritten()       // 在这之前发出去的 /monthly 回来，没有「照上期」那颗按钮
    await load()
    $q.notify({ type: 'positive', timeout: 6000, message: t('monthly.sameAsLastOn', { name: row.name }) })
  } catch (e) {
    $q.notify({ type: 'negative', message: errorText(e), timeout: 5000 })
  } finally {
    busy.value = false
  }
}

/**
 * 点「照上期」。还没填（也没在填、也没在存）的走 carry：后端照上期那一笔的垫付人和分摊记一笔，当场报出来。
 * 填过的、正在填的、本期删掉过的：等于替人把上期的数敲进框里再存 —— 垫付人和分摊都不动。
 * 打完数直接点它时，失焦那次保存已经发出去了：这里改的框、排上的保存不会被它吞掉（settleSaved）
 */
function applyLast(row: Row) {
  if (lastAction(row, historic.value, saving.has(row.category_id)) === 'carry') {
    void carry([row])
    return
  }
  row.text = formatPlain(row.last_amount ?? 0)
  row.dirty = true
  void saveQueued(row)
}

/**
 * 把「和上期一样」的那几项按上期金额记进来。**人点了才记。**
 *
 * **记了就得说出来。**「上期的金额不许预填、连灰色参考都不给」那条规矩的全部理由，就是
 * 「预填的数字长得跟亲手填的一模一样，某个月忘了改也没人看得出」。
 * 这个开关是那条规矩唯一的出口，所以记上的每一笔都当场报出来。
 */
async function carry(list: Row[]) {
  if (historic.value || carrying.value || !list.length) return
  carrying.value = true
  try {
    const { created, failed } = await api.post<CarryResult>('/api/monthly/carry', {
      category_ids: list.map((r) => r.category_id),
    })
    bills.monthlyWritten()
    await load()
    if (created.length) {
      emit('saved')
      void ledger.refresh().catch(() => {})
      $q.notify({
        type: 'info',
        timeout: 6000,
        message: t('monthly.carried', { list: created.map((c) => carriedText(c, list)).join('、') }),
      })
    }
    // **搬不过来的也必须说出来。** 这个开关存在的全部理由是「自动记的钱要看得见」，
    // 那么「自动记账已经停了」同样要看得见 —— 原来这里是个空 catch，
    // 有人搬走之后它就一声不吭地失效了，而屏幕上只是几个空框。
    // 上期有好几笔的单说：那句「人变了，得重新定怎么分」放在它身上是错的
    const multi = failed.filter((f) => f.reason === 'last_multi')
    const other = failed.filter((f) => f.reason !== 'last_multi')
    if (other.length) {
      $q.notify({
        type: 'warning',
        timeout: 8000,
        message: t('monthly.carryFailed', { list: other.map((f) => f.name).join('、') }),
      })
    }
    if (multi.length) {
      $q.notify({
        type: 'warning',
        timeout: 8000,
        message: t('monthly.carryFailedMulti', { list: multi.map((f) => f.name).join('、') }),
      })
    }
  } catch (e) {
    // 整个请求失败（断网/后端炸了）：也得出声，并且把已经落库的那部分拉回来 ——
    // 不 reload 的话用户会照着空框再填一遍，同一分类当期就有了两笔
    await load().catch(() => {})
    $q.notify({
      type: 'negative',
      timeout: 6000,
      message: `${t('monthly.title')}: ${errorText(e)}`,
    })
  } finally {
    carrying.value = false
  }
}

/**
 * 通知里那一笔「记成了谁垫的」。照上期的垫付人是分类的常驻默认（面板上改过一次「谁付的」
 * 就跟着变）或者上期那一笔的 —— 一笔房租记给错的人就是十几万的错，所以要说出来。
 * 照后端实际记的说（created.payer_id；老后端没有就用行上的 carry_payer_id），不自己推算
 */
function carriedText(c: CarryResult['created'][number], list: Row[]): string {
  const payer = c.payer_id ?? list.find((r) => r.category_id === c.category_id)?.carry_payer_id ?? null
  const who = payer === null ? '' : (meta.byId[payer]?.display_name ?? '')
  const amount = formatYen(c.amount)
  return who ? t('monthly.carriedItem', { name: c.name, amount, payer: who }) : `${c.name} ${amount}`
}

/**
 * 去账目页看这个分类**本期**的全部几笔 —— 面板上只显示得下一笔。
 * 带上范围（草稿 ＝ 还没出账的，翻旧账单 ＝ 那一张上的）：只带分类的话列出来的是
 * 这个分类的全部历史，几十笔房租里分不出本期到哪笔为止
 */
function openCategoryEntries(row: Row) {
  const scope = historic.value ? { statement: String(props.statementId) } : { unbilled: '1' }
  void router.push({ name: 'entries', query: { category: String(row.category_id), ...scope } })
}

function onInput(row: Row, e: Event) {
  if ((e as InputEvent).isComposing) return      // 输入法拼字中，等 compositionend
  const digits = digitsOf((e.target as HTMLInputElement).value)
  const n = yenOf(digits)
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

/**
 * 本来有值、被清空（或者填成 0）了 —— 保存时删掉那笔。软删，捞得回来。
 *
 * 判据认的是**值**不是空串：占位符就写着 0，等于在邀请用户填 0；
 * 而只认空串的话，在已录的行里打个 0 会走 PATCH amount_jpy=0，
 * 撞后端的「金额不能是 0」红在那儿，人只能全选删光才过得去。
 */
const willDelete = (row: Row) => row.entry_id !== null && valueOf(row) === 0

/**
 * 这一行的状态说明。**正常录好的不出声** —— 黑色实数本身就说明录了，
 * 五行里重复五次「已录」只是噪音。只有需要你注意的才说话。
 */
function stateText(row: Row): string {
  // 三条状态共用行头那**一个格子**，所以按「要不要用户动手」排，不是按判起来顺手排。
  // archived 原来抢在最前面，把下面两条要动手的全顶掉了 —— 而它恰恰是三条里唯一
  // 纯陈述的那条（钱留着是对的，不用管）。不说它也不行：点完「删掉这一项」
  // 这一行还杵在那儿，看上去就是没删掉
  // 只报「还有几笔没显示出来」。原来那句写全了整个来龙去脉，四十来个字，
  // 在 40px 高、右边还杵着输入框的一行里根本放不下，被省略号截掉大半 ——
  // 而这句话现在是个入口，点进去就看得到全部
  if (row.entry_count > 1) return t('monthly.duplicate', { n: row.entry_count - 1 })
  if (willDelete(row)) return t('monthly.willDelete')
  // 钱也已经删掉了就别再写「这笔还在」
  if (row.archived) {
    return row.entry_id !== null ? t('monthly.removedKeeps') : t('monthly.removedBare')
  }
  return ''                                       // 已录不出声；没录的也不出声，空框＝0
}
const stateClass = (row: Row) =>
  row.entry_count > 1
    ? 'text-warning'
    : willDelete(row)
      ? 'text-negative'
      : 'text-grey-6'   // 已归档；stateText 只在这三种情况下有字，别的情况不会调到这儿

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
/** 正在存的那几行（分类 id）。build() 重建时不许换掉它们 */
const saving = new Set<number>()

/**
 * 保存从哪儿来，决定撞上「要人拿主意」的情况时能不能问：
 *   'ask'   —— 人刚动过这一行（失焦、收起、点了「照上期」、点了冲突那句提示）：弹框问；
 *   'flush' —— 出账之前兜底存（BillView.doCut）：量级闸照样问（问的就是他刚填的数）；
 *              冲突的行不问也不写，留着 dirty —— 出账那边按「有没存上的」拦下；
 *   'leave' —— 离开这一屏：组件在卸载，什么都不问，存不上的最后列成一条不会自己消失的提示
 */
type SaveHow = 'ask' | 'flush' | 'leave'

function saveQueued(row: Row, how: SaveHow = 'ask'): Promise<void> {
  queue = queue.then(() => saveRow(row, how)).catch(() => {})
  return queue
}

async function saveRow(row: Row, how: SaveHow) {
  if (!row.dirty) return
  if (!row.rule_valid) {
    $q.notify({
      type: 'negative',
      message: `${row.name}: ${t('split.notBalanced', { n: formatYen(row.rule_diff) })}`,
      timeout: 5000,
    })
    return
  }
  // **翻旧账单时只许改金额。** 清空走 DELETE、重打走 POST，而 POST 建出来的是
  // statement_id=NULL 的新账目 —— 落进**当前草稿**，旧单子上那笔就此消失，
  // 屏幕上这一行却显示成「改好了」。组件顶上那句注释一直是这么写的，代码没兑现
  if (historic.value && (willDelete(row) || row.entry_id === null)) {
    row.text = row.amount === null ? '' : formatPlain(row.amount)
    row.dirty = false
    $q.notify({ type: 'warning', message: t('monthly.historicAmountOnly'), timeout: 5000 })
    return
  }
  let stale = false
  // 从这儿起到存完（包括等人在对话框里拿主意）都算「正在存」：build() 不许换掉这个对象，
  // 否则人选完、写回的是一个已经不在屏幕上的旧对象
  saving.add(row.category_id)
  try {
    // 服务器上这一项在我没看见的时候变了（build 认出来的）：**不自动写**，问人用哪个
    if (row.conflict && (how !== 'ask' || !(await askConflict(row)))) return
    for (;;) {
      const r = await sendRow(row, how)
      if (r === 'stale') stale = true
      if (r !== 'again') break
    }
  } finally {
    saving.delete(row.category_id)
  }
  // 版本冲突：手里这份 version 已经过期，不重新取的话再点多少次都是同一个 409。
  // **要等这一行出了 saving 再取**：还在 saving 里的话 build() 原样留着这个对象，
  // 过期的 version 一点不变（原来在 catch 里直接 load，等于白取）。
  // 取回来 build() 会把它认成「被人改过」：和我填的一样就采用，不一样就标出来让人选
  if (stale) await load().catch(() => {})
}

/**
 * 发一次请求。返回 'again' ＝ 撞了量级闸、人确认了，带着确认再发一次；
 * 'stale' ＝ version 过期（409），要重新取。
 */
async function sendRow(row: Row, how: SaveHow): Promise<'done' | 'again' | 'stale'> {
  const value = valueOf(row)
  // 合计的底数是后端给的那个，而它只在 load() 时刷新。存成功之后这一行的差额
  // 从 pending 里消失、底数却没动 —— 合计当场掉回挂载时的数（删除时则不减）。
  // 在这儿把底数跟着改：新增 before=0、改金额取差、删除 row.amount=null 就是减掉
  const before = row.amount ?? 0
  // 这一次发出去的是什么。存完**只有这一行没再被改过**才清 dirty（core/monthlyRows.settleSaved）
  const sent = saveSig(row)
  // 人确认过「就是这个数」、框里也还是它，才带确认
  const confirm = row.jump_ok === value ? { confirm_jump: true } : {}
  let jump: Row['jump'] = null
  busy.value = true
  try {
    if (willDelete(row)) {
      // 带上 version：这一笔要是刚被出账带走了（或者被人改过），不能把刚发进群里的
      // 那张单子上的账删掉 —— 409 之后走下面 version_conflict 那条路重载，
      // build() 会把被带走的那一行认出来、提示一句
      await api.del(`/api/entries/${row.entry_id}?version=${row.version}`)
      // 留着这笔的分摊和日期：清空再重打是「改个金额」，不该顺手把分摊换掉。
      // row.rule 本来就是这笔的规则（预览的起步规则），留着不动
      row.deleted_rule = row.rule
      row.deleted_date = row.date
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
            ? {
                rule: row.rule_override,
                // 和预览同一批人：这一笔**自己的**参与人，不是今天在籍的人
                member_ids: (rowMembers.value.get(row.category_id) ?? meta.activeMembers).map((m) => m.id),
              }
            : {}),
          ...confirm,
        },
      )
      row.version = saved.version
      row.amount = saved.amount_jpy
    } else if (value > 0) {
      const body = {
        kind: 'expense',
        date: row.deleted_date ?? data.value!.default_date,
        amount_jpy: value,
        payer_id: payerOf(row),
        category_id: row.category_id,
        title: row.name,
        // **没动过分摊也要把预览那条发上去**：没录的行是从上期那一笔（或者刚删掉的
        // 那一笔）的分摊起步的，发 null 的话后端落成分类默认 —— 屏幕上是
        // 45,000/40,000/35,000，库里是均分
        rule: row.rule_override ?? untouchedRule(row.rule),
        // 和分摊预览用的是同一批人，避免预览与落库分摊到不同的人头上
        member_ids: meta.activeMembers.map((m) => m.id),
      }
      const sig = JSON.stringify(body)
      if (!row.post_key || row.post_sig !== sig) {
        row.post_key = newClientKey()
        row.post_sig = sig
      }
      const saved = await api.post<{ id: number; version: number; amount_jpy: number }>(
        '/api/entries',
        { ...body, ...confirm, client_key: row.post_key },
      )
      row.post_key = null
      row.entry_id = saved.id
      row.version = saved.version
      row.amount = saved.amount_jpy
      row.payer_id = body.payer_id   // 记下的就是这个人垫的，别再按回退链去猜
      row.deleted_rule = null
      row.deleted_date = null
    } else {
      row.dirty = false          // 空着又没录过：没什么可存的
      return 'done'
    }
    if (data.value) {
      data.value.total += (row.amount ?? 0) - before
      // 缓存里的 rows 也得跟着改。只改 total 的话，缓存里躺着的是
      // 「合计是新的、每一行还是旧的」—— 而 onMounted 正是拿它做首屏：
      // 金额框空着、合计却有钱
      const cached = data.value.rows.find((r) => r.category_id === row.category_id)
      if (cached) {
        cached.amount = row.amount
        cached.entry_id = row.entry_id
        cached.version = row.version
        // 垫付人也跟着（和服务器那份一个口径：没录就没有）—— 不改的话从缓存重新挂载，
        // 这一行又退回去猜
        cached.payer_id = row.entry_id === null ? null : row.payer_id
      }
    }
    // 请求在路上时这一行又被改了（重打了金额、点了「照上期」、动了分摊）：
    // 不清 dirty，排着的那次接着存最新的；没排着的照常标红，收起/离屏/出账时存上
    settleSaved(row, sent)
    row.jump = null
    row.jump_ok = null
    bills.monthlyWritten()       // 在这之前发出去的 /monthly 回来就是旧的了
    emit('saved')                // 账单总额/转账方案跟着刷新
    // 账目页那份列表是另一个 store 管的。这一屏从头到尾直接打 /api/entries，
    // 不通知它的话，刚录的固定费在账目页整个 session 都看不见
    void ledger.refresh().catch(() => {})
  } catch (e) {
    if (e instanceof ApiError && e.code === 'amount_jump') {
      // 量级闸：和上期差出好几倍（多打/少打一个 0）。这不是「存失败」，是要人确认一句 ——
      // 不弹红字。离屏时问不了，留着 dirty，由最后那条提示列出来
      row.jump = { ratio: e.detail.ratio, direction: e.detail.direction }
      if (how !== 'leave') jump = row.jump
    } else {
      // 失败就留在 dirty，输入原样保着，人能看见也能改了重来
      $q.notify({
        type: 'negative',
        message: `${row.name}: ${errorText(e)}`,
        timeout: 5000,
      })
      if (e instanceof ApiError && e.code === 'version_conflict') return 'stale'
    }
  } finally {
    busy.value = false
  }
  if (!jump || !(await confirmJump(row, value, jump))) return 'done'
  row.jump_ok = value
  // 框里已经不是人确认的那个数了（对话框是模态的，不该发生）：不替他发
  return row.dirty && valueOf(row) === value ? 'again' : 'done'
}

/**
 * 冲突的这一行用哪个。两个按钮都得点一下才关（persistent）：点空白处就关的话，
 * 分不清是「用刚记的」还是「先不管」，而「用刚记的」会丢掉人的输入。
 *   用我这边的 —— 写的是服务器上现在那一笔、带着它现在的 version（build 时已经换上），
 *                 只改金额（和动过的分摊），垫付人不动；
 *   用刚记的   —— 丢掉手里的输入。
 * 返回 true ＝ 接着把我这边的存上
 */
function askConflict(row: Row): Promise<boolean> {
  const theirs = formatYen(row.conflict?.amount ?? 0)
  const value = valueOf(row)
  const mine = value ? formatYen(value) : t('monthly.conflictDeleteWhat')
  return new Promise((resolve) => {
    $q.dialog({
      message: t('monthly.conflictAsk', { name: row.name, theirs, mine }),
      persistent: true,
      ok: { label: t('monthly.conflictMine'), flat: true },
      cancel: { label: t('monthly.conflictTheirs', { amount: theirs }), flat: true },
    })
      .onOk(() => {
        row.conflict = null
        resolve(true)
      })
      .onCancel(() => {
        row.text = row.amount === null ? '' : formatPlain(row.amount)
        row.dirty = false
        row.rule_override = null
        row.conflict = null
        row.jump = null
        row.jump_ok = null
        resolve(false)
      })
  })
}

/**
 * 量级闸问一句「真是这个数？」。倍数是后端拿本期这一项的合计和上次出账时的比出来的。
 * 点空白处关掉＝回去改：留在 dirty、框还红着，什么都没写
 */
function confirmJump(row: Row, value: number, jump: NonNullable<Row['jump']>): Promise<boolean> {
  const n = jumpFactor(jump.ratio)
  const down = jump.direction === undefined ? Number(jump.ratio) < 1 : jump.direction === 'down'
  const p = { name: row.name, amount: formatYen(value), n }
  const message = n === null ? t('errors.amount_jump') : down ? t('monthly.jumpDown', p) : t('monthly.jumpUp', p)
  return new Promise((resolve) => {
    $q.dialog({
      message,
      ok: { label: t('monthly.jumpOk'), flat: true },
      cancel: { label: t('monthly.jumpFix'), flat: true },
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false))
  })
}

/** 出账之前把还没存的行兜底存掉（BillView.doCut 调它，之后看 dirtyCount） */
async function flush() {
  await eachLive(() => rows.value, (row) => saveQueued(row, 'flush'))
}

/**
 * 离开这一屏：兜底存一遍（比如填完直接切了 Tab）。**还存不上的必须留下一句不会自己消失的话。**
 *
 * 原来存不上只有那条 5 秒的红字，回来时这一行是空框、标题写着「改完自动保存」——
 * 人以为已经填过了。不在回来时把它恢复成 dirty：恢复出来的数会在失焦/离屏时自动写，
 * 而那时它可能已经过期（中间出过账、室友记过同一项），等于替人写钱
 */
let leaving = false
async function leave() {
  leaving = true
  await eachLive(() => rows.value, (row) => saveQueued(row, 'leave'))
  const left = rows.value.filter((r) => r.dirty)
  if (!left.length) return
  const list = left.map((r) => {
    const v = valueOf(r)
    const what = `${r.name} ${v ? formatYen(v) : t('monthly.willDelete')}`
    if (r.conflict) return what + t('monthly.leftConflict', { amount: formatYen(r.conflict.amount ?? 0) })
    if (r.jump) return what + t('monthly.leftJump')
    return what
  })
  $q.notify({
    type: 'warning',
    timeout: 0,
    message: t('monthly.leftUnsaved', { list: list.join('、') }),
    actions: [{ icon: 'close', color: 'white', round: true }],
  })
}
onBeforeUnmount(() => void leave())

// 整页重载（换 chunk）不跑上面那个 leave()：正在存、在等人答量级闸 / 冲突的框、存失败还 dirty 的行，
// 都得挡着它（src/unsaved，router.onError 看）。saving 覆盖了询问框开着的那段：行一直留在里面直到人答完
onBeforeUnmount(holdReload(() => saving.size > 0 || dirtyCount.value > 0))

/**
 * 删掉一项固定费 —— **归档，不是真删**。
 * 那个分类底下可能已经有历史账目，真删外键会挡住，账目页也会失名。
 */
function removeItem(row: Row) {
  const extra =
    row.amount !== null
      ? ` ${t('monthly.removeKeepsEntry', { amount: formatYen(row.amount) })}`
      : ''
  // 「确定」连点两下 onOk 会跑两遍 —— 第二遍直接丢掉，不然就是两条「已删掉」
  let fired = false
  $q.dialog({
    title: t('monthly.removeItem'),
    message: t('monthly.removeConfirm', { name: row.name }) + extra,
    cancel: true,
  }).onOk(async () => {
    if (fired) return
    fired = true
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
              try {
                await api.patch(`/api/categories/${row.category_id}`, { archived: false })
                await meta.load()
                await load()
              } catch (e) {
                $q.notify({ type: 'negative', message: errorText(e) })
              }
            },
          },
        ],
      })
    } catch (e) {
      $q.notify({ type: 'negative', message: errorText(e) })
    }
  })
}


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
      // 缓存里那一行的 version 和垫付人跟着改（理由同 sendRow）：面板重新挂载时拿它建行，
      // 留着旧 version 的话下一次改金额先撞一个 409；留着旧垫付人，行头就写回原来那个人
      const cached = data.value?.rows.find((r) => r.category_id === row.category_id)
      if (cached) {
        cached.version = e.version
        cached.payer_id = payerId
      }
      bills.monthlyWritten()
      emit('saved')             // 谁垫的变了，账单上的应收应付跟着变
      void ledger.refresh().catch(() => {})   // 流水那一行的付款人也得换
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: errorText(e), timeout: 5000 })
    await load().catch(() => {})
  } finally {
    busy.value = false
  }
}


// flush / dirtyCount：出账之前账单页要先把这里没存完的存掉、再看还有没有存不上的（BillView.doCut）
defineExpose({ flush, dirtyCount })
</script>

<style scoped>
/* 标题条上的合计：跟下面每一行的金额同字号、同一条竖线 */
.section-head .amount { font-size: var(--nagaya-fee-amount-fs); font-variant-numeric: tabular-nums; }
/* 输入框里的数字离框右边 10px（框的内边距），合计往里让同样的 10px，
   上下才是同一条竖线。已出账那页的只读列表也让了这 10px（BillView） */
.section-head .amount { padding-right: 10px; }
/* 金额列对齐：右边距 ＝ 行内边距 16 + 展开箭头 24 + 这一格的左内边距。
   要凑到 --nagaya-fee-amount-gap，这里就该留下减掉那 40px 的部分 */
.wrap :deep(.q-expansion-item .q-item__section--side:last-child) {
  padding-left: calc(var(--nagaya-fee-amount-gap) - 40px);
}
.amount-input {
  width: 116px;
  height: 36px;
  padding: 0 10px;
  border: none;
  border-radius: var(--nagaya-r-sm);
  outline: none;
  background: var(--nagaya-fill);
  text-align: right;
  font-family: inherit;
  font-size: var(--nagaya-fee-amount-fs);
  font-variant-numeric: tabular-nums;
  /* **不能用 inherit**：会继承 Quasar 的次级文字色，跟占位只差一档。
     而「正常已录不显示标签」的全部理由就是「实数本身看得出录了」—— 前提是它真的够黑 */
  color: var(--nagaya-ink);
  transition: box-shadow 0.15s;
}
.amount-input:focus { box-shadow: inset 0 0 0 1.5px var(--nagaya-accent); }

/* 灰色占位＝还没填，不是值。改过的才变实色 */
.amount-input::placeholder { color: var(--nagaya-ink-5); }
/* **没存上的样子不能借主色。** 原来是蓝下划线 + 加粗，看着像「存好了」，
   而这一屏标着「改完自动保存」—— 人扫一眼就退出去了，下次打开值没了。
   现在是红的：和旁边那句「{n} 项没存上」说同一件事 */
.amount-input.dirty { box-shadow: inset 0 0 0 1.5px var(--nagaya-neg); color: var(--nagaya-neg); }
.amount-input.to-delete { color: var(--nagaya-neg); text-decoration: line-through; }
/* 320 宽（SE 一代）：输入框收窄一点，名字和垫付人才露得出来；
   「改完自动保存」这句平时的状态收起来，标题才不会折成两行 ——
   折了的话这一块比已出账那页高一截，两页又不齐了。存失败、正在存照样显示 */
@media (max-width: 359px) {
  .amount-input { width: 96px; }
  .save-state.idle { display: none; }
}
/* 块尾那一行。已出账那页是同高的空占位，高度写在同一个变量里 */
/* 上下各让出 8px 的内边距再用负外边距收回来：排版一点不变，但裁剪框变高了 ——
   里面「本期有 N 笔」那个链接的点击区才伸得出去（overflow: hidden 会连点击一起裁掉） */
.name-line { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 8px 0; margin: -8px 0; }
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
/* 「照上期 ¥…」：展开区最上面一颗药丸，**靠右、和行头那个金额框右边对齐** ——
   点了填的就是那一格。金额框右边离行尾 --nagaya-fee-amount-gap，展开区自己已经有 16px 内边距 */
.carry-row {
  display: flex;
  justify-content: flex-end;
  padding-right: calc(var(--nagaya-fee-amount-gap) - 16px);
  margin-bottom: 12px;
}
.carry-chip {
  border: none;
  border-radius: var(--nagaya-r-pill);
  padding: 6px 12px;
  background: var(--nagaya-accent-bg);
  color: var(--nagaya-accent);
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
}
.carry-chip:disabled { opacity: 0.5; }
/* 「以后照上期？」：和「照上期」同一个位置、同一个形状，但不用主色 —— 它不记钱，只是开个开关 */
.hint-chip {
  border: none;
  border-radius: var(--nagaya-r-pill);
  padding: 6px 12px;
  background: var(--nagaya-fill);
  color: var(--nagaya-ink);
  font-family: inherit;
  cursor: pointer;
}
.hint-chip:disabled { opacity: 0.5; }
/* 「草稿里有一笔…是不是它？」：点了去那一笔，长得要像能点 */
.elsewhere-link {
  display: block;
  border: none;
  background: none;
  padding: 0;
  font-family: inherit;
  text-align: left;
  text-decoration: underline;
  cursor: pointer;
}
</style>
