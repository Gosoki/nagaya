/**
 * theme.ts 的颜色必须和 quasar-variables.sass 对得上。
 *
 * 两边各写一份是没办法的事：Quasar 组件的 color 属性只认 palette 名字，
 * 而画头像要的是 hex。分开写就会分开漂 —— 改了 sass 忘了 ts，
 * 界面上同一种账目在不同页面是两个绿。
 */
import { readFileSync } from 'node:fs'

import { expect, it } from 'vitest'

import { KIND_COLOR, KIND_PALETTE } from '../src/theme'

const sass = readFileSync(new URL('../src/quasar-variables.sass', import.meta.url), 'utf8')
const tokens = readFileSync(new URL('../src/css/tokens.css', import.meta.url), 'utf8')

it('每种账目的 hex 和 Quasar palette 是同一个颜色', () => {
  for (const kind of Object.keys(KIND_COLOR) as (keyof typeof KIND_COLOR)[]) {
    const name = KIND_PALETTE[kind]
    // Quasar 自带的颜色在 sass 里；支出那一种（expense）是自己在 tokens.css 里补的
    const m =
      sass.match(new RegExp(`^\\$${name}\\s*:\\s*(#[0-9a-fA-F]{6})`, 'm')) ??
      tokens.match(new RegExp(`--q-${name}:\\s*(#[0-9a-fA-F]{6})`))
    expect(m, `quasar-variables.sass 和 tokens.css 里都没有 ${name}`).not.toBeNull()
    expect(m![1]!.toLowerCase(), `${kind}：theme.ts 和 sass 不一致`).toBe(KIND_COLOR[kind].toLowerCase())
  }
})
