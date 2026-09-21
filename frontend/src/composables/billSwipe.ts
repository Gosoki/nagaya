/**
 * 账单三页左右滑。**翻的是状态，不是地址** —— 三页共用 /bill 一个地址。
 *
 * 首尾相接：从「以前」再往左就回到「未出账」。三页之间来回看是常态，
 * 到头了划不动会让人以为卡住了。
 */
import { useBills, type BillTab } from 'src/stores/bills'

const TABS: BillTab[] = ['draft', 'current', 'past']

export function useBillSwipe() {
  const bills = useBills()
  return ({ direction }: { direction: string }) => {
    if (bills.detail !== null) return           // 正在看某一张旧账单，划了不翻页
    const i = TABS.indexOf(bills.tab)
    if (i < 0) return
    const step = direction === 'left' ? 1 : -1
    bills.tab = TABS[(i + step + TABS.length) % TABS.length]!
  }
}

/**
 * 刚才那一下是划不是点。
 *
 * 横着划过「以前」那个列表时，手指抬起来浏览器照样派发一个 click，于是划一下
 * 就点开了某张账单。Quasar 的滑动指令拦不住它 —— 它只认自己那套手势。
 * 这里独立记一下指针走了多远，列表点击前问一句。
 */
let downX = 0
let downY = 0
let draggedAt = 0
let dragged = false

if (typeof window !== 'undefined') {
  window.addEventListener(
    'pointerdown',
    (e) => {
      downX = e.clientX
      downY = e.clientY
    },
    true,
  )
  window.addEventListener(
    'pointerup',
    (e) => {
      const dx = Math.abs(e.clientX - downX)
      dragged = dx > 24 && dx > Math.abs(e.clientY - downY)
      draggedAt = Date.now()
    },
    true,
  )
}

export const justSwiped = () => dragged && Date.now() - draggedAt < 400
