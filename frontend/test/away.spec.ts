/**
 * 离家模式的起步规则（src/core/away.ts）。和后端 core/rules.skip_members 是同一条规则：
 * 记一笔那屏的预览按它画，没碰过分摊就存时后端按它那份重算，两边必须一样。
 */
import { expect, it } from 'vitest'

import { awaySeed } from '../src/core/away'

const keys = ['1', '2', '3']

it('没有规则（全员同权）：离家的人权重 0，别人照旧', () => {
  expect(awaySeed(null, keys, ['3'])).toEqual({ mode: 'ratio', weights: { '1': 1, '2': 1, '3': 0 } })
})

it('没人离家：原样返回', () => {
  const seed = { mode: 'ratio', weights: { '1': 2, '2': 1, '3': 1 } }
  expect(awaySeed(seed, keys, [])).toBe(seed)
})

it('全员都离家：不替人定谁担，原样返回', () => {
  expect(awaySeed(null, keys, ['1', '2', '3'])).toBeNull()
  // 剩下的人本来权重就是 0：剔完也没人担，同样原样返回
  const seed = { mode: 'ratio', weights: { '1': 0, '2': 0, '3': 1 } }
  expect(awaySeed(seed, keys, ['3'])).toBe(seed)
})

it('离家的人的调整额一起去掉，别人的留着；余数规则照带', () => {
  const seed = { mode: 'ratio', weights: { '1': 1, '2': 1, '3': 1 }, adjustments: { '1': 500, '3': -500 }, remainder_to: 'order' }
  expect(awaySeed(seed, keys, ['3'])).toEqual({
    mode: 'ratio', weights: { '1': 1, '2': 1, '3': 0 }, adjustments: { '1': 500 }, remainder_to: 'order',
  })
})

it('老数据里的定额规则不动（后端也不动）', () => {
  const seed = { mode: 'exact', exact: { '1': 100, '2': 100, '3': 100 } }
  expect(awaySeed(seed, keys, ['3'])).toBe(seed)
})
