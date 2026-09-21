<!--
  一张账单的全貌 —— SPEC F6。**看哪一张由 viewKey 决定，不看路由**：
  三个页签是同一个地址上的状态切换，点页签不会改地址、也不会重建这个组件。

  账单只负责展示：余额是全局累计的，这里拆成「期初结转 + 本期发生 + 本期已收付」。
  所以「赊账」不需要任何额外机制 —— 少付的部分自然以「上期结转」出现在下一张账单上。

  一键复制的文本是直接贴进 LINE 群的，所以格式按等宽对齐排，手机上看着是一张表。
-->
<template>
  <div class="page">
    <!-- 冷启动时别急着喊「这儿是空的」：请求还在飞就先什么都不显示，
         否则每次头一回进来都要先闪一句「本期还没有账目」 -->
    <div v-if="!bill && !bills.pending" class="text-center text-grey-6 q-mt-xl">
      {{ isOpenTab ? t('bill.noOpen') : t('bill.noPeriod') }}
    </div>

    <!-- 用 v-if 而不是 v-else：上面那句多了个「还在加载」的条件，
         两个都不成立时（冷启动的头几十毫秒）这一页就该是干净的 -->
    <template v-if="bill">
      <div class="head bill-section q-pa-md">
        <div class="row items-baseline">
          <div class="text-subtitle1 text-weight-medium">
            {{ bill.is_draft ? t('bill.draft') : bill.label }}
          </div>
          <q-space />
          <div class="text-caption text-grey-6 q-mr-xs">{{ t('bill.total') }}</div>
          <div class="text-h6">{{ formatYen(bill.total_expense) }}</div>
        </div>
        <div v-if="!bill.is_draft && bill.settled" class="row items-center q-gutter-xs q-mt-xs">
          <q-badge color="positive" :label="t('bill.settledBadge')" />
        </div>
        <div class="row items-baseline text-caption text-grey-6">
          <div v-if="bill.covers_from">
            {{ t('bill.coversRange', { from: bill.covers_from, to: bill.covers_to }) }}
          </div>
          <q-space />
          <!-- 草稿账单没必要喊「未结清」：还没出账当然没结清，天天亮着就成了噪音。
               报笔数更有用；出过的账单才说结算状态 -->
          <div v-if="bill.is_draft">
            <span v-if="bill.prev_label" class="q-mr-sm">
              {{ t('bill.lastCut', { label: bill.prev_label }) }}
            </span>
            {{ t('bill.entryCount', { n: bill.entry_count }) }}
          </div>
          <div v-else class="text-warning">{{ dueText }}</div>
        </div>

        <!-- 自己那笔摆在最显眼处。读账单的人要的就是这一个数字，
             埋在半屏之下的话，他先看到的全是别人的录入框 -->
        <div v-if="mine" class="mine q-mt-sm" :class="mine.closing < 0 ? 'owe' : 'owed'">
          {{ mineText }}
        </div>
      </div>
      <div class="hidden">
        <!-- 不锁历史，但改动必须可见：否则下一张的「上期结转」没人解释得清 -->
        <q-banner v-if="bill.edited_after_cut" dense class="bg-orange-1 text-orange-9 q-mt-sm rounded-borders">
          {{ t('bill.editedAfterCut', {
            n: bill.edited_after_cut.count,
            frozen: formatYen(bill.edited_after_cut.frozen_total ?? 0),
            live: formatYen(bill.edited_after_cut.live_total),
          }) }}
        </q-banner>
      </div>

      <!-- 本期固定费：出账单时顺手把家賃/水电煤网填了，账单跟着重算 -->
      <MonthlyFixed v-if="bill.is_draft" @saved="load" />

      <!-- 已出的账单没有那个面板（它只管当前草稿），可固定费往往是这张单子上最大的
           一笔钱。不摆出来的话，点进一张旧账单只看得见日用品，家賃 12 万凭空消失。

           整段只有一个入口，通向固定费那一屏 —— 不给每行挂一个箭头去单笔编辑页：
           固定费是一整屏一起看的东西，拆成一笔笔既多按钮又不好改。 -->
      <div v-else class="bill-section">
        <q-item clickable dense class="section-head" @click="openMonthly">
          <q-item-section>{{ t('monthly.title') }}</q-item-section>
          <q-item-section side class="amount text-grey-9">{{ formatYen(monthlyTotal) }}</q-item-section>
          <q-item-section side><q-icon name="chevron_right" color="grey-5" size="18px" /></q-item-section>
        </q-item>
        <!-- 行的尺寸照着未出账那页的可编辑面板来：一样的行高、一样的金额字号、
             一样的右边距。两页看的是同一件事，来回切时这一块不该变样 -->
        <q-list v-if="monthlyEntries.length" separator class="monthly-list">
          <q-item v-for="e in monthlyEntries" :key="e.id" dense>
            <q-item-section avatar>
              <q-avatar size="30px" :style="{ background: colorOfEntry(e) }" text-color="white">
                <q-icon :name="iconOfEntry(e)" size="16px" />
              </q-avatar>
            </q-item-section>
            <!-- 只写分类名，不写备注：固定费这一屏（可编辑面板那边）根本没有
                 填备注的入口，这里却显示一条，等于凭空冒出个改不了的字段 -->
            <q-item-section>
              <q-item-label>{{ categoryOfEntry(e)?.name ?? labelOfEntry(e) }}</q-item-label>
            </q-item-section>
            <q-item-section side class="amount text-grey-9">{{ formatYen(e.amount_jpy) }}</q-item-section>
          </q-item>
        </q-list>
        <!-- 未出账那页这个位置是「加一项固定费」。已出的账单加不了东西，
             拿一行同高的空占位顶上 —— 两页的这一块于是一样高、一样收口 -->
        <div v-if="monthlyEntries.length" class="fee-foot" aria-hidden="true"></div>
        <div v-else class="text-caption text-grey-6 q-px-md q-pb-md">{{ t('monthly.noneBilled') }}</div>
      </div>

      <!-- 固定费之下，把这期其他的开销也摆出来：
           不然账单上只看得见固定项，日用品/食費那些钱是从哪来的就说不清 -->
      <!-- .others 这个 class 是 E2E 用来指「本期其他那一块」的，别随手删 -->
      <div class="bill-section others">
        <q-item dense class="section-head">
          <q-item-section>{{ t('bill.others') }}</q-item-section>
        </q-item>
        <q-list v-if="others.length" separator>
          <q-item v-for="e in others" :key="e.id" dense clickable @click="editEntry(e.id)">
            <q-item-section avatar>
              <q-avatar size="30px" :style="{ background: colorOfEntry(e) }" text-color="white">
                <q-icon :name="iconOfEntry(e)" size="16px" />
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ labelOfEntry(e) }}</q-item-label>
              <q-item-label caption>
                {{ e.date.slice(5) }} · {{ meta.byId[e.payer_id]?.display_name }}
              </q-item-label>
            </q-item-section>
            <q-item-section side :class="e.amount_jpy < 0 ? 'text-positive' : 'text-grey-9'">
              {{ formatYen(e.amount_jpy) }}
            </q-item-section>
            <q-item-section side><q-icon name="chevron_right" color="grey-5" size="18px" /></q-item-section>
          </q-item>
        </q-list>
        <div v-else class="text-caption text-grey-6 q-px-md q-pb-md">{{ t('bill.othersEmpty') }}</div>
      </div>

      <!-- .per-member 是 E2E 用来指「每人那一块」的锚点，别随手删 -->
      <div class="bill-section per-member">
        <q-item dense class="section-head">
          <q-item-section>{{ t('bill.perMember') }}</q-item-section>
        </q-item>
        <q-list separator>
        <q-item
          v-for="row in bill.members"
          :key="row.member_id"
          :class="{ 'bg-blue-1': row.member_id === auth.me?.id }"
        >
          <q-item-section avatar>
            <q-avatar size="30px" :style="{ background: colorOf(row.member_id) }" text-color="white">
              {{ nameOf(row.member_id).slice(0, 1) }}
            </q-avatar>
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ nameOf(row.member_id) }}</q-item-label>
            <q-item-label caption>
              {{ t('bill.owed') }} {{ formatYen(row.owed) }}
              <span v-if="row.paid"> · {{ t('bill.paid') }} {{ formatYen(row.paid) }}</span>
              <span v-if="row.transferred_out"> · {{ t('bill.prepaid') }} {{ formatYen(row.transferred_out) }}</span>
              <span v-if="row.opening"> · {{ t('bill.carried') }} {{ formatYen(row.opening) }}</span>
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="text-weight-medium" :class="row.closing < 0 ? 'text-negative' : 'text-positive'">
              {{ row.closing === 0 ? t('bill.settled') : formatYen(Math.abs(row.closing)) }}
            </div>
            <div v-if="row.closing !== 0" class="text-caption text-grey-6">
              {{ row.closing > 0 ? t('bill.toReceive') : t('bill.toPay') }}
            </div>
          </q-item-section>
        </q-item>
        </q-list>
      </div>

      <div>
        <q-item dense class="section-head">
          <q-item-section>
            {{ bill.transfers.length ? t('bill.plan', { n: bill.transfers.length }) : t('bill.planEmpty') }}
          </q-item-section>
        </q-item>
        <div class="q-px-md q-pb-md">
        <q-card v-for="(tr, i) in bill.transfers" :key="i" flat bordered class="q-mb-sm">
          <q-card-section class="row items-center q-py-sm q-px-md">
            <div class="col">
              <div class="text-caption text-grey-7">
                {{ nameOf(tr.from_id) }}
                <q-icon name="arrow_forward" size="13px" class="q-mx-xs" />
                {{ nameOf(tr.to_id) }}
              </div>
              <div class="text-subtitle1 text-weight-medium">{{ formatYen(tr.amount) }}</div>
            </div>
