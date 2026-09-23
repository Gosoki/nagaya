<!--
  当前账单上的「固定费」—— 房租/电费/燃气/水费/网费 在这里一次填完。

  账单来了随时填，不用等到出账单。点「出账单」只是划一条线，把这一刻之前记的
  全部归到那张单子上。

  ## 两条要命的约束

  1. **不填就是 0，而且照样能出账。**
     这一屏不摆「上期是多少」当参考 —— 参考值就在输入框那个位置，
     长得跟亲手填的没两样，某个月忘了改就带着上月的电费把账单发出去了。
     每期真的不变的项（房租这种）去设置里开「和上期一样」：那一行上有个
     「照上期」，**人点一下**才记成黑字实数（出账对话框里也有一个勾）。
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
              <!-- 「和上期一样」就放在这一行上，点了才记（记上的金额当场出现在右边的框里，
                   出账对话框里也写着多少）。字只写「照上期」：带上金额这一行放不下，会被省略号吃掉。
                   不另起一条横条 —— 那条会把这一块撑高，出账前后两页就不一样高了 -->
              <button
                v-if="!stateText(row) && isCarryReady(row)"
                class="state carry-chip"
                :disabled="carrying"
                @click.stop="carry([row])"
                :aria-label="`${t('monthly.carryOne')} ${formatYen(row.carry_amount ?? 0)}`"
              >{{ t('monthly.carryOne') }}</button>
              <!-- 开了开关却照抄不了（垫付人搬走了、来了新室友）：一直写在这儿，填了就消失 -->
              <span
                v-else-if="!stateText(row) && isCarryBlocked(row)"
                class="state text-warning"
              >{{ t('monthly.carryStale') }}</span>
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
import type { Category, Member, MonthlyData, MonthlyRow } from 'src/api/types'
import MemberPicker from 'src/components/MemberPicker.vue'
import SplitEditor from 'src/components/SplitEditor.vue'
import { newClientKey } from 'src/clientKey'
import { seedToRatio } from 'src/core/seed'
import { todayJst } from 'src/date'
import { digitsOf } from 'src/digits'
import { formatYen } from 'src/i18n'
import { useBills } from 'src/stores/bills'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

interface Row extends MonthlyRow {
  text: string
  dirty: boolean
  rule_override: Record<string, unknown> | null
  rule_valid: boolean
  rule_diff: number
  /** 已录账目的原始付款人。面板不改它，只拿来喂给分摊预览 */
  payer_id: number | null
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

/**
 * 这一笔算谁垫的。按「谁最有发言权」排：
 *   1. 本期已经录了 → 就是当初记的那个人，谁也别动它
 *   2. 这一项定过默认垫付人 → 用它（房租永远从同一张卡扣）
 *   3. 上期那一笔是谁垫的（和「和上期一样」同一个口径）
 *   4. 全局的「默认垫付人」设置（他今天还住在这儿的话）
 *   5. 当前登录的人
 *
 * 少了第 2 条的话，这一屏就是「谁填的算谁」：别人刷的卡被随手填进去，
 * 账本当场错一整笔房租的钱，而屏幕上一点提示都没有。
 */
function payerOf(row: Row): number | null {
  if (row.payer_id !== null) return row.payer_id
  // 翻旧账单时，已录的那几行**宁可不显示垫付人，也别显示一个猜的**：
  // 后面两级回退给的是「今天的默认垫付人」，跟当初谁真掏的钱没关系 ——
  // 而这一屏正是靠这个名字告诉人「这笔房租是谁垫的」
  if (historic.value && row.entry_id !== null) return null
  // 分类上定的默认垫付人已经搬走了：跳过他往下退（和记一笔那边同一个口径）。
  // 照用的话，手填的房租就记成了已经不住这儿的人垫的。设置里他会标红
  const living = (id: number | null | undefined) =>
    id != null && meta.activeMembers.some((m) => m.id === id) ? id : null
  return living(row.default_payer_id) ?? row.last_payer_id ?? fallbackPayerId.value
}

const payerName = (row: Row) => {
  const id = payerOf(row)
  return id === null ? '' : (meta.byId[id]?.display_name ?? '')
}

const formatPlain = (n: number) => n.toLocaleString('en-US')
const valueOf = (row: Row) => Number(digitsOf(row.text)) || 0

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
  data.value = d
  rows.value = d.rows.map((r) => {
    let held = keep.get(r.category_id)
    // 这一行正在存（请求还在路上）：**原样留着这个对象**。换成新对象的话，
    // 存完的结果写回的是旧对象，新的这一行还是 dirty、没有 entry_id ——
    // 下一次失焦或离屏就把同一笔钱再 POST 一遍
    if (held && saving.has(r.category_id)) return held
    // **手里那一笔被出账带走了**（有人在另一台上出了账）：这一行现在是新一期的
    // 空行。没存上的输入不能留 —— 留着的话，下一次失焦/离开这一屏就把它当成
    // 新的一笔记进下一期，而人以为自己改的是刚才那笔
    if (held?.dirty && held.entry_id !== null && held.entry_id !== r.entry_id) {
      taken.push(r.name)
      held = undefined
    }
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
      payer_id: null,
      deleted_rule: held?.deleted_rule ?? null,
      deleted_date: held?.deleted_date ?? null,
      post_key: held?.dirty ? held.post_key : null,
      post_sig: held?.dirty ? held.post_sig : '',
    })
  })
  if (taken.length) {
    $q.notify({ type: 'warning', timeout: 6000, message: t('monthly.takenByCut', { names: taken.join('、') }) })
  }
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
  // 借不到就自己取 —— 但必须**跟当前这张单子对齐**。原来打的是全局最近 200 笔，
  // 翻半年前那张单子时一条都对不上，于是每一行的垫付人都退回「今天的默认垫付人」
  const url = historic.value
    ? `/api/entries?statement_id=${props.statementId}&limit=1000`
    : '/api/entries?unbilled_only=true&limit=1000'
  const entries = shared ?? (await api.get<{ id: number; payer_id: number }[]>(url))
  const byId = new Map(entries.map((e) => [e.id, e.payer_id]))
  for (const r of rows.value) {
    if (r.entry_id !== null) r.payer_id = byId.get(r.entry_id) ?? null
  }
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
    void hydratePayers()
  },
)

