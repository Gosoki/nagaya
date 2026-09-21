<!-- 成员选择：一排头像，点一下就换。比下拉菜单少一次点击。 -->
<template>
  <div class="row items-center q-gutter-xs">
    <button
      v-for="m in members"
      :key="m.id"
      class="pick"
      :class="{ on: modelValue === m.id }"
      :style="modelValue === m.id ? { background: m.color } : {}"
      @click="emit('update:modelValue', m.id)"
    >
      {{ short(m.display_name) }}
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
.pick.on { color: #fff; font-weight: 600; }
</style>
