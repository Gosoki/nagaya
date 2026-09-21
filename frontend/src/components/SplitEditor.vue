<!--
  分摊编辑器 —— SPEC §7.4 点名的「最难的一屏」。

  每人一行：头像 + 权重 + 调整额 + 实时金额。

  **只有「按比例」一种模式。** 原来还有个「固定金额」模式，但它是冗余的：
  权重全 1、调整额填「目标金额 − 均分额」就能表达任意一组金额（家賃
  45,000/40,000/35,000 ＝ 权重 1:1:1 加 +5,000/0/−5,000）。而且比例模式永远
  自动配平，压根出不了「合计对不上」那种不自洽的状态 —— 那道保护本来就是
  固定金额模式自己招来的。

  预览用前端的分摊引擎算（本地即时，不往返服务器）；**保存后以后端返回的
  shares 为准**，两边靠共享 fixture 锁住不漂（SPEC §7.3）。
-->
<template>
  <div>
    <!-- 列头：比例 / 调整 / 应担 三件事摆在一排，一眼看得出它们的关系。
         调整额原来藏在下面一个折叠里，看不见它是加在比例结果之上的 -->
    <div class="head-row text-caption text-grey-6">
      <div />
      <!-- 比例那格是块居中的药丸，不是右对齐的数字，表头跟着它居中 -->
      <div class="text-center">{{ t('split.weight') }}</div>
      <div class="text-right">{{ t('split.adjustment') }}</div>
      <div class="text-right">{{ t('split.share') }}</div>
    </div>

    <div
      v-for="m in members"
      :key="m.id"
      class="member-row"
      :class="{ out: weightOf(m.id) === 0 }"
    >
      <!-- 点头像/名字＝这个人这笔不参与（比例设 0），再点一下恢复。
           「谁没在」是改分摊时最常做的事，不该还要先点开比例再选一次 -->
      <button class="name-col row items-center no-wrap" @click="toggleOut(m.id)">
        <MemberAvatar :member-id="m.id" class="q-mr-sm" />
        <div class="name ellipsis">{{ m.display_name }}</div>
      </button>

      <!-- 比例不用输入框：真机 iOS 上 type=number 没有上下箭头，
           改个 0/1 得弹出数字键盘挡半屏。点一下直接选，全程不碰键盘 -->
      <div class="weight-col">
        <button class="weight-pill" :class="{ off: weightOf(m.id) === 0 }">
          {{ weightOf(m.id) }}
          <q-popup-proxy cover transition-show="jump-down">
            <div class="weight-pick row no-wrap">
              <button
                v-for="n in WEIGHT_CHOICES"
                :key="n"
                v-close-popup
                class="pick"
                :class="{ on: weightOf(m.id) === n }"
                @click="setWeight(m.id, n)"
              >
                {{ n }}
              </button>
            </div>
          </q-popup-proxy>
        </button>
      </div>
        <div class="adj-col">
          <input
            class="num-input"
            type="text"
            inputmode="text"
            placeholder="0"
            :value="adjDisplay(m.id)"
            @input="onAdjInput(m.id, $event)"
          />
        </div>

      <!-- 还没填金额时给一条短横，不是一排 ¥0。
           ¥0 是个**看起来算过了**的数字，而这时候根本没得算 —— 固定费那一屏
           一排全是 ¥0，看着就像坏了 -->
      <div
        class="share-col"
        :class="{ 'text-grey-5': !amount || (preview?.[String(m.id)] ?? 0) === 0 }"
      >
        {{ amount ? formatYen(preview?.[String(m.id)] ?? 0) : '—' }}
      </div>
    </div>

    <q-separator class="q-my-sm" />

    <div class="row items-center total-bar">
      <div class="text-grey-7">{{ t('split.total') }}</div>
      <q-space />
      <div :class="!amount ? 'text-grey-5' : balanced ? 'text-grey-8' : 'text-negative text-weight-medium'">
        {{ amount ? formatYen(previewTotal) : '—' }}
        <span v-if="amount && !balanced">（{{ t('split.diff') }} {{ formatYen(amount - previewTotal) }}）</span>
      </div>
    </div>
    <div v-if="error" class="text-negative text-caption q-mt-xs">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Member } from 'src/api/types'
