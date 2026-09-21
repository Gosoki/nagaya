/**
 * 离线草稿 —— D15。
 *
 * 只做「没网时把这一笔留在本地」，**不做后台自动同步**：
 * 宁可让人点一下补交，也不要「以为存上了其实没有」。钱的事不能悄悄失败。
 *
 * localStorage 在隐私模式/禁用站点数据时会直接抛异常，所有读写都包了 try/catch，
 * 拿不到就当没有草稿 —— 不能因为存不了草稿把整个页面弄崩。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from 'src/api/client'
import type { Entry, EntryPayload } from 'src/api/types'

const KEY = 'nagaya.drafts'

export interface Draft {
  id: string
  savedAt: string
  payload: EntryPayload
}

function read(): Draft[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Draft[]) : []
  } catch {
    return []
  }
}

function write(list: Draft[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    /* 存不了就算了，至少别把页面弄崩 */
  }
}

export const useDrafts = defineStore('drafts', () => {
  const items = ref<Draft[]>(read())
  const count = computed(() => items.value.length)

  function add(payload: EntryPayload) {
    items.value = [
      ...items.value,
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, savedAt: new Date().toISOString(), payload },
    ]
    write(items.value)
  }

  function remove(id: string) {
    items.value = items.value.filter((d) => d.id !== id)
    write(items.value)
  }

  function clear() {
    items.value = []
    write(items.value)
  }

  /** 补交。逐条提交，成功一条删一条 —— 中途再断网也不会重复提交已成功的。 */
  async function submitAll(): Promise<{ ok: number; failed: number }> {
    let ok = 0
    let failed = 0
    for (const draft of [...items.value]) {
      try {
        await api.post<Entry>('/api/entries', draft.payload)
        remove(draft.id)
        ok += 1
      } catch {
        failed += 1
      }
    }
    return { ok, failed }
  }

  return { items, count, add, remove, clear, submitAll }
})
