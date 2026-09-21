<!-- 成员选择：一排头像，点一下就换。比下拉菜单少一次点击。 -->
<template>
  <div class="row items-center q-gutter-xs">
    <button
      v-for="m in members"
      :key="m.id"
      class="pick"
      :class="{ on: modelValue === m.id }"
      :style="modelValue === m.id ? { background: m.color } : {}"
      :data-label="short(m.display_name)"
      @click="emit('update:modelValue', m.id)"
    >
      <span class="label">{{ short(m.display_name) }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import type { Member } from 'src/api/types'

defineProps<{ modelValue: number | null; members: Member[] }>()
const emit = defineEmits<{ 'update:modelValue': [number] }>()

/** 名字短就整个显示。硬截两个字会把 Kan / Zen 变成「Ka」「Ze」，难看又难认 */
const short = (name: string) => (name.length <= 4 ? name : name.slice(0, 3))
</script>

<style scoped>
.pick {
  /* 网格：两层内容叠在同一格里，格子宽度取两者的最大值 */
  display: inline-grid;
  place-items: center;
  min-width: 54px;
  height: 42px;                 /* 34 太小了，一排三个挨着，拇指容易点到旁边那个 */
  padding: 0 14px;
  border-radius: 21px;
  border: none;
  background: #f2f2f5;
  color: #555;
  font-size: 15px;
  cursor: pointer;
}
/**
 * 选中要加粗，而加粗会让字变宽 —— 一排三个按钮，切一下整排就左右挪一下。
 *
 * 这里让每个按钮**永远按加粗后的宽度**占位：底下压一层看不见的粗体同款文字，
 * 由它把格子撑到最终宽度，上面那层再怎么切字重都不动它。
 */
.pick::before {
  content: attr(data-label);
  grid-area: 1 / 1;
  font-weight: 600;
  visibility: hidden;
}
.pick .label { grid-area: 1 / 1; }
.pick.on { color: #fff; font-weight: 600; }
</style>