import MemberAvatar from 'src/components/MemberAvatar.vue'
import { SplitError, split } from 'src/core/split'
import { formatYen } from 'src/i18n'
import { useMeta } from 'src/stores/meta'

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
  /**
   * 这笔账的 id。只在「余数归谁 ＝ 逐笔轮转」时才用得上 —— 后端的轮转依据是
   * `entry.id`，不给的话这边恒为 0，除不尽的每一笔（三个人分摊里大多数）
   * 预览和落库指的就不是同一个人。改已有的账时 id 是已知的，先把这一半补上；
   * 新记的那一笔在保存之前没有 id，那 1 円归谁只能以后端为准。
   */
  entryId?: number | null
  /** 段选中态的颜色，跟着账目类型走（支出蓝 / 收入绿 / 转账黄）。固定费面板不传，就是蓝 */
  color?: string
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
const meta = useMeta()

const weights = ref<Record<string, number>>({})
const adjustments = ref<Record<string, number>>({})
const touched = ref(false)

/**
 * 输入过程中**保留用户打的原文**，否则负号活不到下一个按键：
 * 光打一个「-」时数值还是 0，`:value` 会把框重绘成空，负号当场消失，
 * 于是「a 少担 1000」这种根本输不进去 —— 而它正是这个字段存在的理由。
 */
const typing = ref<Record<string, string>>({})

function resetWeights() {
  const seed = props.seedRule ?? null
  const seedMode = (seed?.mode as string) ?? 'ratio'
  const keys = props.members.map((m) => String(m.id))

  // 老数据里还有 mode:'exact' 的规则（界面上已经没有这个模式了）。
  // 原样换算成「权重全 1 + 调整额」：基数取 floor(总额/人数)，调整额就是
  // 各人金额减掉基数 —— 加回去一分不差。总额取规则自己的和，不依赖当前金额。
  if (seed && seedMode === 'exact') {
    const seeded = (seed.exact ?? {}) as Record<string, number>
    const total = keys.reduce((sum, k) => sum + Number(seeded[k] ?? 0), 0)
    const base = Math.floor(total / (keys.length || 1))
    weights.value = Object.fromEntries(keys.map((k) => [k, 1]))
    adjustments.value = Object.fromEntries(
      keys.map((k) => [k, Number(seeded[k] ?? 0) - base]).filter(([, v]) => v !== 0),
    )
    typing.value = {}
    return
  }

  const seededW = (seed?.weights ?? null) as Record<string, number> | null
  const equal = Number(seed?.equal_weight ?? 1)
  weights.value = Object.fromEntries(
    keys.map((k) => [k, seededW ? Number(seededW[k] ?? 0) : equal]),
  )
  const seededAdj = (seed?.adjustments ?? {}) as Record<string, number>
  adjustments.value = Object.fromEntries(
    Object.entries(seededAdj).filter(([k, v]) => keys.includes(k) && Number(v) !== 0),
  )
  typing.value = {}
}
resetWeights()
/**
 * 参与人变了。
 *
 * **已经调过的比例不能被抹掉。** 参与人这个列表会因为各种与用户无关的原因
 * 重新算一遍（成员刷新、自己那条记录晚到导致「自己排第一」的顺序变了……），
 * 每次都整体重置的话，用户刚调好的分摊会在某个说不清的时刻悄悄跳回默认 ——
 * 而屏幕上只是「数字自己变了一下」，没人看得出发生了什么。
 * 固定费面板那边早就是这个规矩（load() 保留还没保存的输入）。
 *
 * 所以：没动过的整体重来；动过的只补进新来的人、去掉走了的人。
 */
