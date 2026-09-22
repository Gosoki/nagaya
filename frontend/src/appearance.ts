/**
 * 把「这屋自己的 App 名字和图标」贴到浏览器那几个地方去。
 *
 * 打包产物里那份 manifest、favicon、页签标题都是**写死**的（「長屋 nagaya」＋
 * 那个「長」字）。名字和图标做成可改之后，改完得让这几处跟着走 ——
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

export function applyAppearance(name: string, iconVersion: number): void {
  const title = name.trim()
  if (title) document.title = title

  const manifest = link('manifest')
  if (manifest) manifest.href = '/api/appearance/manifest.webmanifest'

  if (!iconVersion) return          // 没设过就用打包时那套，别动
  const favicon = link('icon')
  if (favicon) favicon.href = iconSrc(32, iconVersion)
  const apple = link('apple-touch-icon')
  if (apple) apple.href = iconSrc(180, iconVersion)
}
