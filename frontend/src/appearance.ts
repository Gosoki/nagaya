/**
 * 把「这屋自己的 App 名字和图标」贴到浏览器那几个地方去。
 *
 * 打包产物里那份 manifest、favicon、页签标题都是**写死**的（「長屋 nagaya」＋
 * 那个红屋顶）。名字和图标做成可改之后，改完得让这几处跟着走 ——
 * 而它们不是 Vue 管的 DOM，得手动换。
 *
 * manifest 指到 `/api/appearance/manifest.webmanifest`：它是后端按当前设置
 * 现拼的，而且走 /api 这条路**永远不进 service worker 的预缓存** ——
 * 打包时那份静态清单会被 SW 缓存住，改了名字也刷不出来。
 */

/** 某个尺寸的图标地址。带版本号是为了绕开手机和浏览器对图标的死缓存 */
export function iconSrc(size: number, version: number): string {
  return `/api/appearance/icon/${size}.png?v=${version}`
}

function link(rel: string): HTMLLinkElement | null {
  return document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
}

function meta(name: string): HTMLMetaElement | null {
  return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
}

/**
 * 让浏览器**重新去读**清单。
 *
 * 清单是页面加载时读一次的东西。改完名字只把 href 设成同一个地址，浏览器
 * 认为什么都没变，不会去重拉 —— 于是「改完得刷新一次才生效」。
 * 把整个 link 元素换掉、地址再带上版本号，才算一次新的声明。
 *
 * 只在真的变了才换：meta 每次刷新都会走到这儿，每次都换等于每次都多拉一趟。
 */
let manifestToken = ''
function applyManifest(token: string): void {
  if (token === manifestToken) return
  manifestToken = token
  link('manifest')?.remove()
  const el = document.createElement('link')
  el.rel = 'manifest'
  el.href = `/api/appearance/manifest.webmanifest?v=${encodeURIComponent(token)}`
  document.head.appendChild(el)
}

export function applyAppearance(name: string, iconVersion: number): void {
  const title = name.trim()
  if (title) document.title = title

  // **iOS 加到主屏时叫什么，只看这一行。** 它不读清单里的 name/short_name，
  // 而 index.html 里这行是打包时写死的「長屋」—— 于是设置里改完名字，
  // 加到主屏的图标下面仍然写着長屋。名字是在「添加到主屏幕」那一刻从
  // 当前 DOM 里读的，所以改这个标签就够，不用重新打包
  const appleTitle = meta('apple-mobile-web-app-title')
  if (appleTitle && title) appleTitle.content = title

  applyManifest(`${iconVersion}-${title}`)

  if (!iconVersion) return          // 没设过就用打包时那套，别动
  const favicon = link('icon')
  if (favicon) favicon.href = iconSrc(32, iconVersion)
  const apple = link('apple-touch-icon')
  if (apple) apple.href = iconSrc(180, iconVersion)
}
