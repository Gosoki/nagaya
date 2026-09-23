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
const payloads = new Map<string, unknown>()
/** 实际发出去的每一个地址，按顺序 —— 用来数「刷了哪几张」 */
const calls: string[] = []

vi.mock('src/api/client', () => ({
  ApiError: class extends Error {},
  api: {
    get: (path: string) => {
      calls.push(path)
      const gate = gates.get(path)
      if (!gate) return Promise.resolve(payloads.get(path) ?? [])
      return gate.promise.then(() => payloads.get(path) ?? [])
    },
  },
}))

function gate(path: string) {
  let resolve!: (v: unknown) => void
  const promise = new Promise((r) => (resolve = r))
  gates.set(path, { resolve, promise })
  return () => resolve(null)
}

describe('账单缓存的竞态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    gates.clear()
    payloads.clear()
    calls.length = 0
  })

  it('更早发出的那一发回来时，不许盖掉更新的数据（跨槽也算）', async () => {
    const bills = useBills()
    payloads.set('/api/statements', [{ id: 7, label: '9/1 出账' }])
    payloads.set('/api/statements/7/bill', { total_expense: 100, statement_id: 7 })
    payloads.set('/api/entries?statement_id=7&limit=200', [])

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
    payloads.set('/api/entries?unbilled_only=true&limit=200', [])
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
    payloads.set('/api/entries?unbilled_only=true&limit=200', [])
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

  it('新记一笔支出不去重算翻过的旧账单，记一笔转账才去', async () => {
    const bills = useBills()
    payloads.set('/api/statements', [{ id: 7, label: '9/1 出账' }])
    payloads.set('/api/statements/7/bill', { total_expense: 100, statement_id: 7 })
    payloads.set('/api/entries?statement_id=7&limit=200', [])
    payloads.set('/api/bill', { total_expense: 1, is_draft: true })
    payloads.set('/api/entries?unbilled_only=true&limit=200', [])
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
})