onMounted(() => {
  // 缓存先上屏，再后台校正。load() 本身会保留还没保存的输入，所以校正不会抹掉手输的值
  const cached = bills.monthly[cacheKey.value]
  if (cached) {
    build(cached)
    void hydratePayers()
  }
  void load()
})

/**
 * 这一行能不能「照上期」一键记上。正在手填的行不算 —— 人已经在填了，
 * 再给一个按钮只会记出两笔（后端也只记传过去的那几项）
 */
const isCarryReady = (r: Row) =>
  !historic.value && Boolean(r.carry_amount) && r.entry_id === null && !r.dirty && !r.text
const isCarryBlocked = (r: Row) =>
  !historic.value && Boolean(r.carry_blocked) && r.entry_id === null && !r.dirty && !r.text
const carrying = ref(false)

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
    const { created, failed } = await api.post<{
      created: { name: string; amount: number }[]
      failed: { name: string }[]
    }>('/api/monthly/carry', { category_ids: list.map((r) => r.category_id) })
    bills.monthlyWritten()
    await load()
    if (created.length) {
      emit('saved')
      void ledger.refresh().catch(() => {})
      $q.notify({
        type: 'info',
        timeout: 6000,
        message: t('monthly.carried', {
          list: created.map((c) => `${c.name} ${formatYen(c.amount)}`).join('、'),
        }),
      })
    }
    // **搬不过来的也必须说出来。** 这个开关存在的全部理由是「自动记的钱要看得见」，
    // 那么「自动记账已经停了」同样要看得见 —— 原来这里是个空 catch，
    // 有人搬走之后它就一声不吭地失效了，而屏幕上只是几个空框
    if (failed.length) {
      $q.notify({
        type: 'warning',
        timeout: 8000,
        message: t('monthly.carryFailed', { list: failed.map((f) => f.name).join('、') }),
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

/** 去账目页看这个分类本期的全部几笔 —— 面板上只显示得下一笔 */
function openCategoryEntries(row: Row) {
  void router.push({ name: 'entries', query: { category: String(row.category_id) } })
}

function onInput(row: Row, e: Event) {
  if ((e as InputEvent).isComposing) return      // 输入法拼字中，等 compositionend
  const digits = digitsOf((e.target as HTMLInputElement).value)
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

function saveQueued(row: Row): Promise<void> {
  queue = queue.then(() => saveRow(row)).catch(() => {})
  return queue
}

async function saveRow(row: Row) {
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
  const value = valueOf(row)
  // 合计的底数是后端给的那个，而它只在 load() 时刷新。存成功之后这一行的差额
  // 从 pending 里消失、底数却没动 —— 合计当场掉回挂载时的数（删除时则不减）。
  // 在这儿把底数跟着改：新增 before=0、改金额取差、删除 row.amount=null 就是减掉
  const before = row.amount ?? 0
  busy.value = true
  saving.add(row.category_id)
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
        { ...body, client_key: row.post_key },
      )
      row.post_key = null
      row.entry_id = saved.id
      row.version = saved.version
      row.amount = saved.amount_jpy
      row.deleted_rule = null
      row.deleted_date = null
    } else {
      row.dirty = false          // 空着又没录过：没什么可存的
      return
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
      }
    }
    row.dirty = false
    row.rule_override = null
    bills.monthlyWritten()       // 在这之前发出去的 /monthly 回来就是旧的了
    emit('saved')                // 账单总额/转账方案跟着刷新
    // 账目页那份列表是另一个 store 管的。这一屏从头到尾直接打 /api/entries，
    // 不通知它的话，刚录的固定费在账目页整个 session 都看不见
    void ledger.refresh().catch(() => {})
  } catch (e) {
    // 失败就留在 dirty，输入原样保着，人能看见也能改了重来
    $q.notify({
      type: 'negative',
      message: `${row.name}: ${errorText(e)}`,
      timeout: 5000,
    })
    // 版本冲突：手里这份 version 已经过期，不重新取的话再点多少次都是同一个 409。
    // load() 会保留还没保存的输入，所以刷一下不会把人填的东西抹掉
    if (e instanceof ApiError && e.code === 'version_conflict') {
      await load().catch(() => {})
    }
  } finally {
    saving.delete(row.category_id)
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
      ? ` ${t('monthly.removeKeepsEntry', { amount: formatYen(row.amount) })}`
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
      emit('saved')             // 谁垫的变了，账单上的应收应付跟着变
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
   里面「照上期」那颗小按钮的点击区才伸得出去（overflow: hidden 会连点击一起裁掉） */
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
/* 「照上期 ¥…」：一颗能点的小药丸。纵向内边距不许撑高这一行（行高交给名字的 strut） */
.carry-chip {
  border: none;
  border-radius: var(--nagaya-r-pill);
  padding: 4px 8px;
  margin-top: -4px;
  margin-bottom: -4px;
  background: var(--nagaya-accent-bg);
  color: var(--nagaya-accent);
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
}
.carry-chip:disabled { opacity: 0.5; }
/* 看着只有 24px 高，点击区上下各多 8px —— 这颗按钮点下去是记钱 */
.carry-chip { position: relative; }
.carry-chip::after { content: ''; position: absolute; inset: -8px -4px; }
</style>
