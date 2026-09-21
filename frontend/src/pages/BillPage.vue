<!--
  月度账单 —— SPEC F6。

  账单只负责展示：余额是全局累计的，这里拆成「期初结转 + 本期发生 + 本期已收付」。
  所以「赊账」不需要任何额外机制 —— 少付的部分自然以「上期结转」出现在下一张账单上。

  一键复制的文本是直接贴进 LINE 群的，所以格式按等宽对齐排，手机上看着是一张表。
-->
<template>
  <q-page class="page">
    <!-- 本期和以前分成两页：看本期问的是「还要填什么、该出账了没」，
         翻旧单子问的是「上个月多少、谁转了没」，混一页两边都别扭 -->
    <BillTabs v-if="statementId === null" />
    <div v-else class="row items-center back-head">
      <q-btn dense flat round icon="arrow_back" @click="backToPast" />
      <div class="col text-weight-medium">{{ t('bill.tabPast') }}</div>
    </div>

    <div v-if="!bill" class="text-center text-grey-6 q-mt-xl">{{ t('bill.noPeriod') }}</div>

    <template v-else>
      <div class="head q-pa-md">
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
        <div v-if="coversText" class="text-caption text-grey-6 q-mt-xs">{{ coversText }}</div>

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
      <div v-else class="others">
        <q-item clickable dense class="q-pt-md q-pb-xs" @click="openMonthly">
          <q-item-section class="text-subtitle2">{{ t('monthly.title') }}</q-item-section>
          <q-item-section side class="text-grey-9">{{ formatYen(monthlyTotal) }}</q-item-section>
          <q-item-section side><q-icon name="chevron_right" color="grey-5" size="18px" /></q-item-section>
        </q-item>
        <q-list v-if="monthlyEntries.length" separator>
          <q-item v-for="e in monthlyEntries" :key="e.id" dense>
            <q-item-section avatar>
              <q-avatar size="30px" :style="{ background: colorOfEntry(e) }" text-color="white">
                <q-icon :name="iconOfEntry(e)" size="16px" />
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ categoryOfEntry(e)?.name ?? labelOfEntry(e) }}</q-item-label>
              <q-item-label v-if="e.title" caption>{{ e.title }}</q-item-label>
            </q-item-section>
            <q-item-section side class="text-grey-9">{{ formatYen(e.amount_jpy) }}</q-item-section>
          </q-item>
        </q-list>
        <div v-else class="text-caption text-grey-6 q-px-md q-pb-md">{{ t('monthly.noneBilled') }}</div>
      </div>

      <!-- 固定费之下，把这期其他的开销也摆出来：
           不然账单上只看得见固定项，日用品/食費那些钱是从哪来的就说不清 -->
      <div class="others">
        <div class="text-subtitle2 q-px-md q-pt-md q-pb-xs">{{ t('bill.others') }}</div>
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

      <div class="text-subtitle2 q-px-md q-pt-md q-pb-xs">{{ t('bill.perMember') }}</div>
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

      <div class="q-pa-md">
        <div class="text-subtitle2 q-mb-sm">
          {{ bill.transfers.length ? t('bill.plan', { n: bill.transfers.length }) : t('bill.planEmpty') }}
        </div>
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

      <!-- 主操作固定在拇指区，和记一笔那屏一个规矩：这一页很长，
           「出账单」压在最底下的话每次都要先滚到底 -->
      <div class="actions">
        <q-btn
          class="col"
          outline
          color="primary"
          no-caps
          icon="content_copy"
          :label="t('bill.copy')"
          @click="copyBill"
        />
        <q-btn
          v-if="bill.is_draft"
          class="col-auto q-ml-sm"
          color="primary"
          no-caps
          unelevated
          icon="task_alt"
          :label="t('bill.cut')"
          :disable="!bill.entry_count"
          @click="doCut"
        />
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
  </q-page>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, api } from 'src/api/client'
import type { Entry, Statement } from 'src/api/types'
import BillTabs from 'src/components/BillTabs.vue'
import MonthlyFixed from 'src/components/MonthlyFixed.vue'
import { formatYen } from 'src/i18n'
import { useAuth } from 'src/stores/auth'
import { useLedger } from 'src/stores/ledger'
import { KIND_COLOR } from 'src/theme'
import { useMeta } from 'src/stores/meta'

