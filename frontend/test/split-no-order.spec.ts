/**
 * 不带 order 的分摊：两份实现必须挑同一个顺序。
 *
 * 顺序决定最大余数法平局时那 1 円归谁。而两边的默认本来是不同的：
 * Python 的 dict 保持插入序，JS 的 Object.keys 会把数字键**升序重排**。
 * 523 条夹具全都带 order，这条路一条都没测到。
 *
 * **下面这四条和 backend/tests/test_split.py 的 NO_ORDER_CASES 是同一份，期望值也一样。**
 * 改动其中一侧时，另一侧要一起改。
 */
import { describe, expect, it } from 'vitest'

import { split } from '../src/core/split'

const CASES: [Record<string, unknown>, number, string | null, Record<string, number>][] = [
  [{ mode: 'ratio', weights: { '3': 1, '1': 1, '2': 1 } }, 1001, '1',
    { '1': 334, '2': 334, '3': 333 }],
  [{ mode: 'ratio', weights: { '10': 1, '2': 1, '1': 1 } }, 1000, null,
    { '1': 334, '2': 333, '10': 333 }],
  [{ mode: 'ratio', weights: { '2': 2, '1': 1, '3': 1 }, remainder_to: 'order' }, 997, '2',
    { '1': 249, '2': 499, '3': 249 }],
  [{ mode: 'exact', exact: { '3': 500, '1': 300, '2': 200 } }, 1000, '1',
    { '1': 300, '2': 200, '3': 500 }],
]

describe('不给顺序时两份实现也要一致', () => {
  it.each(CASES)('%o / %i', (rule, amount, payer, expected) => {
    expect(split(rule as never, amount, { payer })).toEqual(expected)
  })
})
