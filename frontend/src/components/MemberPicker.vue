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
      {{ m.display_name.slice(0, 2) }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { Member } from 'src/api/types'

defineProps<{ modelValue: number | null; members: Member[] }>()
const emit = defineEmits<{ 'update:modelValue': [number] }>()
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
