/**
 * 账单缓存不许被**更早发出的那一发**盖回旧值。
 *
 * 两个口子，都真发生过：
 *   1. 同一个槽：`reload` 去重时复用了改动之前发出的请求 —— 连填五项固定费，
 *      最后一项的钱会从账单合计里永久少掉，而那份数字正是要复制进群里的；
 *   2. **跨槽**：`'current'` 和 `'st:N'` 是两个槽却写同一份缓存，
 *      改完数据 reload('st:N') 之后，一个更早发出的 `'current'` 回来照样盖旧值。
 *
 * 这一条盯着第 2 个 —— 第 1 个被 seq 挡着，第 2 个要靠全局票号。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useBills } from '../src/stores/bills'

/** 每个地址一个「什么时候回」的闸门，测试自己决定谁先回 */
const gates = new Map<string, { resolve: (v: unknown) => void; promise: Promise<unknown> }>()
/** 回什么。给个函数的话每回一次调一次 —— 同一个地址先后两发要回不一样的东西时用 */
const payloads = new Map<string, unknown>()
/** 实际发出去的每一个地址，按顺序 —— 用来数「刷了哪几张」 */
const calls: string[] = []
/** 这几个地址一发就失败（连接被重置、服务器重启时的 502 那种「马上就回来的失败」） */
const failures = new Set<string>()

function answer(path: string): unknown {
  const p = payloads.get(path)
  return (typeof p === 'function' ? p() : p) ?? []
}

vi.mock('src/api/client', () => ({
  ApiError: class extends Error {},
  errorText: (e: unknown) => String(e),
  api: {
    get: (path: string) => {
      calls.push(path)
      if (failures.has(path)) return Promise.reject(new Error(`连不上：${path}`))
      const gate = gates.get(path)
      if (!gate) return Promise.resolve(answer(path))
      return gate.promise.then(() => answer(path))
    },
  },
}))

function gate(path: string) {
  let resolve!: (v: unknown) => void
  let reject!: (e: unknown) => void
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  gates.set(path, { resolve, promise })
  // 调它 ＝ 放行；.fail() ＝ 让卡着的那一发失败
  return Object.assign(() => resolve(null), { fail: () => reject(new Error(`连不上：${path}`)) })
}

