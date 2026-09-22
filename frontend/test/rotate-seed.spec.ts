/**
 * 「余数归谁 ＝ 逐笔轮转」时，那 1 円归谁**取决于 entry.id**。
 *
 * 这条事实撑着 SplitEditor 里的 rotateUnknown：新记的一笔还没有 id，
 * 这边只能拿 0 去算 —— 三个人分摊时三次里有两次会指错人。
 * 哪天轮转依据改了、或者这个判据失效了，这条会先红。
 */
import { describe, expect, it } from 'vitest'

import { split } from '../src/core/split'

const RULE = {
  mode: 'ratio' as const,
  weights: { '1': 1, '2': 1, '3': 1 },
  adjustments: {},
  remainder_to: 'rotate' as const,
}
const OPTS = { order: ['1', '2', '3'], payer: '1' }

describe('逐笔轮转的余数', () => {
  it('seed 一变，多担 1 円的人就换一个', () => {
    const who = (seed: number) => {
      const out = split(RULE, 100, { ...OPTS, rotateSeed: seed })
      return Object.entries(out).find(([, v]) => v === 34)?.[0]
    }
    expect([who(0), who(1), who(2)]).toEqual(['1', '3', '2'])
    expect(who(3), '周期是人数').toBe(who(0))
  })

  it('除得尽的时候 seed 不影响任何人', () => {
    const a = split(RULE, 99, { ...OPTS, rotateSeed: 0 })
    const b = split(RULE, 99, { ...OPTS, rotateSeed: 7 })
    expect(a).toEqual(b)
  })

  it('换成「归付款人」就跟 seed 无关了 —— 那才是默认', () => {
    const rule = { ...RULE, remainder_to: 'payer' as const }
    expect(split(rule, 100, { ...OPTS, rotateSeed: 0 })).toEqual(
      split(rule, 100, { ...OPTS, rotateSeed: 5 }),
    )
  })
})
