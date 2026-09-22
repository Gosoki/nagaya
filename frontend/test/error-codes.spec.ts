/**
 * 后端抛出的每个业务错误码，前端都得有话说。
 *
 * 少一个的下场不是崩，是**默默换一种语言**：ApiError.text 查不到 key 就退回后端那句
 * message，而后端的 message 全是中文写给开发看的 —— 于是日文界面上，「空草稿点出账」
 * 弹出来的是一句「现在没有待出账的账目」。
 *
 * 实测漏过五个：entry_deleted / nothing_to_cut / unknown_category /
 * unknown_mode / unknown_remainder_to。其中前两个用户天天能碰到。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import ja from '../src/i18n/ja'
import zh from '../src/i18n/zh'

const BACKEND = resolve(dirname(fileURLToPath(import.meta.url)), '../../backend/app')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return name.endsWith('.py') ? [full] : []
  })
}

/**
 * 哪些异常类会被翻成 `{code, message, detail}` 给前端 —— **照 main.py 的注册元组推导**，
 * 不手抄。
 *
 * 手抄那份名单已经漏过两次（`BackupError` 漏了一整轮）。而且推导出来的语义
 * 恰好就是对的：**注册了才会变成 4xx 送到用户眼前，才需要文案**；
 * 没注册的（`SettleError` —— 它只在 Σ余额≠0 时抛，那是地基塌了，该是 500）
 * 自动、而且正确地不在名单里。
 */
function registeredFamilies(): string[] {
  const main = readFileSync(resolve(BACKEND, 'main.py'), 'utf-8')
  const m = main.match(/for error_type in \(([^)]*)\)/)
  if (!m) throw new Error('main.py 里那个注册元组的写法变了，这条守卫要跟着改')
  return m[1]
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => x.replace(/Error$/, ''))
}

/** 后端抛出来的、会送到用户眼前的所有 code */
function backendCodes(): string[] {
  const families = registeredFamilies().join('|')
  const re = new RegExp(`\\b(?:${families})Error\\(\\s*\\n?\\s*"([a-z_]+)"`, 'g')
  const out = new Set<string>()
  for (const file of walk(BACKEND)) {
    const text = readFileSync(file, 'utf-8')
    for (const m of text.matchAll(re)) out.add(m[1])
    // not_found() 是 AppError 的快捷方式，正则扫不到
    if (/\bnot_found\(/.test(text)) out.add('not_found')
  }
  return [...out].sort()
}

describe('后端错误码 ↔ 前端文案', () => {
  const codes = backendCodes()

  it('扫到了错误码（正则写错会空跑成假绿）', () => {
    expect(registeredFamilies(), '注册元组该有六族').toContain('App')
    expect(registeredFamilies(), 'SettleError 是故意不注册的').not.toContain('Settle')
    expect(codes.length).toBeGreaterThan(20)
    expect(codes).toContain('sum_mismatch')
    expect(codes, '路由错那一路也要扫到').toContain('not_found')
  })

  it('每个 code 在中文词条里都有一句话', () => {
    const missing = codes.filter((c) => !(c in (zh.errors as Record<string, string>)))
    expect(missing, '缺文案的 code 会退回后端那句中文，日文界面上就露馅了').toEqual([])
  })

  it('日文那份也一个不少', () => {
    const missing = codes.filter((c) => !(c in (ja.errors as Record<string, string>)))
    expect(missing).toEqual([])
  })
})
