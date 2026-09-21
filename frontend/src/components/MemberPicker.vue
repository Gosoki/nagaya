<!-- 成员选择：一排头像，点一下就换。比下拉菜单少一次点击。 -->
<template>
  <div class="row items-center q-gutter-xs">
    <button
      v-for="m in members"
      :key="m.id"
      class="pick"
      :class="{ on: modelValue === m.id }"
      :style="modelValue === m.id ? { background: m.color, borderColor: m.color } : {}"
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
  min-width: 44px;
  height: 34px;
  padding: 0 10px;
  border-radius: 17px;
  border: 1px solid rgba(0, 0, 0, 0.16);
  background: #fff;
  color: #555;
  font-size: 13px;
  cursor: pointer;
}
.pick.on { color: #fff; font-weight: 600; }
</style>
