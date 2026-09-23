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
 * 「记一笔」那屏上切到备忘的页签状态在 stores/nav.ts。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from 'src/api/client'
import type { Memo } from 'src/api/types'

export const useMemos = defineStore('memos', () => {
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

  return { items, loaded, load, create, update, remove }
})
