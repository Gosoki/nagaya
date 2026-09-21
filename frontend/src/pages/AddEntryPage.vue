<!--
  记一笔 —— PWA 打开的默认页（D16），也是整个 app 最该快的一屏。

  验收标准（SPEC §7.4）：常见场景 ≤ 3 次点击 + 1 次输入。
  金额 → 分类 → 保存，付款人和分摊默认折叠着，不展开也能存。
-->
<template>
  <q-page class="page">
    <q-btn-toggle
      v-model="kind"
      spread no-caps unelevated
      toggle-color="primary"
      class="kind-toggle"
      :options="[
        { label: t('kind.expense'), value: 'expense' },
        { label: t('kind.income'), value: 'income' },
        { label: t('kind.settlement'), value: 'settlement' },
      ]"
    />

    <AmountInput ref="amountEl" v-model="amount" />

    <!-- 分类：大色块网格，一点即选。转账没有分类 -->
    <div v-if="kind !== 'settlement'" class="cat-grid">
      <button
        v-for="c in meta.categories"
        :key="c.id"
        class="cat"
        :class="{ on: categoryId === c.id }"
        :style="categoryId === c.id ? { background: c.color, borderColor: c.color } : {}"
        @click="pickCategory(c.id)"
      >
        <q-icon :name="c.icon" size="22px" :color="categoryId === c.id ? 'white' : undefined" />
        <span>{{ c.name }}</span>
      </button>
    </div>

    <div class="q-px-md">
      <!-- 谁付的 / 转账时是谁转给谁 -->
      <div class="row items-center q-mt-sm q-mb-xs">
        <div class="col-auto text-grey-7 label">
          {{ kind === 'income' ? t('entry.receiver') : t('entry.payer') }}
        </div>
        <q-space />
        <MemberPicker v-model="payerId" :members="meta.activeMembers" />
      </div>

      <div v-if="kind === 'settlement'" class="row items-center q-mb-xs">
        <div class="col-auto text-grey-7 label">{{ t('entry.to') }}</div>
        <q-space />
        <MemberPicker v-model="toMemberId" :members="meta.activeMembers.filter((m) => m.id !== payerId)" />
      </div>

      <div class="row items-center q-gutter-sm q-mt-sm">
        <q-input
          v-model="title"
          dense borderless
          class="col"
          :placeholder="t('entry.title')"
          maxlength="40"
        />
        <q-btn dense flat no-caps icon="event" :label="dateLabel" class="text-grey-7">
          <q-popup-proxy cover transition-show="scale">
            <q-date v-model="date" mask="YYYY-MM-DD" today-btn minimal />
          </q-popup-proxy>
        </q-btn>
      </div>

      <q-expansion-item
        v-if="kind !== 'settlement'"
        dense
        class="q-mt-sm split-panel"
        header-class="q-px-none text-primary"
        :label="t('entry.splitDetail')"
        :caption="splitSummary"
      >
        <SplitEditor
          ref="splitEl"
          :amount="signedAmount"
          :members="meta.activeMembers"
          :payer-id="payerId"
          @change="onSplitChange"
        />
      </q-expansion-item>
    </div>

    <!-- 主操作在拇指区；合计对不上时差额就摆在按钮正上方，不用滚回去找 -->
    <div class="actions">
      <div v-if="splitDiff !== 0 && amount > 0" class="diff-line text-negative">
        {{ t('split.notBalanced', { n: formatYen(splitDiff) }) }}
      </div>
      <div class="row">
      <q-btn
        class="col"
        color="primary"
        size="lg"
        no-caps
        unelevated
        :disable="!canSave"
        :loading="busy"
        :label="t('entry.save')"
        @click="save(false)"
      />
      <q-btn
        class="col-auto q-ml-sm"
        color="primary"
        size="lg"
        no-caps
        outline
        :disable="!canSave"
        :label="t('entry.saveAndNext')"
        @click="save(true)"
      />
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from 'src/api/client'
import { formatYen } from 'src/i18n'
import type { EntryKind } from 'src/api/types'
import AmountInput from 'src/components/AmountInput.vue'
import MemberPicker from 'src/components/MemberPicker.vue'
import SplitEditor from 'src/components/SplitEditor.vue'
import { useAuth } from 'src/stores/auth'
import { useDrafts } from 'src/stores/drafts'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const meta = useMeta()
const auth = useAuth()
const ledger = useLedger()
const drafts = useDrafts()

