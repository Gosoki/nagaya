/**
 * 账单两页左右滑。**翻的是状态，不是地址** —— 两页共用 /bill 一个地址。
 *
 * 首尾相接：到头了再划就绕回去。两页之间来回看是常态，
 * 划不动会让人以为卡住了。
 */
import { useBills, type BillTab } from 'src/stores/bills'

const TABS: BillTab[] = ['draft', 'current']

export function useBillSwipe() {
  const bills = useBills()
  return ({ direction }: { direction: string }) => {
    const i = TABS.indexOf(bills.tab)
    if (i < 0) return
    const step = direction === 'left' ? 1 : -1
    bills.tab = TABS[(i + step + TABS.length) % TABS.length]!
  }
}
