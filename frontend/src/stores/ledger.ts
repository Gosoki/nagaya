import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from 'src/api/client'
import type { Entry, EntryPayload } from 'src/api/types'

export const useLedger = defineStore('ledger', () => {
  const entries = ref<Entry[]>([])
  const balances = ref<Record<string, number>>({})
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      const [e, b] = await Promise.all([
        api.get<Entry[]>('/api/entries?limit=100'),
        api.get<{ balances: Record<string, number> }>('/api/balances'),
      ])
      entries.value = e
      balances.value = b.balances
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

  async function remove(entry: Entry) {
    await api.del(`/api/entries/${entry.id}`)
    entries.value = entries.value.filter((e) => e.id !== entry.id)
    const b = await api.get<{ balances: Record<string, number> }>('/api/balances')
    balances.value = b.balances
  }

  return { entries, balances, loading, refresh, create, remove }
})
