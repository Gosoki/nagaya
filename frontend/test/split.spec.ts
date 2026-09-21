/**
 * 前端分摊引擎回归 —— SPEC §7.3 的另一半。
 *
 * 两份 fixture：
 *   split_cases.json         手写 23 条，和后端 pytest 跑的是同一个文件
 *   split_cases_random.json  Python 生成的 500 条，锁住 TS 不跟后端漂
 *
 * 任何一条红了，就说明前后端算出来的钱不一样 —— 这正是「预览 3,167、
 * 存进去 3,166」那类鬼故事的源头，必须当场修。
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { SplitError, split } from '../src/core/split'

const here = dirname(fileURLToPath(import.meta.url))
const load = (name: string) =>
  JSON.parse(readFileSync(resolve(here, '../../tests/fixtures', name), 'utf-8'))

interface Case {
  name?: string
  mode: 'ratio' | 'exact'
  amount: number
  order: string[]
  weights?: Record<string, number>
  adjustments?: Record<string, number>
  exact?: Record<string, number>
  remainder_to?: 'payer' | 'order' | 'rotate'
  payer?: string
  rotate_seed?: number
  expected?: Record<string, number>
  expect_error?: string
  expect_diff?: number
}

function run(c: Case) {
  const rule =
    c.mode === 'exact'
      ? { mode: 'exact' as const, exact: c.exact ?? {} }
      : {
          mode: 'ratio' as const,
          weights: c.weights ?? {},
          adjustments: c.adjustments ?? {},
          remainder_to: c.remainder_to ?? ('payer' as const),
        }
  return split(rule, c.amount, {
    order: c.order,
    payer: c.payer ?? null,
    rotateSeed: c.rotate_seed ?? 0,
  })
}

describe('共享 fixture（和后端 pytest 同一份文件）', () => {
  const cases: Case[] = load('split_cases.json').cases
  it('用例文件不是空的', () => expect(cases.length).toBeGreaterThan(20))

  for (const c of cases) {
    it(c.name ?? 'case', () => {
      if (c.expect_error) {
        let thrown: unknown
        try {
          run(c)
        } catch (e) {
          thrown = e
        }
        expect(thrown).toBeInstanceOf(SplitError)
        expect((thrown as SplitError).code).toBe(c.expect_error)
        if (c.expect_diff !== undefined) {
          expect((thrown as SplitError).detail.diff).toBe(c.expect_diff)
        }
        return
      }
      const shares = run(c)
      expect(shares).toEqual(c.expected)
      expect(Object.values(shares).reduce((s, v) => s + v, 0)).toBe(c.amount)
      expect(Object.values(shares).every(Number.isInteger)).toBe(true)
    })
  }
})

describe('随机用例（期望值由 Python 生成，锁住两边不漂）', () => {
  const data = load('split_cases_random.json')
  const cases: Case[] = data.cases

  it(`${cases.length} 条全部和后端逐円一致`, () => {
    const mismatches: string[] = []
    for (const [i, c] of cases.entries()) {
      const shares = run(c)
      if (JSON.stringify(shares) !== JSON.stringify(c.expected)) {
        mismatches.push(`#${i} amount=${c.amount} 前端=${JSON.stringify(shares)} 后端=${JSON.stringify(c.expected)}`)
      }
    }
    expect(mismatches, `前后端分摊结果不一致：\n${mismatches.slice(0, 5).join('\n')}`).toEqual([])
  })

  it('合计恒等于总额', () => {
    for (const c of cases) {
      expect(Object.values(run(c)).reduce((s, v) => s + v, 0)).toBe(c.amount)
    }
  })
})

describe('前端自己的属性测试', () => {
  it('随机 2000 组：结果全是整数且合计守恒', () => {
    let seed = 20260921
    const rnd = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff
      return seed / 0x7fffffff
    }
    const int = (lo: number, hi: number) => lo + Math.floor(rnd() * (hi - lo + 1))

    for (let t = 0; t < 2000; t++) {
      const n = int(1, 5)
      const order = Array.from({ length: n }, (_, i) => String(i + 1))
      const weights: Record<string, number> = {}
      for (const m of order) weights[m] = int(0, 5)
      if (order.every((m) => weights[m] === 0)) weights[order[0]] = 1
      const adjustments: Record<string, number> = {}
      for (const m of order) if (rnd() < 0.4) adjustments[m] = int(-10_000, 10_000)
      const amount = int(-1_000_000, 1_000_000)

      const shares = split(
        { mode: 'ratio', weights, adjustments, remainder_to: 'payer' },
        amount,
        { order, payer: order[int(0, n - 1)] },
      )
      expect(Object.values(shares).reduce((s, v) => s + v, 0)).toBe(amount)
      expect(Object.values(shares).every(Number.isInteger)).toBe(true)
    }
  })
})