const kind = ref<EntryKind>('expense')
const amount = ref(0)
const categoryId = ref<number | null>(null)
const payerId = ref<number | null>(null)
const toMemberId = ref<number | null>(null)
const title = ref('')
const date = ref(new Date().toISOString().slice(0, 10))
const busy = ref(false)

const rule = ref<Record<string, unknown> | null>(null)
const splitValid = ref(true)
const splitDiff = ref(0)
const amountEl = ref<InstanceType<typeof AmountInput> | null>(null)
const splitEl = ref<InstanceType<typeof SplitEditor> | null>(null)

/** 收入在库里存负数（SPEC §5）；界面上只让人填正数，符号这里加 */
const signedAmount = computed(() => (kind.value === 'income' ? -amount.value : amount.value))

const dateLabel = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  return date.value === today ? t('common.today') : date.value.slice(5)
})

const canSave = computed(
  () =>
    amount.value > 0 &&
    payerId.value !== null &&
    splitValid.value &&
    (kind.value !== 'settlement' || (toMemberId.value !== null && toMemberId.value !== payerId.value)),
)

const splitSummary = computed(() => {
  if (!rule.value) return ''
  return meta.activeMembers.map((m) => m.display_name).join(' / ')
})

onMounted(() => {
  payerId.value = meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null
})
watch(
  () => meta.settings.length,
  () => {
    if (payerId.value === null) {
      payerId.value = meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null
    }
  },
)

function pickCategory(id: number) {
  categoryId.value = categoryId.value === id ? null : id
}

function onSplitChange(next: Record<string, unknown> | null, valid: boolean, diff: number) {
  rule.value = next
  splitValid.value = valid
  splitDiff.value = diff
}

async function save(keepGoing: boolean) {
  if (!canSave.value || payerId.value === null) return
  busy.value = true
  const payload = {
      kind: kind.value,
      date: date.value,
      amount_jpy: signedAmount.value,
      payer_id: payerId.value,
      to_member_id: kind.value === 'settlement' ? toMemberId.value : null,
      category_id: kind.value === 'settlement' ? null : categoryId.value,
      title: title.value,
      rule: kind.value === 'settlement' ? null : rule.value,
  }
  try {
    await ledger.create(payload)
    $q.notify({ type: 'positive', message: t('entry.saved'), timeout: 1200 })
    reset(keepGoing)
  } catch (e) {
    // 只有「连不上服务器」才转存草稿。金额方向错、账期已关这类是**服务器明确拒绝**，
    // 存成草稿只会让人以后反复补交同一笔失败的账（D15）
    if (e instanceof ApiError && e.code === 'network') {
      drafts.add(payload)
      $q.notify({ type: 'warning', message: t('draft.savedOffline'), timeout: 2500 })
      reset(keepGoing)
    } else {
      $q.notify({
        type: 'negative',
        message: e instanceof ApiError ? e.text : String(e),
        timeout: 4000,
      })
    }
  } finally {
    busy.value = false
  }
}

/** 「保存并继续」：不跳转、不清分类，光标回到金额框，超市小票一串录完 */
function reset(keepGoing: boolean) {
  amount.value = 0
  title.value = ''
  rule.value = null
  splitEl.value?.reset()
  if (keepGoing) {
    amountEl.value?.focus()
  } else {
    categoryId.value = null
  }
}
</script>

<style scoped>
.page {
  /* 底部有两层：固定操作栏（约 64px）压在底部 Tab（50px）之上。
     留够位置，否则展开分摊后最后一个人的那一行会被操作栏盖住。 */
  padding-bottom: calc(132px + env(safe-area-inset-bottom));
}
.kind-toggle { border-bottom: 1px solid rgba(0, 0, 0, 0.08); }
.label { font-size: 14px; }

.cat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 4px 12px 8px;
}
.cat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 64px;                      /* 大色块，一点即中，不用瞄 */
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 10px;
  background: #fff;
  color: #444;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.cat.on { color: #fff; }

.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(50px + env(safe-area-inset-bottom));   /* 压在底部 Tab 之上 */
  padding: 6px 12px 8px;
  /* 不用半透明：内容从按钮底下透出来会看着像渲染坏了 */
  background: #fff;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}
.diff-line {
  font-size: 12px;
  text-align: center;
  padding-bottom: 4px;
}
</style>
