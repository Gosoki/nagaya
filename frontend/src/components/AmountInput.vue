<!-- 金额输入：大字号、居中、唤起系统数字键盘。
     日元没有小数，所以 inputmode="numeric" 就够 —— 不需要自绘小键盘。 -->
<template>
  <!-- 日文里日元是**后缀**（12,345円），中文是前缀（¥12,345）—— 全站的
       formatYen 一直是这么写的，只有这个最常用的输入框自己拼了个前缀「￥」。
       录数字时看到的记法和录完之后在账单、流水里看到的不一样，第一反应是
       「我是不是填错框了」 -->
  <div class="amount-wrap" :class="{ suffix: symbolAfter }" :style="{ color: props.color }" @click="focus">
    <span v-if="!symbolAfter" class="sym">{{ symbol }}</span>
    <!-- 替身：和输入框同一套字形，专门用来量「这串数字到底多宽」。
         看不见、不占位、不接事件 -->
    <span ref="ghost" class="ghost amount" aria-hidden="true">{{ display || '0' }}</span>
    <input
      ref="el"
      class="amount"
      type="text"
      inputmode="numeric"
      enterkeyhint="done"
      :aria-label="t('entry.amountLabel')"
      :placeholder="'0'"
      :style="{ width: width }"
      :value="display"
      @input="onInput"
      @compositionend="onInput"
      @focus="onFocus"
    />
    <span v-if="symbolAfter" class="sym">{{ symbol }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { digitsOf } from 'src/digits'

const props = defineProps<{ modelValue: number; color?: string }>()
const emit = defineEmits<{ 'update:modelValue': [number] }>()

const { t, locale } = useI18n()
const el = ref<HTMLInputElement | null>(null)

// 符号本身也是文案，走 i18n（有守卫用例钉着「不许把界面文字写死在组件里」）。
// 日文里日元是后缀，中文是前缀 —— 和全站的 formatYen 对齐
const symbolAfter = computed(() => locale.value === 'ja')
const symbol = computed(() => t('common.currency'))
const display = computed(() => (props.modelValue ? props.modelValue.toLocaleString('en-US') : ''))

/**
 * 输入框按内容宽度伸缩，这样 ¥ 始终贴着数字，而不是被甩到屏幕最左边。
 *
 * **量出来，不靠估。** 原来是按 ch 折算的（数字 1ch、逗号 0.55ch），
 * 在 macOS 上就已经比真实宽度少 2px，「12,800,000」正好卡在被裁掉一条边上；
 * 换一套系统字体（iOS）差得更多，屏幕上就是数字左右各被切掉一点。
 * 现在拿一个同字形的替身量出真实像素，再加 2px 的字形余量。
 */
const ghost = ref<HTMLElement | null>(null)
const width = ref('1ch')

function measure() {
  const w = ghost.value?.getBoundingClientRect().width
  if (w) width.value = `${Math.ceil(w) + 2}px`
}

watch(display, () => void nextTick(measure), { immediate: true })
onMounted(() => {
  measure()
  // 系统字体是异步就绪的：字一换宽度就变了，得再量一次
  void (document as Document & { fonts?: FontFaceSet }).fonts?.ready.then(measure)
})

function onInput(e: Event) {
  // 输入法还在拼字（日文键盘）时别去改框里的值 —— 改了会把拼到一半的字打断，
  // 等 compositionend 再算一次
  if ((e as InputEvent).isComposing) return
  const digits = digitsOf((e.target as HTMLInputElement).value)
  // 上限挡一下手滑：一千万円以上基本是多打了 0
  const n = Math.min(Number(digits || 0), 99_999_999)
  emit('update:modelValue', n)
  void nextTick(() => {
    if (el.value) el.value.value = n ? n.toLocaleString('en-US') : ''
  })
}

function onFocus() {
  el.value?.select()
}

function focus() {
  el.value?.focus()
}

defineExpose({ focus })
</script>

<style scoped>
.amount-wrap {
  position: relative;           /* 替身贴在这儿，不占位 */
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  padding: 12px 12px 6px;
  cursor: text;
}
.sym {
  font-size: 26px;
  opacity: 0.5;                 /* 跟着金额一个色，只是淡一档 */
}
/* 后缀那一版字略小些：「円」是个汉字，和 ¥ 同号会显得比数字还抢眼 */
.amount-wrap.suffix .sym { font-size: 22px; }
.amount {
  color: inherit;
  /* **必须写死继承**：WebKit 给表单控件配的是另一套默认字体，不写的话
     输入框和替身（普通 span）量出来不是同一个宽度，差的那几像素正好把
     数字的边削掉一条。顺带 padding 清零 —— input 自带左右各 2px */
  font-family: inherit;
  padding: 0;
  font-size: 46px;
  font-weight: 600;
  /* 1.1 在 46px 下太紧：input 会裁掉超出内容框的字形，高个儿的数字上沿就没了 */
  line-height: 1.3;
  border: none;
  outline: none;
  background: transparent;
  text-align: left;
  min-width: 1ch;
  /* 只受屏幕限制，不再写死一个 260 —— 最长的「99,999,999」是 262px，
     那个上限正好把它裁掉一条边 */
  max-width: 100%;
  font-variant-numeric: tabular-nums;
  color: inherit;
}
.amount::placeholder { color: var(--nagaya-ink-5); }
/* 替身和输入框共用 .amount 的字形，只是看不见也不占地方 */
.ghost {
  position: absolute;
  left: 0;
  top: 0;
  visibility: hidden;
  pointer-events: none;
  white-space: pre;
  width: auto;
  max-width: none;
}
</style>
