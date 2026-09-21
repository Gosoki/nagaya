/**
 * 「谁付的」那一排按钮：切换时整排不许动。
 *
 * 选中态要加粗，而加粗会让字变宽 —— 一排三个，切一下整排就左右挪一下。
 * 实测改之前：选中 Kan 会让它从 54.4px 变成 56.3px，前面两个跟着左移约 2px。
 *
 * 这里盯的是做法：按钮永远按**加粗后的宽度**占位（底下压一层不可见的粗体同款
 * 文字把格子撑开），而不是靠「别加粗了」把问题绕过去。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

const src = readFileSync(fileURLToPath(new URL('../src/components/MemberPicker.vue', import.meta.url)), 'utf8')

describe('成员选择器切换时不左右挪', () => {
  it('留了一层按加粗宽度撑格子的占位', () => {
    expect(src).toMatch(/\.pick::before\s*\{[^}]*content:\s*attr\(data-label\)/)
    expect(src).toMatch(/\.pick::before\s*\{[^}]*font-weight:\s*600/)
    expect(src).toMatch(/\.pick::before\s*\{[^}]*visibility:\s*hidden/)
  })

  it('两层叠在同一个网格格子里 —— 格子宽度才会取两者的最大值', () => {
    expect(src).toMatch(/\.pick\s*\{[^}]*display:\s*inline-grid/)
    expect(src).toMatch(/grid-area:\s*1\s*\/\s*1/)
  })

  it('data-label 和显示的文字是同一个来源，不会写岔', () => {
    expect(src).toContain(':data-label="short(m.display_name)"')
    expect(src).toContain('<span class="label">{{ short(m.display_name) }}</span>')
  })
})
