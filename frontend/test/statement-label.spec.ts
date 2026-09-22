/**
 * 账单名字按**日本时间**的出账日。cut_at 是 naive UTC：
 * 日本时间 9/22 00:30 出的账，存的是 9/21 15:30 —— 原来会叫「9/21 出账」。
 */
import { beforeAll, expect, it, vi } from 'vitest'

let statementLabel: typeof import('../src/statement').statementLabel

beforeAll(async () => {
  // i18n 一加载就要读语言偏好，node 里没有这两样
  vi.stubGlobal('localStorage', { getItem: () => 'zh', setItem() {}, removeItem() {} })
  vi.stubGlobal('navigator', { language: 'zh-CN' })
  ;({ statementLabel } = await import('../src/statement'))
})

it('JST 凌晨出的账不退回前一天', () => {
  expect(statementLabel({ label: '', cut_at: '2026-09-21T15:30:00' })).toBe('9/22 出账')
})

it('用户自己起的名字照原样', () => {
  expect(statementLabel({ label: '搬家那次', cut_at: '2026-09-21T15:30:00' })).toBe('搬家那次')
})
