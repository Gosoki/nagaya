/**
 * 账单三页的数据。**缓存先上屏，后台校正。**
 *
 * 原来每个页面各自 onMounted 拉一遍，切一次页签就是「旧内容停 200ms → 跳」
 * 或者「白屏 → 渲一半 → 补齐」。实测（模拟 60ms 延迟）：
 *   未出账→已出账  旧数字多停 215ms（/statements → /bill → /entries 串行三跳）
 *   已出账→以前    白屏 65ms
 *   以前→未出账    白屏 66ms，再分两步渲染
 *
 * 这里管三件事：
 *   1. 按「哪一张」缓存，进页面先拿缓存渲染，同一时刻发请求校正
 *   2. 账单和明细两个请求**并发**，手机上少等一个来回
 *   3. 记账/改账之后把**已经缓存过的**几张在后台刷一遍 —— 不是清空缓存：
 *      清空的话下次进去又白屏一次，而这正是要治的毛病
 *
 * 缓存的是钱，所以规矩是「可以旧一个来回，不能旧一整屏」：每次进页面必发请求。
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { api } from 'src/api/client'
import type { Bill, Entry, MonthlyData, Statement } from 'src/api/types'

export interface BillView {
  bill: Bill
  entries: Entry[]
}

/** 路由说的是哪一张：草稿 / 最近出的那一张 / 指名道姓的某一张 */
export type BillKey = 'draft' | 'current' | `st:${number}`

/** 三个页签。**它们是同一个地址上的状态**，点页签不改 URL、不走路由 */
export type BillTab = 'draft' | 'current' | 'past'
const TAB_STORE_KEY = 'nagaya.billTab'

function savedTab(): BillTab {
  try {
    const v = sessionStorage.getItem(TAB_STORE_KEY)
    if (v === 'draft' || v === 'current' || v === 'past') return v
  } catch {
    /* 隐私模式下读不了就用默认值 */
  }
  return 'draft'
}

export const useBills = defineStore('bills', () => {
  /**
   * 当前在看哪一页。地址栏永远停在 /bill，所以刷新之后靠它回到原来那一页 ——
   * 记在 sessionStorage 而不是 localStorage：这是「这次用着用着停在哪儿」，
   * 不是长期偏好，下次重新打开该从「未出账」开始
   */
  const tab = ref<BillTab>(savedTab())
  watch(tab, (v) => {
    try {
      sessionStorage.setItem(TAB_STORE_KEY, v)
    } catch {
      /* 存不了就算了 */
    }
  })

  /**
   * 从「以前」点进来的那一张。这也是状态不是路由 —— 点一条旧账单同样不改地址。
   * 不进 sessionStorage：刷新之后回到列表就好，没必要连「翻到第几张」都记着
   */
  const detail = ref<number | null>(null)

  const statements = ref<Statement[] | null>(null)
  const views = ref<Record<string, BillView>>({})
  /** 固定费面板的数据，同样按「哪一张」缓存 —— 未出账那页一半的内容是它 */
  const monthly = ref<Record<string, MonthlyData>>({})
  /** 在飞的请求数。为 0 且没数据，才敢说「这儿是空的」 */
  const pending = ref(0)
  const inflight = new Map<string, Promise<void>>()

  /**
   * 路由 key → 缓存 key。
   * 'current' 要先知道最近那张的 id —— 列表在手就**同步**答得出来，
   * 答得出来才能秒开；答不出来就返回 null，由请求那边先去取列表。
   */
  function cacheKey(key: BillKey): string | null {
    if (key === 'draft') return 'draft'
    if (key !== 'current') return key
    const id = statements.value?.[0]?.id
    return id === undefined ? null : `st:${id}`
  }

  /** 单子列表同时只取一份：冷启动时草稿和「已出账」会一起要它 */
  let statementsTask: Promise<Statement[]> | null = null
  function loadStatements(): Promise<Statement[]> {
    if (statementsTask) return statementsTask
    statementsTask = api
      .get<Statement[]>('/api/statements')
      .then((rows) => {
        statements.value = rows
        return rows
      })
      .finally(() => {
        statementsTask = null
      })
    return statementsTask
  }

  async function fetchView(key: BillKey): Promise<void> {
    // 「已出账」每次都把列表重取一遍：别人出了新的一张，这儿得跟上
    if (key === 'current' || statements.value === null) await loadStatements()
    const ck = cacheKey(key)
    if (ck === null) return                      // 一张都还没出过
    const id = ck === 'draft' ? null : Number(ck.slice(3))
    const [bill, entries] = await Promise.all([
      api.get<Bill>(id === null ? '/api/bill' : `/api/statements/${id}/bill`),
      api.get<Entry[]>(
        id === null
          ? '/api/entries?unbilled_only=true&limit=200'
          : `/api/entries?statement_id=${id}&limit=200`,
      ),
    ])
    views.value = { ...views.value, [ck]: { bill, entries } }
  }

  /**
   * 同一张同时只发一份：onMounted 和路由 watch 会一起响。
   * 按**缓存 key** 去重，不按路由 key —— 否则 'current' 和 'st:4' 明明是
   * 同一张单子，会各发各的
   */
  function run(key: BillKey): Promise<void> {
    const slot = cacheKey(key) ?? key
    const already = inflight.get(slot)
    if (already) return already
    pending.value += 1
    const task = fetchView(key).finally(() => {
      inflight.delete(slot)
      pending.value -= 1
    })
    inflight.set(slot, task)
    return task
  }

  /** 进页面调它：有缓存立刻返回（请求照发，在后台校正），没缓存才需要等 */
  function ensure(key: BillKey): Promise<void> {
    const ck = cacheKey(key)
    const task = run(key)
    if (ck === null || views.value[ck] === undefined) return task
    // 后台校正失败（比如断网）就继续用缓存，不打断正在看的人
    task.catch(() => {})
    return Promise.resolve()
  }

  /** 改完数据强制重取，要等它 */
  const reload = (key: BillKey) => run(key)

  /** 固定费面板。ck 是缓存 key（'draft' 或 'st:4'），面板自己算得出来 */
  async function loadMonthly(ck: string): Promise<MonthlyData> {
    const d = await api.get<MonthlyData>(
      ck === 'draft' ? '/api/monthly' : `/api/monthly?statement_id=${ck.slice(3)}`,
    )
    monthly.value = { ...monthly.value, [ck]: d }
    return d
  }

  /**
   * 记了一笔 / 改了一笔之后：把**已经缓存过的**几张在后台刷一遍。
   * 不清缓存 —— 清了下次进去又白屏，而白屏正是要治的毛病。
   */
  function refreshCached(): void {
    for (const ck of Object.keys(views.value)) {
      run(ck as BillKey).catch(() => {})
    }
  }

  /** 预热另外两页 + 固定费面板，第一次切过去就不用等 */
  function warm(): void {
    for (const key of ['draft', 'current'] as const) run(key).catch(() => {})
    loadMonthly('draft').catch(() => {})
  }

  return {
    tab, detail, statements, views, monthly, pending,
    cacheKey, loadStatements, loadMonthly, ensure, reload, refreshCached, warm,
  }
})
