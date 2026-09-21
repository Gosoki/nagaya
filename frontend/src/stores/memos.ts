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
import type { Memo } from 'src/api/types'

export type EntriesTab = 'ledger' | 'memo' | 'settings'
const TAB_KEY = 'nagaya.entriesTab'

function savedTab(): EntriesTab {
  try {
    const v = sessionStorage.getItem(TAB_KEY)
    if (v === 'memo' || v === 'settings') return v
  } catch {
    /* 隐私模式下读不了 */
  }
  return 'ledger'
}

export const useMemos = defineStore('memos', () => {
  const tab = ref<EntriesTab>(savedTab())
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

  return { tab, items, loaded, load, create, update, remove }
})
