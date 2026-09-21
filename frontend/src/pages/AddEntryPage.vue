<!--
  记一笔 —— PWA 打开的默认页（D16），也是整个 app 最该快的一屏。

  验收标准（SPEC §7.4）：常见场景 ≤ 3 次点击 + 1 次输入。
  金额 → 分类 → 保存，付款人和分摊默认折叠着，不展开也能存。
-->
<template>
  <q-page class="page">
    <!-- 编辑模式：顶上一条返回 + 这笔在哪张账单上。
         「已出账也能改」这件事必须当场说清楚差额去哪了，否则没人敢按保存 -->
    <div v-if="editingId !== null" class="edit-head">
      <q-btn dense flat round icon="arrow_back" @click="goBack" />
      <div class="col text-weight-medium">{{ t('entry.editTitle') }}</div>
    </div>
    <q-banner v-if="billedLabel" dense class="bg-blue-1 text-blue-9 edit-note">
      {{ t('entry.editBilled', { label: billedLabel }) }}
    </q-banner>

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

    <!-- 分类：大色块网格，一点即选。只有支出分类；收入和转账都没有 -->
    <div
      v-if="kind === 'expense'"
      class="cat-grid"
      :style="{ gridTemplateColumns: `repeat(${Math.min(4, gridCategories.length)}, 1fr)` }"
    >
      <button
        v-for="c in gridCategories"
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
            <div>
              <q-date v-model="date" mask="YYYY-MM-DD" today-btn minimal :options="dateAllowed" />
              <!-- 已出过账的日期选不了：那张单子锁着，记进去也不会出现在上面，
                   只会让人以为补上了。要补记就写在备注里 -->
              <div v-if="minDate && editingId === null" class="text-caption text-grey-7 q-pa-sm date-hint">
                {{ t('entry.dateLocked', { date: minDate }) }}
              </div>
            </div>
          </q-popup-proxy>
        </q-btn>
      </div>

      <!-- 不做折叠：日常网格只剩三个按钮之后竖向空间够用，
           每人分多少一直摆在那儿，比藏在一个要点开的抽屉里踏实。
           折起来的那个抽屉还带个没用的摘要行（「Go / Kan / Zen」），白占一行 -->
      <div v-if="kind !== 'settlement'" class="q-mt-sm split-panel">
        <div class="text-grey-7 label q-mb-xs">{{ t('entry.split') }}</div>
        <SplitEditor
          ref="splitEl"
          :amount="signedAmount"
          :members="meta.activeMembers"
          :payer-id="payerId"
          :seed-rule="ownRule ?? selectedCategoryRule"
          @change="onSplitChange"
        />
      </div>
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
        @click="editingId === null ? save(false) : saveEdit()"
      />
      <q-btn
        v-if="editingId === null"
        class="col-auto q-ml-sm"
        color="primary"
        size="lg"
        no-caps
        outline
        :disable="!canSave"
        :label="t('entry.saveAndNext')"
        @click="save(true)"
      />
      <q-btn
        v-else
        class="col-auto q-ml-sm"
        color="negative"
        size="lg"
        no-caps
        outline
        icon="delete"
        :label="t('common.delete')"
        @click="removeEntry"
      />
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, api } from 'src/api/client'
import { formatYen } from 'src/i18n'
import type { Entry, EntryKind } from 'src/api/types'
import AmountInput from 'src/components/AmountInput.vue'
import MemberPicker from 'src/components/MemberPicker.vue'
import SplitEditor from 'src/components/SplitEditor.vue'
import { useAuth } from 'src/stores/auth'
import { useDrafts } from 'src/stores/drafts'
import { useLedger } from 'src/stores/ledger'
import { useMeta } from 'src/stores/meta'

const { t } = useI18n()
const $q = useQuasar()
const route = useRoute()
const router = useRouter()
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

/** 路由带了 id ＝ 在改一笔已经记下的账（已出账的也算）。空 ＝ 记新的一笔 */
const editingId = computed(() => (route.params.id ? Number(route.params.id) : null))
const version = ref(0)
const billedLabel = ref<string | null>(null)
/** 改的时候分摊要从**这笔自己的规则**起步，不是分类默认值 —— 否则一打开就被改回默认 */
const ownRule = ref<Record<string, unknown> | null>(null)

const rule = ref<Record<string, unknown> | null>(null)
const splitValid = ref(true)
const splitDiff = ref(0)
const amountEl = ref<InstanceType<typeof AmountInput> | null>(null)
const splitEl = ref<InstanceType<typeof SplitEditor> | null>(null)

/** 改一笔电费时，网格里得有「電気」这个分类可选，所以编辑模式不筛掉固定费 */
const gridCategories = computed(() =>
  editingId.value === null ? meta.dailyCategories : meta.categories.filter((c) => !c.archived),
)

/** 收入在库里存负数（SPEC §5）；界面上只让人填正数，符号这里加 */
const signedAmount = computed(() => (kind.value === 'income' ? -amount.value : amount.value))

