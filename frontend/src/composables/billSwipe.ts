import { useRoute, useRouter } from 'vue-router'

/**
 * 账单三页之间左右滑切换。
 *
 * 三页是三条独立的路由（各自的组件、各自的数据），所以不走 q-tab-panels ——
 * 那得把三个页面塞进一个组件里。滑动只是换个路由，页签自己会跟着亮。
 *
 * 从「以前」点进某一张（/bill/3）时不在这个序列里，滑动不该有反应。
 */
const TABS = ['bill', 'bill-current', 'bill-past'] as const

/**
 * 上一下手势是不是「拖」而不是「点」。
 *
 * 横向拖拽结束时浏览器照样会在起止两点的共同祖先上派发 click —— 在「以前」
 * 那页整行都是可点的，于是划一下就误触进了某张账单。
 *
 * 判据不看 Quasar 的 swipe 有没有触发（它在某些元素上根本不启动），
 * 直接量指针自己走了多远：横向超过 24px 就不是点击。
 */
let downX = 0
let downY = 0
let draggedAt = 0
let dragged = false

if (typeof window !== 'undefined') {
  window.addEventListener('pointerdown', (e) => { downX = e.clientX; downY = e.clientY }, true)
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

/** 刚才那一下是拖出来的，不该当点击处理 */
export const justSwiped = () => dragged && Date.now() - draggedAt < 400

export function useBillSwipe() {
  const route = useRoute()
  const router = useRouter()

  return function onSwipe({ direction }: { direction: string }) {
    const i = TABS.indexOf(route.name as (typeof TABS)[number])
    if (i < 0) return
    // 手指往左划 ＝ 往后翻一页，跟系统里的分页手势一致。
    // 首尾相接：在「以前」再往左就回到「未出账」，不用倒着划回去
    const step = direction === 'left' ? 1 : -1
    void router.push({ name: TABS[(i + step + TABS.length) % TABS.length]! })
  }
}
