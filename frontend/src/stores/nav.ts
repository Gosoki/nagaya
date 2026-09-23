/**
 * 两屏的页签状态：「更多」那屏（流水 / 设置），和「记一笔」那屏（记账 / 备忘，以及记新账选的类型）。
 *
 * 页签本身渲染在布局的固定顶栏上（切换时不重建），内容在页面里，两边得看同一份状态。
 * 和账单那两页一个做法 —— 不走路由，不改地址。账单那两页的 tab 不在这儿：
 * 它和账单缓存（翻到的旧账单 detail）绑在一起，留在 bills store。
 *
 * 原来这些放在备忘 store 里 —— 那时备忘还是「更多」里的一个页签。
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import type { EntryKind } from 'src/api/types'

type EntriesTab = 'ledger' | 'settings'
type AddTab = 'add' | 'memo'
const TAB_KEY = 'nagaya.entriesTab'

function savedTab(): EntriesTab {
  try {
    if (sessionStorage.getItem(TAB_KEY) === 'settings') return 'settings'
  } catch {
    /* 隐私模式下读不了 */
  }
  return 'ledger'
}

export const useNav = defineStore('nav', () => {
  const entriesTab = ref<EntriesTab>(savedTab())
  // 备忘在「记一笔」那屏。**不记进 sessionStorage**：记一笔是 PWA 的
  // 落地页，上次停在备忘上、下次打开就不是「打开即记账」了
  const addTab = ref<AddTab>('add')
  /**
   * 记新账时选的类型（支出/收入/转账）。和 addTab 一样放在这儿：顶上那条
   * 由布局画在固定顶栏里（AddTabs），表单在页面里，两边得看同一份。
   * 改一笔已有的账时不用它 —— 那时类型是那笔账自己的（见 AddEntryPage）
   */
  const addKind = ref<EntryKind>('expense')

  /**
   * 底栏点了「记一笔」：回到这一屏的起点 —— 表单那一面、类型是支出。
   * 人已经站在这一屏上时，底栏那一下不会触发路由跳转，上次选的「转账」
   * 会一直留着；而底栏那一格的意思是「我要记一笔」，记的绝大多数是支出
   */
  function goAddHome() {
    addTab.value = 'add'
    addKind.value = 'expense'
  }
  watch(entriesTab, (v) => {
    try {
      sessionStorage.setItem(TAB_KEY, v)
    } catch {
      /* 隐私模式下存不了就算了 */
    }
  })

  return { entriesTab, addTab, addKind, goAddHome }
})