<!-- 转出方和转入方看到的是同一个「已完成」，记的也是同一笔。
                 **跟这笔没关系的人不显示按钮**：原来对所有人显示「已收到」，
                 Kan 一点就替 Go 确认了收款，而 Go 那边钱还没到 -->
            <q-icon
              v-if="bill.settled_transfers[i]"
              name="check_circle"
              color="positive"
              size="24px"
            />
            <q-btn
              v-else-if="auth.me?.id === tr.to_id || auth.me?.id === tr.from_id"
              dense
              color="primary"
              no-caps
              unelevated
              padding="6px 14px"
              :loading="busy === i"
              :label="t('bill.done')"
              @click="confirmReceived(tr, i)"
            />
          </q-card-section>
        </q-card>
        </div>
      </div>

      <!-- 主操作固定在拇指区，和记一笔那屏一个规矩：这一页很长，
           「出账单」压在最底下的话每次都要先滚到底 -->
      <div class="actions">
        <q-btn
          outline
          color="primary"
          no-caps
          icon="content_copy"
          :label="t('bill.copy')"
          @click="copyBill"
        />
        <q-btn
          v-if="bill.is_draft"
          color="primary"
          no-caps
          unelevated
          icon="task_alt"
          :label="t('bill.cut')"
          :disable="!bill.entry_count"
          @click="doCut"
        />
        <!-- 已出的账单：右边这一半写「已出账」。做成静态块不是禁用按钮 ——
             禁用按钮看着还是个按钮，会让人反复点它找反应 -->
        <div v-else class="issued row items-center justify-center">
          <q-icon name="task_alt" size="24px" />
          {{ t('bill.issued') }}
        </div>
      </div>

    </template>

    <!-- 出账完成：立刻告诉大家谁该转多少 -->
    <q-dialog v-model="showCutResult">
      <q-card style="width: 92vw">
        <q-card-section class="q-pb-none">
          <div class="text-subtitle1 text-weight-medium">{{ t('bill.cutDoneTitle') }}</div>
          <div class="text-caption text-grey-7 q-mt-xs">{{ t('bill.cutDoneHint') }}</div>
        </q-card-section>
        <q-card-section>
          <div v-if="!cutResult?.transfers.length" class="text-grey-7">{{ t('bill.planEmpty') }}</div>
          <div
            v-for="(tr, i) in cutResult?.transfers ?? []"
            :key="i"
            class="row items-baseline q-py-xs"
          >
            <div>{{ nameOf(tr.from_id) }}</div>
            <q-icon name="arrow_forward" size="14px" class="q-mx-xs text-grey-6" />
            <div>{{ nameOf(tr.to_id) }}</div>
            <q-space />
            <div class="text-subtitle1 text-weight-medium">{{ formatYen(tr.amount) }}</div>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps :label="t('bill.copy')" @click="copyBill" />
          <q-btn v-close-popup flat no-caps color="primary" :label="t('common.confirm')" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- 剪贴板在非 HTTPS 下用不了（局域网 http 访问就会撞上），退回让人手动长按复制 -->
    <q-dialog v-model="showFallback">
      <q-card style="width: 92vw">
        <q-card-section class="text-caption text-grey-7">{{ t('bill.copyFallback') }}</q-card-section>
        <q-card-section>
          <pre class="bill-text">{{ billText }}</pre>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError, api } from 'src/api/client'
