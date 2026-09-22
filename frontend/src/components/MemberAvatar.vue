<!--
  一个人的头像：设过图就显示图，没设过就是那个带首字的色圆。

  全站统一走这里 —— 账单的每人、分摊面板、个人设置都要用，各写各的话
  换了头像只有一处会变。
-->
<template>
  <q-avatar
    :size="size"
    :style="member?.avatar ? undefined : { background: member?.color ?? FALLBACK }"
    text-color="white"
  >
    <img v-if="member?.avatar" :src="member.avatar" :alt="member.display_name" />
    <template v-else>{{ (member?.display_name ?? '?').slice(0, 1) }}</template>
  </q-avatar>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { useMeta } from 'src/stores/meta'
import { FALLBACK } from 'src/palette'

const props = withDefaults(defineProps<{ memberId?: number | null; size?: string }>(), {
  memberId: null,
  size: '30px',
})

const meta = useMeta()
const member = computed(() => (props.memberId == null ? null : meta.byId[props.memberId]))
</script>
