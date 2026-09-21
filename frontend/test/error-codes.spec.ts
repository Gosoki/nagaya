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

/** 后端所有 XxxError("code", ...) 里的 code */
function backendCodes(): string[] {
  const out = new Set<string>()
  for (const file of walk(BACKEND)) {
    const text = readFileSync(file, 'utf-8')
    for (const m of text.matchAll(/\b(?:Ledger|Bill|Rule|Split)Error\(\s*\n?\s*"([a-z_]+)"/g)) {
      out.add(m[1])
    }
  }
  return [...out].sort()
}

describe('后端错误码 ↔ 前端文案', () => {
  const codes = backendCodes()

  it('扫到了错误码（正则写错会空跑成假绿）', () => {
    expect(codes.length).toBeGreaterThan(8)
    expect(codes).toContain('sum_mismatch')
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