import type { Bill, BillTransfer, Entry, Statement } from 'src/api/types'
import MonthlyFixed from 'src/components/MonthlyFixed.vue'
import { formatYen } from 'src/i18n'
import { useAuth } from 'src/stores/auth'
import { type BillKey, useBills } from 'src/stores/bills'
import { useLedger } from 'src/stores/ledger'
import { KIND_COLOR } from 'src/theme'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const router = useRouter()

const props = defineProps<{ viewKey: BillKey }>()

/** 点一条明细就去改它。已出账的照样能改：差额自己进下一张的「上期结转」 */
function editEntry(id: number) {
  void router.push({ name: 'entry-edit', params: { id: String(id) } })
}
const meta = useMeta()
const auth = useAuth()
const ledger = useLedger()

const bills = useBills()
const viewKey = computed(() => props.viewKey)
/** 「已出账」那页：看的是最近出的那一张，id 由 store 里的单子列表定 */
const isOpenTab = computed(() => props.viewKey === 'current')
const view = computed(() => {
  const ck = bills.cacheKey(viewKey.value)
  return ck === null ? null : (bills.views[ck] ?? null)
})
const bill = computed(() => view.value?.bill ?? null)
const draftEntries = computed(() => view.value?.entries ?? [])
const busy = ref<number | null>(null)
const showFallback = ref(false)
const cutResult = ref<Bill | null>(null)