/** 上次出账那天（含）之前的日期不给选 */
const minDate = computed(() => ledger.prevCutAt?.slice(0, 10) ?? null)
// 只有**新记**的账才限日期：新的一笔不管写哪天都落进当前草稿，选回已出账的范围
// 只会让人以为补进了那张单子。改已有的账不受这条约束 —— 它归哪张单子由
// statement_id 定死，改日期不会让它换单子
const dateAllowed = (d: string) =>
  editingId.value !== null || !minDate.value || d.replace(/\//g, '-') >= minDate.value

const dateLabel = computed(() => {
  const today = new Date().toISOString().slice(0, 10)
  return date.value === today ? t('common.today') : date.value.slice(5)
})

const canSave = computed(
  () =>
    amount.value > 0 &&
    payerId.value !== null &&
    splitValid.value &&
    // 支出必须选分类。不选的话后端拿不到分类默认规则，会悄悄掉回「全员均分」——
    // 一笔本该 1:1:0 的账就变成 1:1:1，而界面上没有任何提示。
    // 收入没有分类：返现、給付金这些套不上「日用品/食費」，写在备注里更清楚。
    (kind.value !== 'expense' || categoryId.value !== null) &&
    (kind.value !== 'settlement' || (toMemberId.value !== null && toMemberId.value !== payerId.value)),
)

/** 选中分类的默认分摊规则，交给编辑器当初始值 —— 否则预览和实际存下去的不是一回事 */
const selectedCategoryRule = computed(
  () =>
    (meta.categories.find((c) => c.id === categoryId.value)?.default_rule_json as
      | Record<string, unknown>
      | null
      | undefined) ?? null,
)

onMounted(async () => {
  if (editingId.value !== null) {
    await loadForEdit(editingId.value)
    return
  }
  payerId.value = meta.setting<number | null>('default_payer_id', null) ?? auth.me?.id ?? null
})

async function loadForEdit(id: number) {
  try {
    const e = await api.get<Entry>(`/api/entries/${id}`)
    kind.value = e.kind
    amount.value = Math.abs(e.amount_jpy)
    categoryId.value = e.category_id
    payerId.value = e.payer_id
    toMemberId.value = e.to_member_id
    title.value = e.title
    date.value = e.date
    version.value = e.version
    ownRule.value = e.split_rule_json
    billedLabel.value = e.statement_label
  } catch (err) {
    $q.notify({ type: 'negative', message: err instanceof ApiError ? err.text : String(err) })
    goBack()
  }
}

function goBack() {
  if (window.history.length > 1) router.back()
  else void router.push({ name: 'entries' })
}

async function saveEdit() {
  if (!canSave.value || payerId.value === null || editingId.value === null) return
  busy.value = true
  try {
    await ledger.update(editingId.value, version.value, {
      kind: kind.value,
      date: date.value,
      amount_jpy: signedAmount.value,
      payer_id: payerId.value,
      to_member_id: kind.value === 'settlement' ? toMemberId.value : null,
      category_id: kind.value === 'expense' ? categoryId.value : null,
      title: title.value,
      rule: kind.value === 'settlement' ? null : rule.value,
    })
    await ledger.refresh()
    $q.notify({ type: 'positive', message: t('entry.saved'), timeout: 1200 })
    goBack()
  } catch (e) {
    $q.notify({
      type: 'negative',
      message: e instanceof ApiError ? e.text : String(e),
      timeout: 4000,
    })
  } finally {
    busy.value = false
  }
}

function removeEntry() {
  if (editingId.value === null) return
  $q.dialog({ title: t('common.delete'), message: t('entry.deleteConfirm'), cancel: true }).onOk(
    async () => {
      await api.del(`/api/entries/${editingId.value}`)
      await ledger.refresh()
      goBack()
    },
  )
}
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
  ownRule.value = null       // 换了分类就用新分类的默认分摊，跟记新账时一致
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
      category_id: kind.value === 'expense' ? categoryId.value : null,
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
/* 编辑模式的头：返回 + 标题，跟内容同一层，不额外占一条 header */
.edit-head {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
}
.edit-note {
  margin: 0 12px 4px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
}
.page {
  /* 底部有两层：固定操作栏（约 64px）压在底部 Tab（50px）之上。
     留够位置，否则展开分摊后最后一个人的那一行会被操作栏盖住。 */
  padding-bottom: calc(var(--nagaya-footer-h) + 90px + env(safe-area-inset-bottom));
}
.kind-toggle { border-bottom: 1px solid rgba(0, 0, 0, 0.08); }
.label { font-size: 14px; }

.cat-grid {
  display: grid;
  /* 列数在模板里按分类数算，最多 4 列。写死 4 列的话分类不足 4 个时
     右边会空出一格，整排偏左，看着像上面的金额没居中 */
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


.actions :deep(.q-btn) { min-height: 44px; }
.date-hint { max-width: 290px; border-top: 1px solid rgba(0, 0, 0, 0.08); }
.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: calc(var(--nagaya-footer-h) + env(safe-area-inset-bottom));   /* 压在底部 Tab 之上 */
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
