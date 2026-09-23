/**
 * 文字色必须看得清。
 *
 * 这个 App 的内容 100% 是数字，「看不清」直接等于「读错钱」。改之前全站的
 * 次要灰字走的是 Quasar 的 text-grey-6（#9e9e9e），在白底上只有 2.85:1 ——
 * 而它印的恰恰是账单上「谁垫了多少、上期结转多少」那几行：白天在户外
 * 或者屏幕自动调暗时，只剩加粗的黑色总额看得清。
 *
 * 这条用例直接从 tokens.css 里把值读出来算，改坏了当场红。
 * WCAG AA：正文 4.5:1，18px 以上的大字 3:1。
 */
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const css = readFileSync(new URL('../src/css/tokens.css', import.meta.url), 'utf8')

function token(name: string): string {
  const m = css.match(new RegExp(`--nagaya-${name}:\\s*([^;]+);`))
  expect(m, `tokens.css 里没有 --nagaya-${name}`).not.toBeNull()
  return m![1]!.trim()
}

/** 相对亮度（WCAG 定义） */
function luminance(hex: string): number {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const ch = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255)
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(ch[0]!) + 0.7152 * lin(ch[1]!) + 0.0722 * lin(ch[2]!)
}

const ratio = (a: string, b: string) => {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m)
  return (x! + 0.05) / (y! + 0.05)
}

describe('文字对比度', () => {
  const white = '#ffffff'

  it.each([
    ['ink', 4.5],
    ['ink-2', 4.5],
    ['ink-3', 4.5],
    // accent 现在是主题色（每个人自己挑），逐档在 theme-colors.spec.ts 里算
    ['pos', 4.5],
    ['neg', 4.5],
    ['warn', 4.5],
  ])('白底上的 --nagaya-%s 至少 %s:1', (name, min) => {
    const got = ratio(token(name as string), white)
    expect(Math.round(got * 100) / 100, `${name} 只有 ${got.toFixed(2)}:1`).toBeGreaterThanOrEqual(
      min as number,
    )
  })

  it('占位符那一档可以低，但不许低到看不见（≥ 2:1）', () => {
    expect(ratio(token('ink-4'), white)).toBeGreaterThanOrEqual(2)
  })

  it('Quasar 的灰阶工具类被接管了 —— 它自己那几个值都不够 4.5:1', () => {
    for (const cls of ['text-grey-5', 'text-grey-6', 'text-grey-7']) {
      expect(css, `${cls} 没有被接管`).toContain(`.${cls} {`)
    }
    // 接管前后的差距：Quasar 的 $grey-6 是 #9e9e9e
    expect(ratio('#9e9e9e', white)).toBeLessThan(4.5)
    expect(ratio(token('ink-3'), white)).toBeGreaterThanOrEqual(4.5)
  })
})

/**
 * 深色那一套（html.dark 里那一块）。基准是深色的**卡片底**：数字都印在卡片上。
 * 深色下最容易出事的是「浅色值原样留着」—— 藏青的字印在近黑的底上只有 2:1。
 */
describe('深色模式的文字对比度', () => {
  const block = css.match(/html\.dark\s*\{([\s\S]*?)\n\}/)
  it('tokens.css 里有 html.dark 那一块', () => {
    expect(block, '没找到 html.dark { … }').not.toBeNull()
  })
  const dark = (name: string): string => {
    const m = block![1]!.match(new RegExp(`--nagaya-${name}:\\s*([^;]+);`))
    expect(m, `html.dark 里没有 --nagaya-${name}`).not.toBeNull()
    return m![1]!.trim()
  }

  it.each([
    ['ink', 4.5],
    ['ink-2', 4.5],
    ['ink-3', 4.5],
    ['pos', 4.5],
    ['neg', 4.5],
    ['warn', 4.5],
    ['kind-expense', 4.5],
    ['kind-income', 4.5],
    ['kind-settlement', 4.5],
  ])('深色卡片底上的 --nagaya-%s 至少 %s:1', (name, min) => {
    const got = ratio(dark(name as string), dark('surface'))
    expect(Math.round(got * 100) / 100, `${name} 只有 ${got.toFixed(2)}:1`).toBeGreaterThanOrEqual(
      min as number,
    )
  })

  it('占位符那一档可以低，但不许低到看不见（≥ 2:1）', () => {
    expect(ratio(dark('ink-4'), dark('surface'))).toBeGreaterThanOrEqual(2)
  })
})
