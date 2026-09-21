<!--
  月度账单 —— SPEC F6。

  账单只负责展示：余额是全局累计的，这里拆成「期初结转 + 本期发生 + 本期已收付」。
  所以「赊账」不需要任何额外机制 —— 少付的部分自然以「上期结转」出现在下一张账单上。

  一键复制的文本是直接贴进 LINE 群的，所以格式按等宽对齐排，手机上看着是一张表。
-->
<template>
  <q-page class="q-pb-xl">
    <div v-if="!bill" class="text-center text-grey-6 q-mt-xl">{{ t('bill.noPeriod') }}</div>

    <template v-else>
      <div class="head q-pa-md">
        <div class="row items-center">
          <div>
            <div class="text-h6">{{ bill.period.label }}</div>
            <div class="text-caption text-grey-7">
              {{ bill.period.start_date }} 〜 {{ bill.period.end_date }}
            </div>
          </div>
          <q-space />
          <div class="text-right">
            <div class="text-h6">{{ formatYen(bill.total_expense) }}</div>
            <div class="text-caption" :class="bill.period.status === 'closed' ? 'text-grey-6' : 'text-warning'">
              {{ bill.period.status === 'closed' ? t('bill.closed') : dueText }}
            </div>
          </div>
        </div>
        <div v-if="coversText" class="text-caption text-grey-7 q-mt-xs">{{ coversText }}</div>
      </div>

      <!-- 本期固定费：出账单时顺手把家賃/水电煤网填了，账单跟着重算 -->
      <MonthlyFixed
        :period-id="bill.period.id"
        :readonly="bill.period.status === 'closed'"
        @saved="load"
      />

      <q-list separator>
        <q-item v-for="row in bill.members" :key="row.member_id">
          <q-item-section avatar>
            <q-avatar size="32px" :style="{ background: colorOf(row.member_id) }" text-color="white">
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
          <q-card-section class="row items-center q-py-sm">
            <div class="col">
              <span class="text-weight-medium">{{ nameOf(tr.from_id) }}</span>
              <q-icon name="arrow_forward" size="16px" class="q-mx-xs text-grey-6" />
              <span class="text-weight-medium">{{ nameOf(tr.to_id) }}</span>
              <div class="text-h6">{{ formatYen(tr.amount) }}</div>
            </div>
            <q-btn
              color="primary"
              no-caps
              unelevated
              :disable="bill.period.status === 'closed'"
              :loading="busy === i"
              :label="t('bill.received')"
              @click="confirmReceived(tr, i)"
            />
          </q-card-section>
        </q-card>
      </div>

      <div class="q-px-md q-gutter-sm column">
        <q-btn outline color="primary" no-caps icon="content_copy" :label="t('bill.copy')" @click="copyBill" />
        <q-btn
          v-if="bill.period.status === 'open'"
          flat color="grey-8" no-caps icon="lock" :label="t('bill.close')"
          @click="doClose"
        />
        <q-btn v-else flat color="grey-8" no-caps icon="lock_open" :label="t('bill.reopen')" @click="doReopen" />
      </div>
    </template>

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
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { ApiError, api } from 'src/api/client'
import type { Period } from 'src/api/types'
import MonthlyFixed from 'src/components/MonthlyFixed.vue'
import { formatYen } from 'src/i18n'
import { useLedger } from 'src/stores/ledger'
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
  period: { id: number; label: string; start_date: string; end_date: string; status: 'open' | 'closed' }
  settle_due: string | null
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
const meta = useMeta()
const ledger = useLedger()

const bill = ref<Bill | null>(null)
const busy = ref<number | null>(null)
const showFallback = ref(false)

const nameOf = (id: number) => meta.byId[id]?.display_name ?? String(id)
const colorOf = (id: number) => meta.byId[id]?.color ?? '#90a4ae'

const dueText = computed(() =>
  bill.value?.settle_due ? t('bill.dueBy', { date: bill.value.settle_due }) : t('bill.unsettled'),
)

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

async function load() {
  const periods = await api.get<Period[]>('/api/periods')
  // 默认打开**最早的未关账账期** —— 那才是「你现在欠着的那张账单」，
  // 和转账挂靠的规则（挂到最早未关账期）是同一条。
  // 用「最新的一期」会有个坑：误记一笔未来日期的账就能把账单页整个带跑。
  const oldestOpen = [...periods].reverse().find((p) => p.status === 'open')
  const id = Number(route.params.periodId) || oldestOpen?.id || periods[0]?.id
  if (!id) return
  bill.value = await api.get<Bill>(`/api/periods/${id}/bill`)
}

onMounted(load)

/** 贴进 LINE 的纯文本。在前端拼，所以自动跟随界面语言（SPEC §7.5）。 */
const billText = computed(() => {
  const b = bill.value
  if (!b) return ''
  const lines: string[] = []
  lines.push(`【${b.period.label} ${t('bill.title')}】 ${t('bill.total')} ${formatYen(b.total_expense)}`)
  lines.push(b.settle_due ? t('bill.dueBy', { date: b.settle_due }) : t('bill.unsettled'))
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

/** 点「已收到」＝记一笔转账。金额可改小，差额自动结转 —— 这就是赊账。 */
function confirmReceived(tr: BillTransfer, index: number) {
  $q.dialog({
    title: t('bill.received'),
    message: t('bill.receivedHint', { from: nameOf(tr.from_id), to: nameOf(tr.to_id) }),
    prompt: { model: String(tr.amount), type: 'number' },
    cancel: true,
  }).onOk(async (value: string) => {
    const amount = Math.floor(Number(value))
    if (!amount || amount <= 0) return
    busy.value = index
    try {
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

async function doClose() {
  $q.dialog({ title: t('bill.close'), message: t('bill.closeConfirm'), cancel: true }).onOk(async () => {
    try {
      await api.post(`/api/periods/${bill.value!.period.id}/close`)
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e instanceof ApiError ? e.text : String(e) })
    }
  })
}

async function doReopen() {
  await api.post(`/api/periods/${bill.value!.period.id}/reopen`)
  await load()
}
</script>

<style scoped>
.head { border-bottom: 1px solid rgba(0, 0, 0, 0.08); }
.bill-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  margin: 0;
  user-select: all;
}
</style>