interface BillRow {
  member_id: number
  opening: number
  owed: number
  paid: number
  transferred_out: number
  transferred_in: number
  closing: number
}
interface BillTransfer { from_id: number; to_id: number; amount: number }
interface Bill {
  statement_id: number | null
  label: string | null
  is_draft: boolean
  cut_at: string | null
  covers_from: string | null
  covers_to: string | null
  edited_after_cut: { count: number; frozen_total: number | null; live_total: number } | null
  prev_cut_at: string | null
  prev_label: string | null
  days_since_prev_cut: number | null
  suggest_monthly: boolean
  settled: boolean
  settled_transfers: boolean[]
  total_expense: number
  total_income: number
  entry_count: number
  members: BillRow[]
  transfers: BillTransfer[]
  simplified: boolean
  covers: { title: string; category_id: number | null; period_start: string | null; period_end: string | null }[]
}

const { t } = useI18n()
const $q = useQuasar()
const route = useRoute()
const router = useRouter()

/** 点一条明细就去改它。已出账的照样能改：差额自己进下一张的「上期结转」 */
function editEntry(id: number) {
  void router.push({ name: 'entry-edit', params: { id: String(id) } })
}
const meta = useMeta()
const auth = useAuth()
const ledger = useLedger()

const bill = ref<Bill | null>(null)
/** 路由里带的账单 id。null ＝ 本期那张草稿 */
const statementId = computed(() => Number(route.params.statementId) || null)
const draftEntries = ref<Entry[]>([])
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

/** 「含 7–8 月水费」这类标注 */
const coversText = computed(() => {
  if (!bill.value?.covers.length) return ''
  return bill.value.covers
    .map((c) => {
      const label =
        c.title || (c.category_id === null ? '' : (meta.categoryById[c.category_id]?.name ?? ''))
      // 日期压成 07/01〜08/31：标题多半已经写了「7〜8月分」，再跟一串完整日期太啰嗦
      const span = [c.period_start, c.period_end]
        .filter(Boolean)
        .map((d) => d!.slice(5).replace('-', '/'))
        .join('〜')
      return t('bill.covers', { label: label ? `${label}（${span}）` : span })
    })
    .join(' · ')
})

/** 看哪一张完全由路由决定：/bill ＝本期草稿，/bill/3 ＝那张出过的 */
async function load() {
  const id = statementId.value
  bill.value = id
    ? await api.get<Bill>(`/api/statements/${id}/bill`)
    : await api.get<Bill>('/api/bill')
  draftEntries.value = await api.get<Entry[]>(
    id ? `/api/entries?statement_id=${id}&limit=200` : '/api/entries?unbilled_only=true&limit=200',
  )
}

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

function backToPast() {
  void router.push({ name: 'bill-past' })
}

onMounted(load)
watch(statementId, load)   // 在两张单子之间跳时组件不会重建，得自己重新拉

/** 贴进 LINE 的纯文本。在前端拼，所以自动跟随界面语言（SPEC §7.5）。 */
const billText = computed(() => {
  const b = bill.value
  if (!b) return ''
  const lines: string[] = []
  const head = b.is_draft ? t('bill.draft') : (b.label ?? '')
  lines.push(`【${head}】 ${t('bill.total')} ${formatYen(b.total_expense)}`)
  if (b.covers_from) lines.push(t('bill.coversRange', { from: b.covers_from, to: b.covers_to }))
  lines.push(dueText.value)
  if (coversText.value) lines.push(coversText.value)
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
      await router.push({ name: 'bill', params: { statementId: String(st.id) } })
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
.head { border-bottom: 1px solid rgba(0, 0, 0, 0.08); }
/* 自己那笔：这一屏最该一眼看到的东西 */
.mine { font-size: 17px; font-weight: 600; }
.mine.owe { color: #c10015; }
.mine.owed { color: #21ba45; }

/* 主操作条：压在底部 Tab 之上 */
.actions :deep(.q-btn) { min-height: 44px; }
.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(var(--nagaya-footer-h) + env(safe-area-inset-bottom));
  display: flex;
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
