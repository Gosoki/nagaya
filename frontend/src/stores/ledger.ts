import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from 'src/api/client'
import type { Entry, EntryPayload } from 'src/api/types'

export const useLedger = defineStore('ledger', () => {
  const entries = ref<Entry[]>([])
  const balances = ref<Record<string, number>>({})
  const loading = ref(false)
  /** 上一张出过的账单是什么时候切的。用来挡住把日期选回已出账的范围里 */
  const prevCutAt = ref<string | null>(null)
  const prevLabel = ref<string | null>(null)

  async function refresh() {
    loading.value = true
    try {
      const [e, b, bill] = await Promise.all([
        api.get<Entry[]>('/api/entries?limit=100'),
        api.get<{ balances: Record<string, number> }>('/api/balances'),
        api.get<{ prev_cut_at: string | null; prev_label: string | null }>('/api/bill'),
      ])
      entries.value = e
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
    return saved
  }

  /** 改一笔。version 是乐观锁：传你读到的那个，被人改过就会被后端挡下来 */
  async function update(id: number, version: number, payload: Partial<EntryPayload>): Promise<Entry> {
    const saved = await api.patch<Entry>(`/api/entries/${id}?version=${version}`, payload)
    entries.value = entries.value.map((e) => (e.id === id ? saved : e))
    const b = await api.get<{ balances: Record<string, number> }>('/api/balances')
    balances.value = b.balances
    return saved
  }

  async function remove(entry: Entry) {
    await api.del(`/api/entries/${entry.id}`)
    entries.value = entries.value.filter((e) => e.id !== entry.id)
    const b = await api.get<{ balances: Record<string, number> }>('/api/balances')
    balances.value = b.balances
  }

  return { entries, balances, loading, prevCutAt, prevLabel, refresh, create, update, remove }
})
