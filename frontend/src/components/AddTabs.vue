<!-- 记一笔那屏顶上的四格：支出 / 收入 / 转账 / 备忘。

     前三个产生一笔账，第四个不产生 —— 但站在这一屏上它们是同一个问题的四个答案：
     「我现在要往家里记点什么」。所以选中备忘时是**中性灰**，不借用任何一种
     记账类型的颜色。

     **和 BillTabs、EntriesTabs 一个写法：布局直接画在固定顶栏里，状态放 store。**
     原来是页面自己 Teleport 进顶栏的 —— 三屏里只有它这么写：顶栏在页面挂载
     那一拍才多出这一条，布局得事后再量一次、再把内容往下推。

     改一笔已有的账时不在这儿画（那屏顶上站着返回条，类型选择在页面里）。 -->
<template>
  <q-btn-toggle
    v-model="pane"
    spread no-caps unelevated
    :toggle-color="memos.addTab === 'memo' ? 'grey-7' : KIND_PALETTE[memos.addKind]"
    class="kind-toggle"
    :options="options"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { EntryKind } from 'src/api/types'
import { useMemos } from 'src/stores/memos'
import { KIND_PALETTE } from 'src/theme'

const { t } = useI18n()
const memos = useMemos()

const pane = computed({
  get: () => (memos.addTab === 'memo' ? 'memo' : memos.addKind),
  set: (v: string) => {
    memos.addTab = v === 'memo' ? 'memo' : 'add'
    if (v !== 'memo') memos.addKind = v as EntryKind
  },
})

const options = computed(() => [
  { label: t('kind.expense'), value: 'expense' },
  { label: t('kind.income'), value: 'income' },
  { label: t('kind.settlement'), value: 'settlement' },
  { label: t('entries.tabMemo'), value: 'memo' },
])
</script>

<!-- .kind-toggle 的样式在 src/css/tokens.css 里 —— 编辑一笔账时页面里那条共用同一份 -->
