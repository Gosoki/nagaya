/**
 * 主题色色板：每一档都得在四个地方站得住（src/themeColor.ts）。
 * 主题色管的是链接、选中的页签、按钮 —— 看不清就是点不到、认不出选的是哪个。
 */
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import ja from '../src/i18n/ja'
import zh from '../src/i18n/zh'
import { THEME_COLORS } from '../src/themeColor'

function luminance(hex: string): number {
  const h = hex.replace('#', '')
  const ch = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(ch[0]!) + 0.7152 * lin(ch[1]!) + 0.0722 * lin(ch[2]!)
}
const ratio = (a: string, b: string) => {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m)
  return (x! + 0.05) / (y! + 0.05)
}

const css = readFileSync(new URL('../src/css/tokens.css', import.meta.url), 'utf8')
const darkSurface = css.match(/html\.dark\s*\{[\s\S]*?--nagaya-surface:\s*(#[0-9a-f]{6})/i)![1]!
const WHITE = '#ffffff'

describe.each(THEME_COLORS.map((c) => [c.id, c] as const))('主题色 %s', (_id, c) => {
  it('浅色：白底上当字 ≥4.5，当按钮底时白字 ≥4.5', () => {
    expect(ratio(c.light, WHITE)).toBeGreaterThanOrEqual(4.5)
  })
  it('深色：卡片底上当字 ≥4.5', () => {
    expect(ratio(c.darkInk, darkSurface)).toBeGreaterThanOrEqual(4.5)
  })
  it('深色：按钮底上白字 ≥4.5，按钮和卡片分得开（≥3）', () => {
    expect(ratio(WHITE, c.darkFill)).toBeGreaterThanOrEqual(4.5)
    expect(ratio(c.darkFill, darkSurface)).toBeGreaterThanOrEqual(3)
  })
})

it('默认那一档就是 tokens.css 里写的那一档', () => {
  const def = THEME_COLORS[0]!
  expect(css).toContain(`--nagaya-theme: ${def.light};`)
  expect(css).toContain(`--nagaya-theme-dark-fill: ${def.darkFill};`)
  expect(css).toContain(`--nagaya-theme-dark-ink: ${def.darkInk};`)
})

it('每一档中日都有名字（色块的读屏标签和长按提示用它）', () => {
  for (const c of THEME_COLORS) {
    expect((zh.profile.themeColors as Record<string, string>)[c.id], `zh 缺 ${c.id}`).toBeTruthy()
    expect((ja.profile.themeColors as Record<string, string>)[c.id], `ja 缺 ${c.id}`).toBeTruthy()
  }
})
