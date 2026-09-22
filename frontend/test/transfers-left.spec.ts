/**
 * 「此刻还该转多少」。审计 flow-1（critical）：实时方案里找不到这一对时，
 * 原来退回成「方案剩余额」—— 已经换了条路结清的那一对，按钮照样亮、大字照样叫人转钱。
 */
import { expect, it } from 'vitest'

import { leftOf } from '../src/core/transfers'

const plan = [
  { from_id: 2, to_id: 1, amount: 10_000 },
  { from_id: 3, to_id: 1, amount: 10_000 },
]

it('实时方案里没有这一对 ＝ 此刻不欠', () => {
  const bill = { settled_paid: [0, 0], live_transfers: [] }
  expect(leftOf(bill, plan[0]!, 0)).toBe(0)
  expect(leftOf(bill, plan[1]!, 1)).toBe(0)
})

it('两头取小：部分还了之后是剩下的，实时欠得更少时按实时', () => {
  const bill = {
    settled_paid: [4_000, 0],
    live_transfers: [
      { from_id: 2, to_id: 1, amount: 9_000 },
      { from_id: 3, to_id: 1, amount: 3_000 },
    ],
  }
  expect(leftOf(bill, plan[0]!, 0)).toBe(6_000)
  expect(leftOf(bill, plan[1]!, 1)).toBe(3_000)
})

it('后端没给实时方案（老缓存）才退回方案剩余额', () => {
  const bill = { settled_paid: [4_000, 0] } as Parameters<typeof leftOf>[0]
  expect(leftOf(bill, plan[0]!, 0)).toBe(6_000)
})
