<!-- 金额输入：大字号、居中、唤起系统数字键盘。
     日元没有小数，所以 inputmode="numeric" 就够 —— 不需要自绘小键盘。 -->
<template>
  <div class="amount-wrap" :style="{ color: props.color }" @click="focus">
    <span class="sym">{{ symbol }}</span>
    <input
      ref="el"
      class="amount"
      type="text"
      inputmode="numeric"
      enterkeyhint="done"
      :placeholder="'0'"
      :style="{ width: widthCh }"
      :value="display"
      @input="onInput"
      @focus="onFocus"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ modelValue: number; color?: string }>()
const emit = defineEmits<{ 'update:modelValue': [number] }>()

const { locale } = useI18n()
const el = ref<HTMLInputElement | null>(null)

const symbol = computed(() => (locale.value === 'ja' ? '￥' : '¥'))
const display = computed(() => (props.modelValue ? props.modelValue.toLocaleString('en-US') : ''))

// 输入框按内容宽度伸缩，这样 ¥ 始终贴着数字，而不是被甩到屏幕最左边。
// 逗号比数字窄，所以按逗号数折算一下，否则右边会多出一块空白。
const widthCh = computed(() => {
  const text = display.value || '0'
  const commas = (text.match(/,/g) ?? []).length
  // 末尾那 0.3ch 是**留给字形的余量**：正好按 1ch 算的话框子和「0」一样宽，
  // 一丝不差，遇上亚像素取整就会把字边削掉一条，看着像被遮住了
  return `${Math.max(1, text.length - commas * 0.55) + 0.3}ch`
})

function onInput(e: Event) {
  const digits = (e.target as HTMLInputElement).value.replace(/\D/g, '')
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
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  padding: 18px 12px 10px;
  cursor: text;
}
.sym {
  font-size: 26px;
  opacity: 0.5;                 /* 跟着金额一个色，只是淡一档 */
}
.amount {
  color: inherit;
  font-size: 46px;
  font-weight: 600;
  /* 1.1 在 46px 下太紧：input 会裁掉超出内容框的字形，高个儿的数字上沿就没了 */
  line-height: 1.3;
  border: none;
  outline: none;
  background: transparent;
  text-align: left;
  min-width: 1ch;
  max-width: 260px;
  font-variant-numeric: tabular-nums;
  color: inherit;
}
.amount::placeholder { color: #d0d0d0; }
</style>
