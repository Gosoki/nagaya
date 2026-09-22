/**
 * 起步规则 → 面板上的比例 + 调整额。预览和「没碰过就存」共用这一个函数，
 * 两边才是同一份（第二轮审计 fe-logic-1，critical）。
 */
import { expect, it } from 'vitest'

import { seedToRatio } from '../src/core/seed'

it('上期调过的比例和调整额原样带过来', () => {
  const seed = { mode: 'ratio', weights: { '1': 1, '2': 1, '3': 1 }, adjustments: { '1': 5000, '3': -5000 } }
  expect(seedToRatio(seed, ['1', '2', '3'])).toEqual({
    weights: { '1': 1, '2': 1, '3': 1 },
    adjustments: { '1': 5000, '3': -5000 },
  })
})

it('老的 exact 规则换算成「全 1 + 调整额」，金额变了也分得开', () => {
  const seed = { mode: 'exact', exact: { '1': 45000, '2': 40000, '3': 35000 } }
  expect(seedToRatio(seed, ['1', '2', '3'])).toEqual({
    weights: { '1': 1, '2': 1, '3': 1 },
    adjustments: { '1': 5000, '3': -5000 },
  })
})

it('规则里没点名的人按 0；没有规则就全员同权', () => {
  expect(seedToRatio({ weights: { '1': 2 } }, ['1', '2']).weights).toEqual({ '1': 2, '2': 0 })
  expect(seedToRatio(null, ['1', '2']).weights).toEqual({ '1': 1, '2': 1 })
})
