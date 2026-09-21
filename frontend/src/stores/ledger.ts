import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from 'src/api/client'
import type { Entry, EntryPayload } from 'src/api/types'
import { useBills } from 'src/stores/bills'

export const useLedger = defineStore('ledger', () => {
  const entries = ref<Entry[]>([])
  const balances = ref<Record<string, number>>({})
  const loading = ref(false)
  /** 上一张出过的账单是什么时候切的。用来挡住把日期选回已出账的范围里 */
  const prevCutAt = ref<string | null>(null)
  const prevLabel = ref<string | null>(null)
  /**
   * 账目是一次性拉这么多笔。筛选和合计都在前端算，所以**拉少了就筛不全**。
   * 三个人按种子数据的速率大约每年一百笔，500 笔够五年 —— 到那天不能让合计
   * 悄悄少算，得先说出来。truncated 就是「还有更早的没拉到」
   */
  const LIMIT = 500
  const truncated = ref(false)

  async function refresh() {
    loading.value = true
    try {
      const [e, b, bill] = await Promise.all([
        // 筛选在前端做，拉少了就筛不全
        api.get<Entry[]>(`/api/entries?limit=${LIMIT}`),
        api.get<{ balances: Record<string, number> }>('/api/balances'),
        api.get<{ prev_cut_at: string | null; prev_label: string | null }>('/api/bill'),
      ])
      entries.value = e
      truncated.value = e.length >= LIMIT
      balances.value = b.balances
      prevCutAt.value = bill.prev_cut_at
      prevLabel.value = bill.prev_label
    } finally {
      loading.value = false
    }
  }

  /** 存完用**后端返回的 shares 覆盖本地预览值** —— 以后端为准（SPEC §7.3）。 */
  async function create(payload: EntryPayload): Promise<Entry> {
    const saved = await api.post<Entry>('/api/entries', payload)
    entries.value = [saved, ...entries.value]
    const b = await api.get<{ balances: Record<string, number> }>('/api/balances')
    balances.value = b.balances
    // 账单那几页缓存着，记完这笔它们就旧了。后台刷，不清空 ——
    // 清空的话下次点过去又要白屏等一遍
    useBills().refreshCached()
    return saved
  }

  /** 改一笔。version 是乐观锁：传你读到的那个，被人改过就会被后端挡下来 */
  async function update(id: number, version: number, payload: Partial<EntryPayload>): Promise<Entry> {
    const saved = await api.patch<Entry>(`/api/entries/${id}?version=${version}`, payload)
    entries.value = entries.value.map((e) => (e.id === id ? saved : e))
    const b = await api.get<{ balances: Record<string, number> }>('/api/balances')
    balances.value = b.balances
    useBills().refreshCached()
    return saved
  }

  async function remove(entry: Entry) {
    await api.del(`/api/entries/${entry.id}`)
    entries.value = entries.value.filter((e) => e.id !== entry.id)
    const b = await api.get<{ balances: Record<string, number> }>('/api/balances')
    balances.value = b.balances
    useBills().refreshCached()
  }

  return {
    entries, balances, loading, truncated, prevCutAt, prevLabel,
    refresh, create, update, remove,
  }
})
