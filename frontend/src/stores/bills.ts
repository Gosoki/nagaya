/**
 * 账单两页（未出账 / 已出账，更早的从标题翻）的数据。**缓存先上屏，后台校正。**
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

import { ApiError, api } from 'src/api/client'
import type { Bill, Entry, MonthlyData, Statement } from 'src/api/types'

export interface BillView {
  bill: Bill
  entries: Entry[]
}

/** 路由说的是哪一张：草稿 / 最近出的那一张 / 指名道姓的某一张 */
export type BillKey = 'draft' | 'current' | `st:${number}`

/** 两个页签。**它们是同一个地址上的状态**，点页签不改 URL、不走路由。
    出过的单子不再单独占一页 —— 全在「已出账」里，点标题那个名字翻 */
export type BillTab = 'draft' | 'current'
const TAB_STORE_KEY = 'nagaya.billTab'

const DETAIL_KEY = 'nagaya.billDetail'
function savedDetail(): number | null {
  try {
    const v = Number(sessionStorage.getItem(DETAIL_KEY))
    return Number.isInteger(v) && v > 0 ? v : null
  } catch {
    return null
  }
}

function savedTab(): BillTab {
  try {
    const v = sessionStorage.getItem(TAB_STORE_KEY)
    if (v === 'draft' || v === 'current') return v
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
   * 「已出账」当前翻到哪一张；**null ＝ 最近出的那一张**。
   * 这也是状态不是路由 —— 翻旧账单同样不改地址。
   * 记在 sessionStorage 里：换新版时的整页重载（src/update.ts）之后还在这一张上；
   * 关掉 app 再打开就清空了，照样回到最近那张
   */
  const detail = ref<number | null>(savedDetail())
  watch(detail, (v) => {
    try {
      if (v === null) sessionStorage.removeItem(DETAIL_KEY)
      else sessionStorage.setItem(DETAIL_KEY, String(v))
    } catch {
      /* 存不了就算了 */
    }
  })

  const statements = ref<Statement[] | null>(null)
  const views = ref<Record<string, BillView>>({})
  /** 固定费面板的数据，同样按「哪一张」缓存 —— 未出账那页一半的内容是它 */
  const monthly = ref<Record<string, MonthlyData>>({})
  /** 在飞的请求数。为 0 且没数据，才敢说「这儿是空的」 */
  const pending = ref(0)
  /**
   * 上一次取数失败的原因。**「取不到」和「没有」是两件事** ——
   * 少了它，断网时账单页会说「这屋里还没出过账」，那是句假话。
   */
  const lastError = ref<string | null>(null)
  const inflight = new Map<string, Promise<void>>()
  /**
   * 每个槽位发出去的第几发。用来认「我是不是已经过时了」——
   * 强制重取时旧的那一发照样会回来，回来之后不许再往缓存里写。
   */
  const seq = new Map<string, number>()
  /**
   * 全局单调递增的票号，和「每份缓存最后是被哪一票写的」。
   *
   * 光有 seq 盖不住一个口子：`'current'` 和 `'st:N'` 是**两个槽**，写的却是
   * 同一份缓存。改完数据 reload('st:N') 之后，一个在改动之前就发出去的
   * `'current'` 回来照样会把旧数据盖上 —— 正是 seq 本来要防的那件事，
   * 只是跨了槽。票号是全局的，所以跨槽也认得出谁更旧。
   */
  let ticket = 0
  const written = new Map<string, number>()
  /**
   * 第几代数据。出账（invalidate）把它 +1。
   *
   * 清缓存清不掉**已经发出去的请求**：出账那一刻正好有一发 'draft' 在路上，
   * 它回来的是出账之前的草稿 —— 里面正是刚刚被归进新账单的那批账。
   * 缓存清了、`written` 也清了，于是它畅通无阻地写进 views['draft']，
   * 而「未出账」那页看到的就是一份已经出过账的草稿，还可点可改。
   * 之后谁也不会再纠正它（没有人知道它是旧的），刷新页面才好。
   * 拿代号一比就认得出来：不是这一代的，结果直接扔掉。
   */
  let generation = 0

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
    const gen = generation
    const task: Promise<Statement[]> = api
      .get<Statement[]>('/api/statements')
      .then((rows) => {
        // 出账之后回来的旧列表里没有刚出的那一张，写进去会让 'current' 认错单子
        if (gen === generation) statements.value = rows
        return rows
      })
      .finally(() => {
        // 只清自己：出账时 invalidate 已经换上了新的一发，别把它置空
        if (statementsTask === task) statementsTask = null
      })
    statementsTask = task
    return task
  }

  async function fetchView(key: BillKey, slot: string, my: number, gen: number): Promise<void> {
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
    // 我不是这个槽位上最新的那一发了 —— 别把旧数据盖回去。
    // 少了这一句，reload 发出的新请求先回、写对了，随后旧的那发才回来又盖成旧值
    if (seq.get(slot) !== my) return
    // 这份缓存已经被一张更新的票写过了（多半来自另一个槽）—— 同样不许盖
    if ((written.get(ck) ?? 0) > my) return
    // 出账把整个缓存作废了，而我是出账之前发出去的 —— 拿回来的是上一代的账
    if (gen !== generation) return
    written.set(ck, my)
    views.value = { ...views.value, [ck]: { bill, entries } }
  }

  /**
   * 同一张同时只发一份：onMounted 和路由 watch 会一起响。
   * 按**缓存 key** 去重，不按路由 key —— 否则 'current' 和 'st:4' 明明是
   * 同一张单子，会各发各的
   */
  function run(key: BillKey, force = false): Promise<void> {
    // 'current' 单独占一个槽，不跟 'st:N' 合并：它比别人多干一件事 ——
    // 重取单子列表。并到某个 'st:N' 的在飞请求上的话，别人刚出的那张新账单
    // 就一直进不到列表里，这一页会一直显示上一张
    const slot = key === 'current' ? 'current' : (cacheKey(key) ?? key)
    const already = inflight.get(slot)
    // **只有「进页面校正」才许复用在飞的那一发。** 改完数据的强制重取不能复用：
    // 一个在写之前发出的 GET，回来的必然是写之前的数据，而它被当成「重取结果」
    // 写进缓存之后就再也没有人纠正了 —— 连填五项固定费时，最后一项的钱
    // 会从账单合计里永久少掉，而那份数字正是要复制进群里的
    if (already && !force) return already
    const my = (ticket += 1)
    seq.set(slot, my)
    pending.value += 1
    const task = fetchView(key, slot, my, generation)
      .then(() => {
        lastError.value = null
      })
      .catch((e: unknown) => {
        lastError.value = e instanceof ApiError ? e.text : String(e)
        throw e
      })
      .finally(() => {
        if (inflight.get(slot) === task) inflight.delete(slot)
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

  /** 改完数据强制重取，要等它。force：绝不复用改动之前发出的那一发 */
  const reload = (key: BillKey) => run(key, true)

  /**
   * 固定费面板每存成一笔（或者「照上期」记了几笔）就加一。
   * 在这之前发出去的 /monthly，回来的是**存之前**的样子：照写的话刚存好的那一行
   * 变回空框、「照上期」又冒出来，人再填一遍就是同一项两笔
   */
  let monthlyStamp = 0
  function monthlyWritten(): void {
    monthlyStamp += 1
  }

  /**
   * 同一份固定费同时只取一份：进账单页时预热和面板自己会一起要它。
   * 按「哪一份 + 中间有没有存过 + 有没有出过账」去重 —— 存过之后的新请求
   * 不许复用存之前发出去的那一发
   */
  const monthlyTasks = new Map<string, Promise<MonthlyData>>()
  function loadMonthly(ck: string): Promise<MonthlyData> {
    const k = `${ck}|${monthlyStamp}|${generation}`
    const hit = monthlyTasks.get(k)
    if (hit) return hit
    const task = fetchMonthly(ck).finally(() => monthlyTasks.delete(k))
    monthlyTasks.set(k, task)
    return task
  }

  /** 固定费面板。ck 是缓存 key（'draft' 或 'st:4'），面板自己算得出来 */
  async function fetchMonthly(ck: string): Promise<MonthlyData> {
    const gen = generation
    const stamp = monthlyStamp
    const d = await api.get<MonthlyData>(
      ck === 'draft' ? '/api/monthly' : `/api/monthly?statement_id=${ck.slice(3)}`,
    )
    // 我出发之后面板存过：这份是旧的。缓存里那份（面板存的时候已经跟着改了）才是对的
    if (stamp !== monthlyStamp) return monthly.value[ck] ?? d
    // 和账单那边同一条规矩：出账之前发出去的这一发，回来的是已经归进新单子的
    // 那批固定费。写进去的话，「未出账」那页会把它们当本期草稿画出来，还可点可改
    if (gen === generation) monthly.value = { ...monthly.value, [ck]: d }
    return d
  }

  /**
   * 记了一笔 / 改了一笔之后：把**已经缓存过的**几张在后台刷一遍。
   * 不清缓存 —— 清了下次进去又白屏，而白屏正是要治的毛病。
   */
  function refreshCached(touched?: Entry): void {
    // 出过账的单子只有两种事动得了它：**改/删它里头的账**，和**记一笔转账**
    // （「已结清」认的是出账之后的转账）。新记一笔支出/收入落的是草稿，
    // 跟它一个数字都不沾 —— 而在 5 年的库上重算一张旧单子要 70ms 上下，
    // 翻过几张就刷几张，每记一笔都来一轮。
    // 不知道动了什么（没传参数）时照旧全刷：宁可白刷，不能让数字发旧
    const all =
      touched === undefined || touched.statement_id !== null || touched.kind === 'settlement'
    for (const ck of Object.keys(views.value)) {
      if (!all && ck !== 'draft') continue
      run(ck as BillKey, true).catch(() => {})
    }
    // 固定费面板那份缓存有同一个洞：在账目页把一笔房租删了，
    // 回到账单页那一行还挂着金额、还能点进去改一笔已经不在了的账
    for (const ck of Object.keys(monthly.value)) {
      if (!all && ck !== 'draft') continue
      loadMonthly(ck).catch(() => {})
    }
  }

  /**
   * 出账之后把缓存整个丢掉。
   *
   * 出账把草稿里那批固定费整个挪到新单子上了 —— `monthly['draft']` 里存的
   * entry_id/version 于是全指向**已经归到新账单上的**那几笔账。而固定费面板是
   * 缓存先上屏的：切回「未出账」会把刚出账的那批当本期草稿画出来，还可点可改。
   * monthly 以前不在这组清理里，漏了整整一块。
   */
  function invalidate(): void {
    generation += 1          // 在路上的那几发就此作废，回来也不许写
    // 在飞的请求也不许再被复用：出账时「已出账」那页的预热还在路上，
    // 出完账 ensure('current') 会直接复用它 —— 它回来的是出账前的列表，
    // 写入被 generation 挡掉，于是这一页停在「还没出过账单」
    inflight.clear()
    seq.clear()
    statementsTask = null
    views.value = {}
    written.clear()          // 缓存都丢了，「谁写过它」的记录也跟着作废
    monthly.value = {}
    statements.value = null
    detail.value = null
  }

  /**
   * 从后台切回来：挂着的这段时间室友可能记了账、甚至出了一张新的。
   * 缓存过的几张都后台校正一遍（不清空，屏幕不白）。'current' 顺带重取单子列表
   */
  function refreshViews(): void {
    const cks = Object.keys(views.value)
    if (!cks.length) return
    // 只刷草稿、最新那张（'current' 顺带重取单子列表）和正在看的那张。
    // 原来是缓存过的每一张都重取：最新那张被 'current' 和 'st:N' 各取一遍，
    // 这次会话翻过的旧单子每次切回前台都挨个重算（5 年的库上一张十几毫秒）——
    // 而进那一页时 ensure() 本来就会重取
    run('current', true).catch(() => {})
    if (views.value.draft) run('draft', true).catch(() => {})
    const onScreen = detail.value === null ? null : (`st:${detail.value}` as const)
    if (onScreen && views.value[onScreen] && onScreen !== cacheKey('current')) {
      run(onScreen, true).catch(() => {})
    }
    // 草稿的固定费面板也重取：面板盯着这份缓存重建，而重建会留住还没存的输入 ——
    // 不刷的话，室友出完账这一块还挂着上一期的房租
    if (monthly.value.draft) loadMonthly('draft').catch(() => {})
  }

  /** 预热另外两页 + 固定费面板，第一次切过去就不用等 */
  function warm(): void {
    for (const key of ['draft', 'current'] as const) run(key).catch(() => {})
    loadMonthly('draft').catch(() => {})
  }

  return {
    tab, detail, statements, views, monthly, pending, lastError,
    cacheKey, loadStatements, loadMonthly, monthlyWritten, ensure, reload, refreshCached, refreshViews, invalidate, warm,
  }
})
