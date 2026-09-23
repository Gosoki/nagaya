/**
 * 账单页左右滑的翻页逻辑（未出账 / 已出账）。
 *
 * 只测「从哪页滑到哪页」这件事 —— 手势本身不测：合成的鼠标事件跟真机触摸
 * 走的是 Quasar 里两条不同的代码路径（阈值 50px vs 6px），拿它当验收标准
 * 会得出跟真机不一样的结论。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useBillSwipe } from '../src/composables/billSwipe'
import { useBills } from '../src/stores/bills'

type BillTab = 'draft' | 'current'

beforeEach(() => setActivePinia(createPinia()))

function swipeFrom(from: BillTab, direction: 'left' | 'right', detail: number | null = null) {
  const bills = useBills()
  bills.tab = from
  bills.detail = detail
  useBillSwipe()({ direction })
  return bills.tab
}

describe('账单两页左右滑', () => {
  it('往左划＝往后翻一页', () => {
    expect(swipeFrom('draft', 'left')).toBe('current')
  })

  it('往右划＝往前翻一页', () => {
    expect(swipeFrom('current', 'right')).toBe('draft')
  })

  it('首尾相接，一直划得下去', () => {
    expect(swipeFrom('current', 'left')).toBe('draft')
    expect(swipeFrom('draft', 'right')).toBe('current')
  })

  it('正翻着某一张旧账单，照样能划回未出账 —— 旧账单不是一页，是「已出账」里的一张', () => {
    expect(swipeFrom('current', 'right', 3)).toBe('draft')
  })
})