watch(
  () => props.members.map((m) => m.id).join(','),
  () => {
    if (!touched.value) {
      resetWeights()
      return
    }
    const keys = props.members.map((m) => String(m.id))
    weights.value = Object.fromEntries(keys.map((k) => [k, weights.value[k] ?? 1]))
    adjustments.value = Object.fromEntries(
      keys.filter((k) => adjustments.value[k]).map((k) => [k, adjustments.value[k]!]),
    )
  },
)
// 换了分类 → 换一套默认规则重来。touched 一并清掉，否则会把上一个分类的规则带过去。
// **只认真正换了内容的**：categoryById 重算一次就会给出一个内容相同的新对象，
// 按引用比的话，一次无关的成员刷新就能把用户调好的比例冲掉
watch(
  () => JSON.stringify(props.seedRule ?? null),
  () => {
    touched.value = false
    resetWeights()
  },
)

const rule = computed<Record<string, unknown>>(() => ({
  mode: 'ratio',
  weights: weights.value,
  adjustments: adjustments.value,
  // 余数归谁是**设置项**，不是代码里写死的值。写死成 'payer' 的话，面板上
  // 改了不生效，而且这条死值还会随规则一起存进 split_rule_json，把设置永久钉住
  remainder_to: meta.setting<string>('remainder_to', 'payer'),
}))

/**
 * 喂给分摊算法的成员顺序。**必须和后端一样（display_order）**，不能用
 * props.members 那个「自己排第一」的展示顺序 —— 最大余数法平局时是靠成员在
 * 这个数组里的下标决胜的，顺序一换，多出来的那 1 円就落到别人头上：
 * 三人等分、金额除以 3 余 2 时（日常账里约三分之一），换个人登录，
 * 预览里多担 1 円的就换一个人，而库里存的始终是后端那一份。
 */
const order = computed(() =>
  [...props.members]
    .sort((a, b) => a.display_order - b.display_order || a.id - b.id)
    .map((m) => String(m.id)),
)
const error = ref('')

const preview = computed<Record<string, number> | null>(() => {
  error.value = ''
  if (!props.amount) return null
  try {
    return split(rule.value as never, props.amount, {
      order: order.value,
      payer: props.payerId === null ? null : String(props.payerId),
      rotateSeed: props.entryId ?? 0,
    })
  } catch (e) {
    // 权重全 0 时不另外红一行「没人参与分摊」：底下的合计已经把缺口报出来了，
    // 而且旁边就写着「权重 0 ＝ 不参与」，再说一遍是噪音
    if (e instanceof SplitError && e.code !== 'weights_all_zero') error.value = e.message
    return null
  }
})

const previewTotal = computed(() =>
  Object.values(preview.value ?? {}).reduce((s, v) => s + v, 0),
)

/**
 * 比例模式**几乎**永远配平 —— 调整额再怎么填都会从基数里扣回来。
 * 唯一的例外是三个人权重全填 0：那就没人担这笔钱，整笔悬空。
 * 这时候要把缺多少报出来，并且不许存。
 */
const balanced = computed(() => !props.amount || previewTotal.value === props.amount)

watch(
  [rule, () => props.amount, touched, balanced],
  () => {
    emit('change', touched.value ? rule.value : null, balanced.value, props.amount - previewTotal.value)
  },
  { immediate: true, deep: true },
)

/** 三四个室友，权重再高也就是「谁用得多一倍」。给到 3 足够，多了反而挑花眼 */
const WEIGHT_CHOICES = [0, 1, 2, 3]

const weightOf = (id: number) => weights.value[String(id)] ?? 0

function setWeight(id: number, n: number) {
  touched.value = true
  weights.value = { ...weights.value, [String(id)]: n }
}

/** 设成 0 之前那个人是几，恢复时原样还回去（不是一律变回 1） */
const lastNonZero = ref<Record<string, number>>({})

function toggleOut(id: number) {
  const key = String(id)
  const now = weightOf(id)
  if (now === 0) {
    setWeight(id, lastNonZero.value[key] ?? 1)
  } else {
    lastNonZero.value = { ...lastNonZero.value, [key]: now }
    setWeight(id, 0)
  }
}

