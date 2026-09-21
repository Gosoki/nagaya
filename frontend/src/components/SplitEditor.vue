<!--
  分摊编辑器 —— SPEC §7.4 点名的「最难的一屏」。

  每人一行：头像 + 权重 stepper（−/数字/＋）+ 实时金额。
  底部固定条常驻「合计 ／ 差额」，固定金额模式下差额 ≠ 0 时红字且禁止保存。

  预览用前端的分摊引擎算（本地即时，不往返服务器）；**保存后以后端返回的
  shares 为准**，两边靠共享 fixture 锁住不漂（SPEC §7.3）。
-->
<template>
  <div>
    <q-btn-toggle
      v-model="mode"
      spread
      no-caps
      unelevated
      toggle-color="primary"
      class="q-mb-md mode-toggle"
      :options="[
        { label: t('split.ratio'), value: 'ratio' },
        { label: t('split.exact'), value: 'exact' },
      ]"
      @update:model-value="onModeChange"
    />

    <!-- 列头：比例 / 调整 / 应担 三件事摆在一排，一眼看得出它们的关系。
         调整额原来藏在下面一个折叠里，看不见它是加在比例结果之上的 -->
    <div class="row items-center head-row text-caption text-grey-6">
      <div class="col name-col" />
      <div v-if="mode === 'ratio'" class="col-auto weight-col text-center">{{ t('split.weight') }}</div>
      <div v-if="mode === 'ratio'" class="col-auto adj-col text-right">{{ t('split.adjustment') }}</div>
      <div v-else class="col-auto exact-col text-right">{{ t('split.amountCol') }}</div>
      <!-- 固定金额模式不要「应担」这一列：输入框里就是金额，重复一遍没意义 -->
      <div v-if="mode === 'ratio'" class="col-auto share-col text-right">{{ t('split.share') }}</div>
    </div>

    <div v-for="m in members" :key="m.id" class="row items-center member-row">
      <div class="col name-col row items-center no-wrap">
        <q-avatar size="28px" :style="{ background: m.color }" text-color="white" class="q-mr-sm">
          {{ m.display_name.slice(0, 1) }}
        </q-avatar>
        <div class="name ellipsis">{{ m.display_name }}</div>
      </div>

      <template v-if="mode === 'ratio'">
        <div class="col-auto weight-col row items-center justify-center no-wrap">
          <q-btn
            dense flat round icon="remove" padding="9px"
            :disable="(weights[String(m.id)] ?? 0) <= 0"
            @click="bump(m.id, -1)"
          />
          <div class="weight">{{ weights[String(m.id)] ?? 0 }}</div>
          <q-btn dense flat round icon="add" padding="9px" @click="bump(m.id, 1)" />
        </div>
        <div class="col-auto adj-col">
          <input
            class="num-input"
            type="text"
            inputmode="numeric"
            placeholder="0"
            :value="adjDisplay(m.id)"
            @input="onAdjInput(m.id, $event)"
          />
        </div>
      </template>

      <div v-else class="col-auto exact-col">
        <input
          class="num-input"
          type="text"
          inputmode="numeric"
          :value="exactDisplay(m.id)"
          @input="onExactInput(m.id, $event)"
        />
      </div>

      <div
        v-if="mode === 'ratio'"
        class="col-auto share-col"
        :class="{ 'text-grey-5': (preview?.[String(m.id)] ?? 0) === 0 }"
      >
        {{ formatYen(preview?.[String(m.id)] ?? 0) }}
      </div>
    </div>

    <div class="text-caption text-grey-6 q-mt-xs">{{ t('split.hint') }}</div>

    <q-separator class="q-my-sm" />

    <div class="row items-center total-bar">
      <div class="text-grey-7">{{ t('split.total') }}</div>
      <q-space />
      <div :class="balanced ? 'text-grey-8' : 'text-negative text-weight-medium'">
        {{ formatYen(previewTotal) }}
        <span v-if="!balanced">（{{ t('split.diff') }} {{ formatYen(amount - previewTotal) }}）</span>
      </div>
    </div>
    <div v-if="error" class="text-negative text-caption q-mt-xs">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Member } from 'src/api/types'
import { SplitError, split } from 'src/core/split'
import { formatYen } from 'src/i18n'

const props = defineProps<{
  amount: number
  members: Member[]
  payerId: number | null
  /**
   * 初始规则（分类默认值或这笔账已有的规则）。
   * 不给的话就是全员等权。
   *
   * 没有它会出一个很阴的 bug：选了「家賃」（默认是固定金额 45000/40000/35000）
   * 展开分摊，看到的却是 1:1:1 —— 预览本身就是错的；更糟的是手一碰
   * touched 就置位，保存时把显式的 1:1:1 传上去，把分类的固定金额规则顶掉了。
   */
  seedRule?: Record<string, unknown> | null
}>()
const emit = defineEmits<{
  /**
   * 用户动过分摊 → 往上抛显式规则；没动过则抛 null，交给后端用默认值。
   * 顺带抛出差额：合计/差额要在**固定操作栏**里常驻（SPEC §7.4），
   * 光放在这个面板底部的话，人多了就滚到屏幕外去了。
   */
  change: [rule: Record<string, unknown> | null, valid: boolean, diff: number]
}>()

const { t } = useI18n()

const mode = ref<'ratio' | 'exact'>('ratio')
const weights = ref<Record<string, number>>({})
const adjustments = ref<Record<string, number>>({})
const exact = ref<Record<string, number>>({})
const touched = ref(false)

