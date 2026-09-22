import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from 'src/api/client'
import type { Entry, EntryPayload } from 'src/api/types'
import { useBills } from 'src/stores/bills'

/**
 * 账目列表。
 *
 * **写成功就是成功。** 写完之后的那些刷新（账单缓存、列表）一律不许把失败冒泡上来 ——
 * 原来 create/update/remove 都是 `await api.get('/api/balances')` 紧跟在写后面，
 * 于是「账已经记上了、只是后面那个 GET 断网了」会被调用方当成「这笔没记上」，
 * 原样存进离线草稿；补交时再 POST 一遍，账本里就有了两笔一模一样的钱。
 */
export const useLedger = defineStore('ledger', () => {
  const entries = ref<Entry[]>([])
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
      // 不拉 /api/balances：它存下来之后没有任何组件读过（余额页早就并进账单页了），
      // 每次开 App、每记一笔都白跑一个来回
      const [e, bill] = await Promise.all([
        // 筛选在前端做，拉少了就筛不全
        api.get<Entry[]>(`/api/entries?limit=${LIMIT}`),
        api.get<{ prev_cut_at: string | null; prev_label: string | null }>('/api/bill'),
      ])
      entries.value = e
      truncated.value = e.length >= LIMIT
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
    // 账单那几页缓存着，记完这笔它们就旧了。后台刷，不清空 ——
    // 清空的话下次点过去又要白屏等一遍。**失败也不冒泡**：这笔已经记上了
    useBills().refreshCached(saved)
    return saved
  }

  /** 改一笔。version 是乐观锁：传你读到的那个，被人改过就会被后端挡下来 */
  async function update(id: number, version: number, payload: Partial<EntryPayload>): Promise<Entry> {
    const saved = await api.patch<Entry>(`/api/entries/${id}?version=${version}`, payload)
    entries.value = entries.value.map((e) => (e.id === id ? saved : e))
    useBills().refreshCached(saved)
    return saved
  }

  async function remove(entry: Entry) {
    await api.del(`/api/entries/${entry.id}`)
    entries.value = entries.value.filter((e) => e.id !== entry.id)
    useBills().refreshCached(entry)
  }

  /** 撤销刚才那次删除。后端一直是软删，只是以前前端没接这个入口 */
  async function restore(id: number): Promise<Entry> {
    const back = await api.post<Entry>(`/api/entries/${id}/restore`)
    entries.value = [back, ...entries.value.filter((e) => e.id !== id)]
    useBills().refreshCached(back)
    return back
  }

  return {
    entries, loading, truncated, prevCutAt, prevLabel,
    refresh, create, update, remove, restore,
  }
})