const nameOf = (id: number) => meta.byId[id]?.display_name ?? String(id)
const colorOf = (id: number) => meta.byId[id]?.color ?? '#90a4ae'

/** 自己在这张账单上的那一行 */
const showCutResult = computed({
  get: () => cutResult.value !== null,
  set: (v) => {
    if (!v) cutResult.value = null
  },
})

const mine = computed(
  () => bill.value?.members.find((r) => r.member_id === auth.me?.id) ?? null,
)
const mineText = computed(() => {
  const row = mine.value
  if (!row) return ''
  if (row.closing === 0) return t('bill.youSettled')
  if (row.closing > 0) return t('bill.youReceive', { amount: formatYen(row.closing) })
  const to = bill.value?.transfers.find((x) => x.from_id === row.member_id)
  return t('bill.youPay', {
    to: to ? nameOf(to.to_id) : '',
    amount: formatYen(Math.abs(row.closing)),
  })
})

const dueText = computed(() => {
  const day = meta.setting<number | null>('settle_due_day', null)
  return day ? t('bill.dueBy', { date: `${day}` }) : t('bill.unsettled')
})

/** 改完数据强制重取这一张。进页面用的是 ensure（缓存先上屏） */
const load = () => bills.reload(viewKey.value)

/** 这张账单上的固定费。已出的账单用它代替那个可编辑面板 */
const monthlyEntries = computed(() =>
  draftEntries.value
    .filter((e) => {
      if (e.kind === 'settlement' || e.category_id === null) return false
      return Boolean(meta.categoryById[e.category_id]?.monthly)
    })
    // 跟可编辑面板同一个顺序（家賃在最上面）。按日期排的话全是出账日，等于没排
    .sort(
      (a, b) =>
        (meta.categoryById[a.category_id!]?.display_order ?? 0) -
        (meta.categoryById[b.category_id!]?.display_order ?? 0),
    ),
)

const monthlyTotal = computed(() =>
  monthlyEntries.value.reduce((sum, e) => sum + e.amount_jpy, 0),
)

/** 固定费是一整屏一起看的东西，点哪一行都去那一屏，不进单笔编辑页 */
function openMonthly() {
  const id = bill.value?.statement_id
  if (id == null) return
  void router.push({ name: 'monthly', params: { statementId: String(id) } })
}

/** 这张账单上非固定费的明细（日用品/食費/收入之类）。转账不算，它们在下面的方案里 */
const others = computed(() =>
  draftEntries.value.filter((e) => {
    if (e.kind === 'settlement') return false
    const cat = e.category_id === null ? undefined : meta.categoryById[e.category_id]
    return !cat?.monthly
  }),
)

const categoryOfEntry = (e: Entry) =>
  e.category_id === null ? undefined : meta.categoryById[e.category_id]
