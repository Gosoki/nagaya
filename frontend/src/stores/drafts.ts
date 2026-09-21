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

import { ApiError, api } from 'src/api/client'
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

  /**
   * 补交。逐条提交，成功一条删一条 —— 中途再断网也不会重复提交已成功的。
   *
   * **区分「没网」和「后端不收」。** 原来一律算失败、一律报「连不上服务器」：
   * 一条被后端明确拒绝的草稿（金额为 0、分类被归档了、日期落进已出账范围）
   * 会永远卡在那儿，横幅一直挂着「有 1 笔没提交」，点多少次都是同一句错话，
   * 而真正的原因一个字都看不到。
   *
   * 被拒的那条照样留着（里面是用户真填过的钱，不能替他扔掉），但要把后端那句话
   * 带回去说清楚，让人知道该去改哪儿。
   */
  async function submitAll(): Promise<{ ok: number; offline: number; rejected: string[] }> {
    let ok = 0
    let offline = 0
    const rejected: string[] = []
    for (const draft of [...items.value]) {
      try {
        await api.post<Entry>('/api/entries', draft.payload)
        remove(draft.id)
        ok += 1
      } catch (e) {
        if (e instanceof ApiError && e.code !== 'network') rejected.push(e.text)
        else offline += 1
      }
    }
    return { ok, offline, rejected }
  }

  return { items, count, add, remove, clear, submitAll }
})
