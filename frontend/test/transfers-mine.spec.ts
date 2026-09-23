/**
 * 账单头卡「我这期」—— 屏幕上最显眼、也是人照着去转钱的那一行。
 *
 * 历次审计里出事最多的地方：已经还清的人被继续命令转钱（第三轮）、
 * 要转给两个人时第二个人被截掉（第四轮）。每一档都钉一条。
 */
import { describe, expect, it } from 'vitest'

import { effClosing, mineOf, supersededIn } from '../src/core/transfers'

// 1 垫了钱，2 和 3 各欠 1 一万
const plan = [
  { from_id: 2, to_id: 1, amount: 10_000 },
  { from_id: 3, to_id: 1, amount: 10_000 },
]
const bill = (over: Record<string, unknown> = {}) =>
  ({
    is_draft: false,
    transfers: plan,
    settled_transfers: [false, false],
    settled_paid: [0, 0],
    live_transfers: plan,
    live_closing: {},
    ...over,
  }) as unknown as Parameters<typeof mineOf>[0] & Parameters<typeof supersededIn>[0]

describe('我这期', () => {
  it('不在这张单子上（后来才搬进来的人翻旧账单）', () => {
    expect(mineOf(bill(), null)).toEqual({ kind: 'notIn' })
  })

  it('只欠一个人：照此刻还剩的说', () => {
    expect(mineOf(bill(), { member_id: 2, closing: -10_000 })).toEqual({ kind: 'pay', to: 1, amount: 10_000 })
  })

  it('还了一半：说剩下的，不说原额', () => {
    const b = bill({ settled_paid: [4_000, 0], live_transfers: [{ from_id: 2, to_id: 1, amount: 6_000 }, plan[1]] })
    expect(mineOf(b, { member_id: 2, closing: -10_000 })).toEqual({ kind: 'pay', to: 1, amount: 6_000 })
  })

  it('已经还清：不许再叫人转一次', () => {
    const b = bill({ settled_paid: [10_000, 0], live_transfers: [plan[1]] })
    expect(mineOf(b, { member_id: 2, closing: -10_000 })).toEqual({ kind: 'settled' })
  })

  it('要收钱：两笔加起来', () => {
    expect(mineOf(bill(), { member_id: 1, closing: 20_000 })).toEqual({ kind: 'receive', amount: 20_000 })
  })

  it('欠两个人：两个都得列出来', () => {
    const two = [
      { from_id: 3, to_id: 1, amount: 5_000 },
      { from_id: 3, to_id: 2, amount: 4_000 },
    ]
    const b = bill({ transfers: two, settled_transfers: [false, false], live_transfers: two })
    expect(mineOf(b, { member_id: 3, closing: -9_000 })).toEqual({
      kind: 'payMany',
      items: [{ to: 1, amount: 5_000 }, { to: 2, amount: 4_000 }],
    })
  })

  it('只欠一个人、同时有人欠我：照单笔那一档', () => {
    const mixed = [
      { from_id: 2, to_id: 1, amount: 5_000 },
      { from_id: 3, to_id: 2, amount: 2_000 },
    ]
    const b = bill({ transfers: mixed, live_transfers: mixed })
    expect(mineOf(b, { member_id: 2, closing: -3_000 })).toEqual({ kind: 'pay', to: 1, amount: 5_000 })
  })

  it('不在方案里、此刻还欠：说此刻的数，但不超过这张单子自己的数', () => {
    const b = bill({ live_closing: { '4': -800 } })
    expect(mineOf(b, { member_id: 4, closing: -500 })).toEqual({ kind: 'owe', amount: 500 })
    const less = bill({ live_closing: { '4': -300 } })
    expect(mineOf(less, { member_id: 4, closing: -500 })).toEqual({ kind: 'owe', amount: 300 })
  })

  it('不在方案里、此刻方向反了：已经两清，不许印「你应付」', () => {
    const b = bill({ live_closing: { '4': 200 } })
    expect(effClosing(b as never, { member_id: 4, closing: -500 })).toBe(0)
    expect(mineOf(b, { member_id: 4, closing: -500 })).toEqual({ kind: 'settled' })
  })
})

describe('方案被后来的账单接手', () => {
  it('有一行永远点不亮了（钱绕别的路结清）', () => {
    expect(supersededIn(bill({ live_transfers: [plan[1]] }))).toBe(true)
  })

  it('还在按方案走的不算；草稿不算', () => {
    expect(supersededIn(bill())).toBe(false)
    expect(supersededIn(bill({ is_draft: true, live_transfers: [] }))).toBe(false)
  })
})