// 收入没有分类，得有自己的图标色，否则跟「分类丢了」长得一模一样
const colorOfEntry = (e: Entry) =>
  e.kind === 'expense' ? (categoryOfEntry(e)?.color ?? '#90a4ae') : KIND_COLOR[e.kind]
const iconOfEntry = (e: Entry) =>
  e.kind === 'income' ? 'savings' : (categoryOfEntry(e)?.icon ?? 'receipt_long')
const labelOfEntry = (e: Entry) => e.title || categoryOfEntry(e)?.name || t(`kind.${e.kind}`)

// 有缓存立刻渲染，同时后台校正。换页签时组件不重建、只换 prop，所以盯着 prop
onMounted(() => {
  void bills.ensure(viewKey.value)
  bills.warm()                      // 预热另外两页，第一次切过去不用等
})
watch(viewKey, () => void bills.ensure(viewKey.value))

/** 贴进 LINE 的纯文本。在前端拼，所以自动跟随界面语言（SPEC §7.5）。 */
const billText = computed(() => {
  const b = bill.value
  if (!b) return ''
  const lines: string[] = []
  const head = b.is_draft ? t('bill.draft') : (b.label ?? '')
  lines.push(`【${head}】 ${t('bill.total')} ${formatYen(b.total_expense)}`)
  if (b.covers_from) lines.push(t('bill.coversRange', { from: b.covers_from, to: b.covers_to }))
  lines.push(dueText.value)
  lines.push('')
  for (const r of b.members) {
    const bits = [`${t('bill.owed')} ${formatYen(r.owed)}`]
    if (r.paid) bits.push(`${t('bill.paid')} ${formatYen(r.paid)}`)
    if (r.transferred_out) bits.push(`${t('bill.prepaid')} ${formatYen(r.transferred_out)}`)
    if (r.opening) bits.push(`${t('bill.carried')} ${formatYen(r.opening)}`)
    const tail =
      r.closing === 0
        ? t('bill.settled')
        : `${r.closing > 0 ? t('bill.toReceive') : t('bill.toPay')} ${formatYen(Math.abs(r.closing))}`
    lines.push(`${nameOf(r.member_id)}  ${bits.join(' / ')} → ${tail}`)
  }
  lines.push('')
  if (b.transfers.length) {
    lines.push(t('bill.plan', { n: b.transfers.length }))
    for (const tr of b.transfers) {
      lines.push(`  ${nameOf(tr.from_id)} → ${nameOf(tr.to_id)}  ${formatYen(tr.amount)}`)
    }
  } else {
    lines.push(t('bill.planEmpty'))
  }
  return lines.join('\n')
})

async function copyBill() {
  try {
    await navigator.clipboard.writeText(billText.value)
    $q.notify({ type: 'positive', message: t('bill.copied'), timeout: 1500 })
  } catch {
    // 非安全上下文（局域网 http）下 clipboard 直接抛，退回手动复制
    showFallback.value = true
  }
}

/** 点「已完成」＝记一笔转账。金额可改小，差额自动结转 —— 这就是赊账。 */
function confirmReceived(tr: BillTransfer, index: number) {
  $q.dialog({
    title: t('bill.done'),
    message: t('bill.doneHint', { from: nameOf(tr.from_id), to: nameOf(tr.to_id) }),
    prompt: { model: String(tr.amount), type: 'number' },
    cancel: true,
  }).onOk(async (value: string) => {
    const amount = Math.floor(Number(value))
    if (!amount || amount <= 0) return
    busy.value = index
    try {
      // 转账发生在出账之后，所以它进的是**下一张**草稿 —— 这是对的：
      // 账单是对「出账那一刻」的陈述，之后收到的钱属于下一轮。
      // 但记账的入口留在这张单子上，因为方案就在这儿。
      await ledger.create({
        kind: 'settlement',
        date: new Date().toISOString().slice(0, 10),
        amount_jpy: amount,
        payer_id: tr.from_id,
        to_member_id: tr.to_id,
      })
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
    } finally {
      busy.value = null
    }
  })
}

