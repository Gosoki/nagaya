/**
 * 「添加到主屏幕」的指引按浏览器给。认错了，给出去的步骤就对不上屏幕上的按钮。
 */
import { describe, expect, it } from 'vitest'

import { installPlatform, isLoopback } from '../src/installGuide'

const UA = {
  iphoneSafari:
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1',
  iphoneChrome:
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/138.0.7204.119 Mobile/15E148 Safari/604.1',
  iphoneLine:
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Safari Line/15.9.0',
  androidChrome:
    'Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36',
  androidLine:
    'Mozilla/5.0 (Linux; Android 15; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/138.0.0.0 Mobile Safari/537.36 Line/15.9.0/IAB',
  // iPad 默认「桌面版网站」：UA 和 Mac 一模一样，只能靠触屏认
  ipadDesktop:
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15',
  macChrome:
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
}

describe('installPlatform', () => {
  it('iPhone 上分得清 Safari、别的浏览器和 LINE 里的浏览器', () => {
    expect(installPlatform(UA.iphoneSafari)).toBe('ios-safari')
    expect(installPlatform(UA.iphoneChrome)).toBe('ios-other')
    expect(installPlatform(UA.iphoneLine)).toBe('in-app')
  })

  it('安卓：Chrome 给安卓的步骤，LINE 里的浏览器先让它换出去', () => {
    expect(installPlatform(UA.androidChrome)).toBe('android')
    expect(installPlatform(UA.androidLine)).toBe('in-app')
  })

  it('iPad 的「桌面版网站」靠触屏认成 iOS；真的 Mac 不是', () => {
    expect(installPlatform(UA.ipadDesktop, 5)).toBe('ios-safari')
    expect(installPlatform(UA.ipadDesktop, 0)).toBe('other')
    expect(installPlatform(UA.macChrome, 0)).toBe('other')
  })
})

describe('isLoopback', () => {
  it('跑服务的那台电脑自己打开的地址，别的手机打不开', () => {
    for (const h of ['localhost', 'nagaya.localhost', '127.0.0.1', '127.1.2.3', '[::1]', '0.0.0.0', '[::]']) expect(isLoopback(h)).toBe(true)
    for (const h of ['10.0.0.89', '192.168.1.5', 'nagaya.local', 'ledger.example.com']) expect(isLoopback(h)).toBe(false)
  })
})
