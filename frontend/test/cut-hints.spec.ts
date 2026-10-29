/**
 * 出账确认框里讲固定费的那几句按哪几行拼（core/cutHints，审计 #13 / #47）。
 *
 * 「X 还空着」有一半是隔月才收的水费 —— 分成「按往常这期该有」和「还没轮到」两段，
 * 但**一项都不许藏**：节奏是从历史猜的，猜错了那笔真忘了的账单就按 0 出账了。
 */
import { describe, expect, it } from 'vitest'

import { cutParams, cutRows, offCycle, shouldStopAfterCarry } from '../src/core/cutHints'

type R = {
  name: string
  amount: number | null
  archived: boolean
  carry_amount?: number | null
  entry_count: number
  cuts_since_last?: number | null
  typical_gap?: number | null
}
const row = (name: string, over: Partial<R> = {}): R => ({
  name, amount: null, archived: false, carry_amount: null, entry_count: 0,
  cuts_since_last: null, typical_gap: null, ...over,
})

describe('出账框里的固定费', () => {
  const rows = [
    row('房租', { carry_amount: 120_000 }),                         // 照上期能记
    row('电费', { cuts_since_last: 1, typical_gap: 1 }),           // 每期都有：该有
    row('水费', { cuts_since_last: 1, typical_gap: 2 }),           // 隔月、上期刚有：还没轮到
    row('燃气', { cuts_since_last: 2, typical_gap: 2 }),           // 隔月、到点了：该有
    row('网费', { cuts_since_last: 1, typical_gap: null }),        // 看不出节奏：当该有
    row('停车位', { amount: 8_000, entry_count: 2 }),               // 本期两笔
    row('NHK', { archived: true }),                                 // 删掉的项不说
  ]
  const got = cutRows(rows)
  const names = (rs: R[]) => rs.map((r) => r.name)

  it('分成两段：该有的、还没轮到的', () => {
    expect(names(got.due)).toEqual(['电费', '燃气', '网费'])
    expect(names(got.waiting)).toEqual(['水费'])
  })

  it('一项都不藏：两段合起来就是全部空着的（照上期能记的、删掉的项除外）', () => {
    const blank = rows.filter((r) => !r.archived && !r.amount && !r.carry_amount)
    expect([...names(got.due), ...names(got.waiting)].sort()).toEqual(names(blank).sort())
  })

  it('照上期能记的单列；本期不止一笔的单列', () => {
    expect(names(got.carryable)).toEqual(['房租'])
    expect(names(got.multi)).toEqual(['停车位'])
  })

  it('历史不够（从没出现过）一律当「该有」', () => {
    expect(offCycle(row('新项'))).toBe(false)
    expect(offCycle(row('新项', { cuts_since_last: null, typical_gap: 2 }))).toBe(false)
  })
})

describe('出账框里「先按上期记上」之后出不出账（审计 #13 / R27）', () => {
  const rent = { category_id: 1, name: '房租' }
  const net = { category_id: 2, name: '网费' }
  const made = (id: number) => ({ category_id: id })

  it('全部记上了才放行', () => {
    expect(shouldStopAfterCarry([rent, net], [made(1), made(2)], [])).toEqual({ stop: false, skipped: [] })
  })

  it('有一项 failed（垫付人刚搬走、上期有好几笔）：停下，不出账', () => {
    expect(shouldStopAfterCarry([rent, net], [made(2)], [made(1)])).toEqual({ stop: true, skipped: [] })
  })

  it('后端静默跳过（既没记上、也不在 failed 里）：照样停下，并单独列出来', () => {
    // 室友刚在面板上记了房租、刚关掉「和上期一样」：后端认它已经处理过，什么都不回
    expect(shouldStopAfterCarry([rent, net], [made(2)], [])).toEqual({ stop: true, skipped: [rent] })
    expect(shouldStopAfterCarry([rent], [], [])).toEqual({ stop: true, skipped: [rent] })
  })
})

describe('出账带不带 after_statement_id（审计 #5 / R27）', () => {
  it('弹框那一刻看到的最近一张：「先按上期记上」和出账两边都带', () => {
    expect(cutParams(7)).toEqual({ carry: { after_statement_id: 7 }, query: '&after_statement_id=7' })
  })

  it('一张都没出过是 0：也得带（0 不是「没给」）', () => {
    expect(cutParams(0)).toEqual({ carry: { after_statement_id: 0 }, query: '&after_statement_id=0' })
  })

  it('老后端不给这个字段：两边都不带', () => {
    expect(cutParams(undefined)).toEqual({ carry: {}, query: '' })
  })
})