function resetWeights() {
  const seed = props.seedRule ?? null
  const seedMode = (seed?.mode as string) ?? 'ratio'
  const keys = props.members.map((m) => String(m.id))

  if (seed && seedMode === 'exact') {
    const seeded = (seed.exact ?? {}) as Record<string, number>
    mode.value = 'exact'
    exact.value = Object.fromEntries(keys.map((k) => [k, Number(seeded[k] ?? 0)]))
    weights.value = Object.fromEntries(keys.map((k) => [k, 1]))
    adjustments.value = {}
    return
  }

  mode.value = 'ratio'
  const seededW = (seed?.weights ?? null) as Record<string, number> | null
  const equal = Number(seed?.equal_weight ?? 1)
  weights.value = Object.fromEntries(
    keys.map((k) => [k, seededW ? Number(seededW[k] ?? 0) : equal]),
  )
  const seededAdj = (seed?.adjustments ?? {}) as Record<string, number>
  adjustments.value = Object.fromEntries(
    Object.entries(seededAdj).filter(([k, v]) => keys.includes(k) && Number(v) !== 0),
  )
  exact.value = Object.fromEntries(keys.map((k) => [k, 0]))
}
resetWeights()
watch(() => props.members, resetWeights)
// 换了分类 → 换一套默认规则重来。touched 一并清掉，否则会把上一个分类的规则带过去
watch(
  () => props.seedRule,
  () => {
    touched.value = false
    resetWeights()
  },
)

const rule = computed<Record<string, unknown>>(() =>
  mode.value === 'exact'
    ? { mode: 'exact', exact: exact.value }
    : { mode: 'ratio', weights: weights.value, adjustments: adjustments.value, remainder_to: 'payer' },
)

const order = computed(() => props.members.map((m) => String(m.id)))
const error = ref('')

const preview = computed<Record<string, number> | null>(() => {
  error.value = ''
  if (!props.amount) return null
  try {
    return split(rule.value as never, props.amount, {
      order: order.value,
      payer: props.payerId === null ? null : String(props.payerId),
    })
  } catch (e) {
    // 固定金额对不上是常态（正在输入中），底部差额那条已经在提示了，不必再红一行
    if (e instanceof SplitError && e.code !== 'sum_mismatch') error.value = e.message
    return null
  }
})

const previewTotal = computed(() =>
  mode.value === 'exact'
    ? Object.values(exact.value).reduce((s, v) => s + v, 0)
    : Object.values(preview.value ?? {}).reduce((s, v) => s + v, 0),
)
const balanced = computed(() => !props.amount || previewTotal.value === props.amount)

watch(
  [rule, () => props.amount, touched, balanced],
  () => {
    emit('change', touched.value ? rule.value : null, balanced.value, props.amount - previewTotal.value)
  },
  { immediate: true, deep: true },
)

function onModeChange() {
  touched.value = true
  if (mode.value === 'exact' && props.amount && preview.value) {
    exact.value = { ...preview.value }        // 从比例切过来时，带着刚才算好的数字，不用重敲
  }
}

function bump(id: number, delta: number) {
  touched.value = true
  const key = String(id)
  weights.value = { ...weights.value, [key]: Math.max(0, (weights.value[key] ?? 0) + delta) }
}

function digits(e: Event, allowNegative: boolean): number {
  const raw = (e.target as HTMLInputElement).value
  const neg = allowNegative && raw.trim().startsWith('-')
  const n = Number(raw.replace(/\D/g, '') || 0)
  return neg ? -n : n
}

function onExactInput(id: number, e: Event) {
  touched.value = true
  exact.value = { ...exact.value, [String(id)]: digits(e, true) }
}

function onAdjInput(id: number, e: Event) {
  touched.value = true
  const v = digits(e, true)
  const next = { ...adjustments.value }
  if (v === 0) delete next[String(id)]
  else next[String(id)] = v
  adjustments.value = next
}

const exactDisplay = (id: number) => {
  const v = exact.value[String(id)] ?? 0
  return v ? v.toLocaleString('en-US') : ''
}
const adjDisplay = (id: number) => {
  const v = adjustments.value[String(id)]
  return v ? v.toLocaleString('en-US') : ''
}

/** 父组件切完分类想恢复默认时调它 */
defineExpose({
  reset() {
    touched.value = false
    mode.value = 'ratio'
    resetWeights()
  },
})
</script>

<style scoped>
.mode-toggle { border: 1px solid rgba(0, 0, 0, 0.12); border-radius: 8px; }

/* 375px 下的列宽预算：左右各 16 padding → 343 可用。
   固定列 84+66+84 = 234，名字列拿剩下的并在必要时省略号收缩。 */
.head-row { padding-bottom: 2px; }
.name-col { min-width: 0; }
.weight-col { width: 112px; }
.adj-col { width: 62px; }
.exact-col { width: 150px; }
.share-col { width: 78px; text-align: right; font-variant-numeric: tabular-nums; font-size: 15px; }

.member-row { min-height: 48px; }
/* 44px 说的是**按钮本身**，不是整行 —— 原来 ± 只有 24×24，
   三行挤在一起，拇指很容易点到相邻的那个甚至相邻成员 */
.member-row :deep(.q-btn) { min-width: 40px; min-height: 40px; }
.name { font-size: 15px; }
.weight {
  min-width: 24px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  font-size: 16px;
}
.num-input {
  width: 100%;
  border: none;
  border-bottom: 1px solid rgba(0, 0, 0, 0.2);
  outline: none;
  background: transparent;
  text-align: right;
  font-size: 15px;
  padding: 4px 2px;
  font-variant-numeric: tabular-nums;
  color: inherit;
}
.num-input::placeholder { color: #ccc; }
.total-bar { font-size: 15px; }
</style>
