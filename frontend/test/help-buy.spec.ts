/**
 * 「帮买」的认法：一笔支出，付款人自己一分不担、全算在一个别人头上。
 * 和后端 services/bill.help_buy_for 是同一条规则（tests/test_bill.py 也钉着）。
 */
import { expect, it } from 'vitest'

import { helpBuyFor } from '../src/core/helpBuy'

const e = (kind: 'expense' | 'income' | 'settlement', payer: number, shares: Record<string, number>) => ({
  kind,
  payer_id: payer,
  shares,
})

it('Go 付钱、全算 Kan 的 ＝ 替 Kan 买', () => {
  expect(helpBuyFor(e('expense', 1, { '2': 3200 }))).toBe(2)
  // 别人是 0 的行也算「只有一个人担」
  expect(helpBuyFor(e('expense', 1, { '1': 0, '2': 3200, '3': 0 }))).toBe(2)
})

it('付款人自己也担、或者两个人分 —— 普通支出', () => {
  expect(helpBuyFor(e('expense', 1, { '1': 500, '2': 500 }))).toBeNull()
  expect(helpBuyFor(e('expense', 1, { '2': 500, '3': 500 }))).toBeNull()
  // 只有付款人自己担：自己买自己用的，也不是帮买
  expect(helpBuyFor(e('expense', 1, { '1': 1000 }))).toBeNull()
})

it('转账、收入都不是', () => {
  expect(helpBuyFor(e('settlement', 1, { '2': 3200 }))).toBeNull()
  expect(helpBuyFor(e('income', 1, { '2': -3200 }))).toBeNull()
})
