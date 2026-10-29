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
  /**
   * 防旧响应（和 ledger.refresh 同一个办法）。打开备忘那一下发出去的 GET 还在路上，
   * 这边已经加了一条「房东电话」—— 那发回来的是加之前的列表，照写的话新加的那条
   * 从界面上消失，人会再加一遍。seq 认「我是不是最新那一发」，writes 认「我出发之后本地写过没有」
   */
  let seq = 0
  let writes = 0

  async function load(): Promise<void> {
    const my = ++seq
    const w = writes
    const got = await api.get<Memo[]>('/api/memos')
    if (my !== seq) return                       // 后面还有更新的一发，交给它
    if (w !== writes) return load()              // 途中本地写过：这份里没有它，再取一次
    items.value = got
    loaded.value = true
  }

  async function create(title: string): Promise<Memo> {
    const saved = await api.post<Memo>('/api/memos', { title })
    writes += 1
    items.value = [...items.value, saved]
    return saved
  }

  async function update(id: number, patch: Partial<Pick<Memo, 'title' | 'body'>>) {
    const saved = await api.patch<Memo>(`/api/memos/${id}`, patch)
    writes += 1
    items.value = items.value.map((m) => (m.id === id ? saved : m))
    return saved
  }

  async function remove(id: number) {
    await api.del(`/api/memos/${id}`)
    writes += 1
    items.value = items.value.filter((m) => m.id !== id)
  }

  return { items, loaded, load, create, update, remove }
})