/** 出账单：把这一刻之前记的账归到一张单子上。**不锁定任何东西** */
function doCut() {
  // 默认勾上＝这张单子把固定费也结了。不勾＝把固定费留在草稿里，只结日常那部分。
  // 刚出过账又出一张（后端按设置里的天数判定），固定费那轮还没到，默认就别带上 ——
  // 但得把理由写出来，不然框子自己跳成没勾会让人以为坏了。
  const withMonthlyByDefault = bill.value?.suggest_monthly !== false
  // 只有默认没勾上时才多说一句。Quasar 的对话框不认换行，要换行就得开 html
  const gap = bill.value?.days_since_prev_cut ?? 0
  let hint = ''
  if (!withMonthlyByDefault) {
    hint = gap === 0 ? t('bill.monthlyOffHintToday') : t('bill.monthlyOffHint', { n: gap })
  }
  $q.dialog({
    title: t('bill.cut'),
    message: hint ? `${t('bill.cutConfirm')}<br><br>${hint}` : t('bill.cutConfirm'),
    html: Boolean(hint),
    cancel: true,
    options: {
      type: 'checkbox',
      model: withMonthlyByDefault ? ['monthly'] : [],
      items: [{ label: t('bill.includeMonthly'), value: 'monthly' }],
    },
  }).onOk(async (picked: string[]) => {
    try {
      const withMonthly = picked.includes('monthly')
      const st = await api.post<Statement>(`/api/statements?include_monthly=${withMonthly}`)
      // 出完账立刻把「谁给谁多少」摆出来 —— 这是出账之后马上要做的事，
      // 不该让人再自己翻回去找
      const cut = await api.get<Bill>(`/api/statements/${st.id}/bill`)
      cutResult.value = cut
      // 跳到这张新单子的地址上，界面才跟 URL 对得上（顶上会变成返回条）
      // 出账把所有缓存都变旧了（草稿清空、多出一张单子），整体重取
      bills.views = {}
      bills.statements = null
      bills.tab = 'current'         // 出完账就该看这张新单子；地址不动
      await bills.ensure('current')
      // 记一笔那屏的「日期不许选回已出账范围」靠 ledger.prevCutAt，
      // 出完账不刷新的话它还是出账前的旧值，锁就形同虚设
      await ledger.refresh()
    } catch (e) {
      $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
    }
  })
}
</script>

<style scoped>
/* 本期固定费：和未出账那页的面板对齐到同一套尺寸 —— 行高 40、金额 16px、
   右边留 50px（那页那儿是展开箭头，这页没有，用内边距占出来） */
.monthly-list .q-item {
  min-height: var(--nagaya-fee-row-h);
  padding-right: var(--nagaya-fee-amount-gap);
}
.monthly-list .amount,
.section-head .amount {
  font-size: var(--nagaya-fee-amount-fs);
  font-variant-numeric: tabular-nums;
}
/* 块尾那一行的占位：高度和边框都照着未出账那页的「加一项固定费」来 */
.fee-foot {
  min-height: var(--nagaya-fee-foot-h);
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
/* 自己那笔：这一屏最该一眼看到的东西 */
.mine { font-size: 17px; font-weight: 600; }
.mine.owe { color: #c10015; }
.mine.owed { color: #21ba45; }

/* 主操作条：压在底部 Tab 之上 */
.actions :deep(.q-btn) { min-height: 44px; }
/* 两块严格各占一半。用 grid 而不是 flex：flex 下两边算出来的 flex 一样，
   实测仍然是 188/156，内容宽度还在暗中起作用；grid 的 1fr 1fr 是确定的 */
.actions > * { min-width: 0; }
/* 已出的账单右边这一半：写状态，不做成禁用按钮 ——
   禁用按钮看着还是个按钮，会让人反复点它找反应 */
.issued {
  min-height: 44px;
  border-radius: 4px;
  background: #f2f2f5;
  color: #9e9e9e;
  /* 字号/字重/行高/图标间距全部照抄 q-btn 的实测值：外框早就各占一半了，
     里面不抄的话左右两块字一大一小、一粗一细，看着还是不一样大 */
  font-size: 14px;
  font-weight: 500;
  line-height: 24px;
}
.issued :deep(.q-icon) { margin-right: 12px; }
.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(var(--nagaya-footer-h) + env(safe-area-inset-bottom));
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  /* 页面收到 --nagaya-max-w 居中，这条压在它上面的操作栏也得跟着收，
     否则宽屏上按钮会跑到内容外面去 */
  padding: 8px max(12px, calc((100% - var(--nagaya-max-w)) / 2));
  background: #fff;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
.page {
  /* 给固定操作条留位，否则滚到底时最后一块会被它盖住 */
  padding-bottom: calc(var(--nagaya-footer-h) + 78px + env(safe-area-inset-bottom));
}
.bill-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  margin: 0;
  user-select: all;
}
</style>
