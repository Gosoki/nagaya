/**
 * 拼进 html: true 的弹框之前必须转义。固定费项目的名字是用户起的，
 * 出账确认框原来把它原样拼进去 —— 名字叫 `<img src=x onerror=…>` 就是存储型 XSS。
 */
import { expect, it } from 'vitest'

import { escapeHtml } from '../src/html'

it('尖括号、引号、& 都转义掉', () => {
  expect(escapeHtml('<img src=x onerror="alert(1)">')).toBe(
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
  )
  expect(escapeHtml("A & B's")).toBe('A &amp; B&#39;s')
})

it('普通的名字原样通过', () => {
  expect(escapeHtml('燃气、水费 还空着')).toBe('燃气、水费 还空着')
})
