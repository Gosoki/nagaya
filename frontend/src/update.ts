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
  // 首装那一次接管不算：页面本来就是新的。但**只跳过那一次** —— 原来按「加载时有没有
  // controller」一刀切，首装那场会话之后的更新全被忽略，挂在后台几天都换不到新版
  let seen = Boolean(sw.controller)
  // 切回前台就问一次有没有新版。sw.js 是 no-cache，没更新时只花一个 304
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void sw.getRegistration().then((r) => r?.update()).catch(() => {})
  })
  sw.addEventListener('controllerchange', () => {
    if (!seen) {
      seen = true
      return
    }
    if (ready) return
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

/**
 * 切页之后调它，传**这次切到的地址**。有新版等着就换 —— 按这个地址整页打开，
 * 不是 reload 当前地址：/bill/7 进来之后页面会把地址收回 /bill，reload 的话
 * 刚点开的那张旧账单就丢了。
 *
 * 写请求没落地就**不换**，留到下一次切页再试 —— 原来最多等 5 秒就强制重载，
 * 信号不好时会把一笔还在路上的「记入账」掐断，连草稿都不留
 */
export function applyUpdateIfReady(path: string): void {
  if (!ready) return
  ready = false
  const start = Date.now()
  const tick = () => {
    if (pendingWrites() > 0) {
      if (Date.now() - start < 5000) setTimeout(tick, 100)
      else ready = true                       // 下次切页再说
      return
    }
    location.replace(path)
  }
  // 让刚切走的那一页先卸载完（它的 onBeforeUnmount 可能正要补存）
  setTimeout(tick, 50)
}
