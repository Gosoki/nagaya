<!-- 成员选择：一排头像，点一下就换。比下拉菜单少一次点击。 -->
<template>
  <div class="row items-center q-gutter-xs">
    <button
      v-for="m in members"
      :key="m.id"
      class="pick"
      type="button"
      :aria-pressed="modelValue === m.id"
      :class="{ on: modelValue === m.id }"
      :style="modelValue === m.id ? { background: m.color } : {}"
      :data-label="short(m.display_name)"
      :aria-label="m.display_name"
      :title="m.display_name"
      @click="emit('update:modelValue', m.id)"
    >
      <span class="label">{{ short(m.display_name) }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import type { Member } from 'src/api/types'

const props = defineProps<{ modelValue: number | null; members: Member[] }>()
const emit = defineEmits<{ 'update:modelValue': [number] }>()

/**
 * 按钮上印几个字。名字短就整个显示（硬截两个字会把 Kan / Zen 变成「Ka」「Ze」）。
 * 长的从 3 个字起截，**和别人撞了就再多给一个字** —— 原来一律截 3 个，
 * 「Alexander / Alexandra」在「谁付的」里是两个一模一样的「Ale」
 */
function short(name: string): string {
  if (name.length <= 4) return name
  const others = props.members.map((m) => m.display_name).filter((n) => n !== name)
  for (let n = 3; n < name.length; n++) {
    const head = name.slice(0, n)
    if (!others.some((o) => o.slice(0, n) === head)) return head
  }
  return name
}
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
  background: var(--nagaya-fill);
  color: var(--nagaya-ink-2);
  font-size: 15px;
  cursor: pointer;
  transition: transform 0.12s, background-color 0.15s;
}
.pick:active { transform: scale(0.95); }
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
