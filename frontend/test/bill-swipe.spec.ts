/**
 * 账单三页左右滑的翻页逻辑。
 *
 * 只测「从哪页滑到哪页」这件事 —— 手势本身不测：合成的鼠标事件跟真机触摸
 * 走的是 Quasar 里两条不同的代码路径（阈值 50px vs 6px），拿它当验收标准
 * 会得出跟真机不一样的结论。
 */
import { describe, expect, it, vi } from 'vitest'

const push = vi.fn()
let name = 'bill'

vi.mock('vue-router', () => ({
  useRoute: () => ({ get name() { return name } }),
  useRouter: () => ({ push }),
}))

const { useBillSwipe } = await import('../src/composables/billSwipe')

function swipeFrom(from: string, direction: 'left' | 'right') {
  name = from
  push.mockClear()
  useBillSwipe()({ direction })
  return push.mock.calls[0]?.[0]?.name ?? null
}

describe('账单三页左右滑', () => {
  it('往左划＝往后翻一页', () => {
    expect(swipeFrom('bill', 'left')).toBe('bill-current')
    expect(swipeFrom('bill-current', 'left')).toBe('bill-past')
  })

  it('往右划＝往前翻一页', () => {
    expect(swipeFrom('bill-past', 'right')).toBe('bill-current')
    expect(swipeFrom('bill-current', 'right')).toBe('bill')
  })

  it('首尾相接，一直划得下去', () => {
    expect(swipeFrom('bill-past', 'left')).toBe('bill')
    expect(swipeFrom('bill', 'right')).toBe('bill-past')
  })

  it('从「以前」点进某一张时不在这个序列里，划了没反应', () => {
    expect(swipeFrom('entries', 'left')).toBeNull()
  })
})