function normalize(raw: string): { text: string; value: number } {
  const neg = raw.trim().startsWith('-')
  const d = raw.replace(/\D/g, '')
  const n = d ? Number(d) : 0
  const sign = neg ? '-' : ''
  return { text: d ? sign + n.toLocaleString('en-US') : sign, value: neg ? -n : n }
}

function onAdjInput(id: number, e: Event) {
  touched.value = true
  const { text, value } = normalize((e.target as HTMLInputElement).value)
  typing.value = { ...typing.value, [`a${id}`]: text }
  const next = { ...adjustments.value }
  if (value === 0) delete next[String(id)]
  else next[String(id)] = value
  adjustments.value = next
}

const adjDisplay = (id: number) => {
  const held = typing.value[`a${id}`]
  if (held !== undefined) return held
  const v = adjustments.value[String(id)]
  return v ? v.toLocaleString('en-US') : ''
}

/** 父组件切完分类想恢复默认时调它 */
defineExpose({
  reset() {
    touched.value = false
    resetWeights()
  },
})
</script>

<style scoped>

/* 列宽按内容的体量分，不是一刀切四等分：
     · 调整和应担都是钱，必须等宽 —— 数字对不齐一眼就看出来歪
     · 比例只装一位数，给 56px 刚好放下那颗药丸；等分的话是个大空框
     · 剩下的全给名字
   表头和下面的值共用同一套 grid 列，所以不可能错位。 */
.head-row,
.member-row {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) 56px minmax(0, 1fr) minmax(0, 1fr);
  align-items: center;
  column-gap: 6px;
}
.head-row {
  padding-bottom: 4px;
  margin-bottom: 2px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);   /* 把表头和它管的那几列绑在一起 */
  font-size: 11px;
  letter-spacing: 0.04em;
}
.name-col {
  min-width: 0;
  border: none;
  background: transparent;
  padding: 0;
  text-align: left;
  color: inherit;
  cursor: pointer;
}
/* 比例和调整之间留一道明显的空 —— 它们是两种不同的输入，不该挨在一起 */
.adj-col { padding-left: 14px; }
.share-col { text-align: right; font-variant-numeric: tabular-nums; font-size: 15px; }

.member-row { min-height: 48px; }
/* 权重 0 ＝ 这个人这笔不参与。整行压灰，1:1:0 一眼就认得出来 */
.member-row.out .name,
.member-row.out .share-col { color: #bdbdbd; }
.member-row.out .q-avatar { opacity: 0.45; }
.name { font-size: 15px; }
/* 数字框本身要够高：44px 说的是**可点区域**，输入框太矮拇指点不准 */
/* 比例那颗药丸：44px 是可点区域的底线，拇指点得准 */
.weight-col { display: flex; justify-content: center; }
/* 药丸只占 48px 宽（44 高仍然够拇指点）。撑满整列的话是个大盒子，
   右边又紧贴着调整的下划线，两种输入样式挤在一起看着就乱 */
.weight-pill {
  width: 48px;
  min-height: 44px;                    /* 拇指的底线 */
  border: none;
  border-radius: 8px;
  background: #f2f2f5;
  color: #222;
  font-size: 16px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.weight-pill.off {
  background: #fafafa;
  color: #bdbdbd;
}
.weight-pick {
  padding: 4px;
}
.weight-pick .pick {
  min-width: 46px;
  min-height: 46px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #333;
  font-size: 17px;
  cursor: pointer;
}
.weight-pick .pick.on {
  background: #3d4785;
  color: #fff;
  font-weight: 600;
}
.weight-input::-webkit-outer-spin-button,
.weight-input::-webkit-inner-spin-button {
  opacity: 1;                 /* 桌面上把上下箭头显出来，手机上本来就没有 */
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
  height: 40px;              /* 行高 48，输入框占满大半 —— 拇指点得准 */
  font-variant-numeric: tabular-nums;
  color: inherit;
}
.num-input::placeholder { color: #ccc; }
.total-bar { font-size: 15px; }
</style>
