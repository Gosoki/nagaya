/**
 * 新版上岗之后什么时候换页面。
 *
 * SW 写了 skipWaiting + clientsClaim，新版一装好就接管 —— 但**已经打开的这一页
 * 仍然跑着旧 JS**。装到主屏之后尤其要命：从多任务里恢复不算一次导航，
 * 人可能连着好几天看的都是旧界面。
 *
 * 原来是一接管就立刻 location.reload()：人正填到一半的金额、没存上的固定费、
 * 写了一半的备忘，一下全没了（冷启动那次页面本来就是新的，刷一下纯属白闪）。
 * 现在分两步：
 *   1. 先确认这一页是不是真的旧 —— 拿服务器上现在的 index.html 比一比入口脚本，
 *      一样就什么都不做；
 *   2. 真旧就记下来，**等下一次站内切页**再整页重载：切页本来就会丢掉当前页的状态，
 *      不额外丢东西。重载前等还在路上的写请求落地（固定费离开这一屏时会补存）。
 */
import { pendingWrites } from 'src/api/client'

let ready = false

export function watchForUpdate(): void {
  const sw = navigator.serviceWorker
  if (!sw) return
  const hadController = Boolean(sw.controller)
  sw.addEventListener('controllerchange', () => {
    if (!hadController || ready) return          // 首装：页面本来就是新的
    void (async () => {
      try {
        const html = await (await fetch('/', { cache: 'no-store' })).text()
        const mine = document.querySelector('script[type="module"][src]')?.getAttribute('src')
        if (mine && html.includes(mine)) return  // 入口脚本没变 ＝ 这一页就是新版
      } catch {
        /* 取不到就当是旧的，下一次切页时换 */
      }
      ready = true
    })()
  })
}

/** 切页之后调它。有新版等着就换 —— 先等写请求落地，最多等 5 秒 */
export function applyUpdateIfReady(): void {
  if (!ready) return
  ready = false
  const start = Date.now()
  const tick = () => {
    if (pendingWrites() > 0 && Date.now() - start < 5000) {
      setTimeout(tick, 100)
      return
    }
    location.reload()
  }
  // 让刚切走的那一页先卸载完（它的 onBeforeUnmount 可能正要补存）
  setTimeout(tick, 50)
}
