/**
 * 「添加到主屏幕」的指引按什么手机、什么浏览器给。
 *
 * **没法替人点。** iOS 根本没有「装到主屏」的接口；安卓 Chrome 的安装弹窗要 HTTPS
 * 加 service worker 才会出现，局域网 http 下也没有。能做的只有把那几步说清楚 ——
 * 而每种浏览器那几步长得不一样，所以得先认出来是哪一种。
 */

/** 现在是不是从主屏打开的（全屏、没有地址栏） */
export function isStandalone(): boolean {
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  )
}

export type InstallPlatform = 'ios-safari' | 'ios-other' | 'in-app' | 'android' | 'other'

/**
 * 按 UA 认。`touchPoints` 单独传进来是为了能测：iPad 默认用「桌面版网站」，
 * UA 写的是 Macintosh，只能靠「Mac 却有触屏」认出来。
 */
export function installPlatform(ua: string, touchPoints = 0): InstallPlatform {
  // App 里自带的浏览器（群里点账单链接，打开的就是 LINE 的）：加不了主屏，得先换到浏览器
  if (/\bLine\/|FBAN|FBAV|Instagram|MicroMessenger/i.test(ua)) return 'in-app'
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && touchPoints > 1)
  if (ios) return /CriOS|FxiOS|EdgiOS|OPiOS/.test(ua) ? 'ios-other' : 'ios-safari'
  if (/Android/.test(ua)) return 'android'
  return 'other'
}
