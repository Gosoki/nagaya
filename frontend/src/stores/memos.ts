/**
 * 备忘。
 *
 * 两样东西拼成一屏：
 *   * **固定费那几项**的常驻备忘 —— 写在 Category.note 上。它们本来就是一份
 *     现成的清单，不必再抄一遍；而且「水费隔月收」这种事每期都成立，
 *     写进某一笔账的备注里，下个月就找不着了
 *   * **清单之外的**条目 —— 备用钥匙放哪、垃圾袋买哪种、房东电话。这些没有
 *     天然的归属，才需要这张 memo 表
 *
 * 那个页签的状态也放这儿：页签本身渲染在布局的固定顶栏上（切换时不重建），
 * 内容在页面里，两边得看同一份状态。和账单那两页一个做法 —— 不走路由，不改地址。
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { api } from 'src/api/client'
import type { EntryKind, Memo } from 'src/api/types'

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

export const useMemos = defineStore('memos', () => {
  const tab = ref<EntriesTab>(savedTab())
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
  watch(tab, (v) => {
    try {
      sessionStorage.setItem(TAB_KEY, v)
    } catch {
      /* 隐私模式下存不了就算了 */
    }
  })

  const items = ref<Memo[]>([])
  const loaded = ref(false)

  async function load() {
    items.value = await api.get<Memo[]>('/api/memos')
    loaded.value = true
  }

  async function create(title: string): Promise<Memo> {
    const saved = await api.post<Memo>('/api/memos', { title })
    items.value = [...items.value, saved]
    return saved
  }

  async function update(id: number, patch: Partial<Pick<Memo, 'title' | 'body'>>) {
    const saved = await api.patch<Memo>(`/api/memos/${id}`, patch)
    items.value = items.value.map((m) => (m.id === id ? saved : m))
    return saved
  }

  async function remove(id: number) {
    await api.del(`/api/memos/${id}`)
    items.value = items.value.filter((m) => m.id !== id)
  }

  return { tab, addTab, addKind, goAddHome, items, loaded, load, create, update, remove }
})
