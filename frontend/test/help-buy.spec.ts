/**
 * 「帮买」的认法：一笔支出，付款人自己一分不担、全算在一个别人头上。
 * 和后端 services/bill.help_buy_for 是同一条规则，**跑同一份 fixture**（tests/fixtures/help_buy_cases.json）。
 *
 * 原来两边各写各的单测、互为镜像，只靠注释同步 —— 和分摊用例共用 fixture 之前是同一种状况：
 * 以后加一条规则（比如再排除某种分类）只改了一边，另一边的单测照样绿。
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { helpBuyFor } from '../src/core/helpBuy'

const here = dirname(fileURLToPath(import.meta.url))
const load = (name: string) =>
  JSON.parse(readFileSync(resolve(here, '../../tests/fixtures', name), 'utf-8'))

interface Case {
  name: string
  kind: 'expense' | 'income' | 'settlement'
  payer_id: number
  shares: Record<string, number>
  fixed_cost?: boolean
  expected: number | null
}

describe('共享 fixture（和后端 pytest 同一份文件）', () => {
  const cases: Case[] = load('help_buy_cases.json').cases
  it('用例文件不是空的', () => expect(cases.length).toBeGreaterThan(5))

  for (const c of cases) {
    it(c.name, () => {
      expect(helpBuyFor({ kind: c.kind, payer_id: c.payer_id, shares: c.shares }, c.fixed_cost ?? false)).toBe(c.expected)
    })
  }
})