describe('账单缓存的竞态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    gates.clear()
    payloads.clear()
    failures.clear()
    calls.length = 0
  })

  it('更早发出的那一发回来时，不许盖掉更新的数据（跨槽也算）', async () => {
    const bills = useBills()
    payloads.set('/api/statements', [{ id: 7, label: '9/1 出账' }])
    payloads.set('/api/statements/7/bill', { total_expense: 100, statement_id: 7 })
    payloads.set('/api/entries?statement_id=7&limit=1000', [])

    // ① 'current' 先出发，卡在半路。等一拍让它走过 loadStatements ——
    // 不等的话两条路会一起卡在同一个 loadStatements 上，撞不出要验的那个顺序
    const openCurrent = gate('/api/statements/7/bill')
    const current = bills.ensure('current')
    await new Promise((r) => setTimeout(r, 10))

    // ② 数据变了，强制重取 'st:7' —— 另一个槽，同一份缓存
    payloads.set('/api/statements/7/bill', { total_expense: 999, statement_id: 7 })
    gates.delete('/api/statements/7/bill')
    await bills.reload('st:7')
    expect(bills.views['st:7']?.bill.total_expense, '新数据该已经写进去了').toBe(999)

    // ③ 现在才放那一发旧的回来 —— 它拿的是 100，不许盖上去
    payloads.set('/api/statements/7/bill', { total_expense: 100, statement_id: 7 })
    openCurrent()
    await current

    expect(bills.views['st:7']?.bill.total_expense, '旧请求把新数据盖回去了').toBe(999)
  })

  it('同一个槽：强制重取不复用改动之前发出的那一发', async () => {
    const bills = useBills()
    payloads.set('/api/bill', { total_expense: 1 })
    payloads.set('/api/entries?unbilled_only=true&limit=1000', [])
    payloads.set('/api/statements', [])

    const open = gate('/api/bill')
    const first = bills.ensure('draft')
    await new Promise((r) => setTimeout(r, 10))
    payloads.set('/api/bill', { total_expense: 2 })
    gates.delete('/api/bill')
    await bills.reload('draft')
    expect(bills.views.draft?.bill.total_expense).toBe(2)

    payloads.set('/api/bill', { total_expense: 1 })
    open()
    await first
    expect(bills.views.draft?.bill.total_expense, '旧的那一发不该盖回 1').toBe(2)
  })

  it('出账之后，出账前发出的那一发不许把旧草稿写进缓存', async () => {
    const bills = useBills()
    payloads.set('/api/bill', { total_expense: 8000, is_draft: true })
    payloads.set('/api/entries?unbilled_only=true&limit=1000', [])
    payloads.set('/api/statements', [])

    const open = gate('/api/bill')
    const stale = bills.ensure('draft')
    await new Promise((r) => setTimeout(r, 10))

    // 出账了：草稿里那批账整个挪到新单子上，缓存全部作废
    bills.invalidate()

    // 出账**之前**发出的那一发这才回来 —— 它拿的是已经出过账的那批账。
    // 写进去的话，「未出账」那页会把它们当本期草稿画出来，还可点可改，
    // 而且再没有人会纠正它
    open()
    await stale
    expect(bills.views.draft, '出账前的旧草稿被写回了缓存').toBeUndefined()
  })

  it('固定费：取数途中面板又存过一笔，回来的不许是缓存里那份旧的 —— 再取一次', async () => {
    // 审计 #8：「照上期」记上水费（POST /carry 不往缓存里写行）→ 面板去取 →
    // 还在路上时另一行存好了。原来这一发回来就把缓存那份还回去，而缓存里水费还是空框：
    // 刚记上的那行画回空框、按钮又亮着，人照着空框再填一遍，同一项就是两笔
    const bills = useBills()
    const water = (amount: number | null, entry_id: number | null) => ({
      category_id: 4, name: '水费', amount, entry_id, entry_count: entry_id === null ? 0 : 1,
    })
    payloads.set('/api/monthly', { default_date: '2026-10-29', rows: [water(null, null)], total: 134_800 })
    await bills.loadMonthly('draft')

    bills.monthlyWritten()                       // ① 照上期记上了水费
    const open = gate('/api/monthly')
    const replies = [
      { default_date: '2026-10-29', rows: [water(12_600, 11)], total: 147_400 },   // 出门时网费那笔还没存
      { default_date: '2026-10-29', rows: [water(12_600, 11)], total: 147_700 },   // 再取一次：两笔都在
    ]
    payloads.set('/api/monthly', () => replies.shift())
    const loading = bills.loadMonthly('draft')
    await new Promise((r) => setTimeout(r, 10))

    // ② 它还在路上时，网费那一行存好了：面板只就地改了自己那一行的缓存，再记一笔「写过了」
    bills.monthly.draft!.total += 300
    bills.monthlyWritten()
    open()
    const got = await loading

    expect(got.rows[0], '拿回的是缓存里那个空框').toMatchObject({ entry_id: 11, amount: 12_600 })
    expect(got.total).toBe(147_700)
    expect(bills.monthly.draft?.rows[0]?.entry_id, '缓存也得换成重取的那份').toBe(11)
    expect(calls.filter((c) => c === '/api/monthly'), '途中写过就得再取一次').toHaveLength(3)
  })

  it('新记一笔支出不去重算翻过的旧账单，记一笔转账才去', async () => {
    const bills = useBills()
    payloads.set('/api/statements', [{ id: 7, label: '9/1 出账' }])
    payloads.set('/api/statements/7/bill', { total_expense: 100, statement_id: 7 })
    payloads.set('/api/entries?statement_id=7&limit=1000', [])
    payloads.set('/api/bill', { total_expense: 1, is_draft: true })
    payloads.set('/api/entries?unbilled_only=true&limit=1000', [])
    await bills.ensure('st:7')
    await bills.ensure('draft')

    const oldBill = () => calls.filter((c) => c === '/api/statements/7/bill').length
    calls.length = 0

    // 新记一笔支出落的是草稿，旧单子上一个数字都不会变 —— 而在 5 年的库上
    // 重算一张旧单子要 70ms 上下，翻过几张就刷几张
    bills.refreshCached({ id: 1, kind: 'expense', statement_id: null } as never)
    await new Promise((r) => setTimeout(r, 10))
    expect(oldBill(), '新记一笔支出不该去重算旧账单').toBe(0)
    expect(calls, '本期草稿必须刷').toContain('/api/bill')

    // 转账不一样：「已结清」认的就是出账之后的转账，旧单子跟着变
    calls.length = 0
    bills.refreshCached({ id: 2, kind: 'settlement', statement_id: null } as never)
    await new Promise((r) => setTimeout(r, 10))
    expect(oldBill(), '记一笔转账会改「已结清」，旧账单必须跟着刷').toBeGreaterThan(0)

    // 改的是一笔已经出过账的账，同理
    calls.length = 0
    bills.refreshCached({ id: 3, kind: 'expense', statement_id: 7 } as never)
    await new Promise((r) => setTimeout(r, 10))
    expect(oldBill(), '改了旧单子上的账，那张单子必须跟着刷').toBeGreaterThan(0)
  })

  it('屏幕上那张取数失败，别的槽取成功不许把报错清掉；它自己取成了才清', async () => {
    // 审计 #68：原来只有一个全局 lastError，哪个槽取成功都把它置空。屏幕上那张（st:5）
    // 快速失败之后，后台的 'draft'、'current' 一校正成功，离线细带就没了 —— 屏幕上那张其实还是旧数；
    // 没缓存时（点开群里贴的 /bill/5）还会说「还没有账目」而不是报错加重试
    const bills = useBills()
    bills.tab = 'current'
    bills.detail = 5
    payloads.set('/api/statements', [{ id: 7, label: '' }, { id: 5, label: '' }])
    payloads.set('/api/statements/7/bill', { total_expense: 7, statement_id: 7 })
    payloads.set('/api/bill', { total_expense: 1, is_draft: true })
    failures.add('/api/statements/5/bill')

    await bills.ensure('st:5').catch(() => {})
    expect(bills.lastError, '屏幕上那张没取到，得说出来').toBeTruthy()

    // 预热 / 切回前台那几发：别的槽取成功了
    await bills.reload('draft')
    await bills.reload('current')
    expect(bills.lastError, '别的槽取成功不该把屏幕上这张的报错清掉').toBeTruthy()

    // 重试也失败：还是报着
    await bills.reload('st:5').catch(() => {})
    expect(bills.lastError).toBeTruthy()

    // 它自己取成了才清
    failures.delete('/api/statements/5/bill')
    payloads.set('/api/statements/5/bill', { total_expense: 5, statement_id: 5 })
    await bills.reload('st:5')
    expect(bills.lastError).toBeNull()
  })

  it('被同一槽新请求顶替的旧请求：成没成都不算数（报错不挂、也不清）', async () => {
    const bills = useBills()
    bills.tab = 'current'
    bills.detail = 5
    const path = '/api/statements/5/bill'
    payloads.set('/api/statements', [{ id: 7, label: '' }, { id: 5, label: '' }])
    payloads.set(path, { total_expense: 5, statement_id: 5 })

    // ① 旧的那发卡住；新的一发取成了；旧的这才失败 —— 屏幕上那张是好的，不许挂红
    const old = gate(path)
    const first = bills.ensure('st:5')
    await new Promise((r) => setTimeout(r, 10))
    gates.delete(path)
    await bills.reload('st:5')
    expect(bills.lastError).toBeNull()
    old.fail()
    await first.catch(() => {})
    expect(bills.lastError, '被顶替的旧请求失败了，不该把报错挂上').toBeNull()

    // ② 反过来：新的一发失败了，旧的那发后回来、成了 —— 它的数据不算数，报错也不许被它清掉
    const old2 = gate(path)
    const second = bills.reload('st:5')
    await new Promise((r) => setTimeout(r, 10))
    gates.delete(path)
    failures.add(path)
    await bills.reload('st:5').catch(() => {})
    expect(bills.lastError, '新的一发没取到，得说出来').toBeTruthy()
    failures.delete(path)
    old2()
    await second
    expect(bills.lastError, '被顶替的旧请求成了，不该把新一发的报错清掉').toBeTruthy()
  })

  it('翻到别的页签时，看的是那一页自己的报错', async () => {
    const bills = useBills()
    payloads.set('/api/statements', [{ id: 7, label: '' }])
    payloads.set('/api/statements/7/bill', { total_expense: 7, statement_id: 7 })
    failures.add('/api/bill')
    bills.tab = 'draft'
    await bills.ensure('draft').catch(() => {})
    expect(bills.lastError, '草稿没取到').toBeTruthy()
    // 「已出账」那张取成了：草稿那一格还挂着，但屏幕上这一页是好的
    await bills.reload('current')
    expect(bills.lastError, '草稿页还没取到').toBeTruthy()
    bills.tab = 'current'
    expect(bills.lastError, '已出账这一页取成了，不该挂草稿的报错').toBeNull()
  })
})
