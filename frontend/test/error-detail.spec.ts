/**
 * 每个错误文案里的 `{占位符}`，后端真的传了那个名字的参数吗。
 *
 * 对不上的下场不是崩，是**界面上留一个插不进去的空洞**：
 * 「备份没做成：」后面什么都没有。而现有的守卫一条都查不出来 ——
 * error-codes 只管「code 有没有文案」，i18n-keys 只管「键存不存在」，
 * 两条都不看文案**里面**写了什么。实测就漏过一条（backup_failed 要 message、
 * 后端传的是 path）。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import ja from '../src/i18n/ja'
import zh from '../src/i18n/zh'

const BACKEND = resolve(__dirname, '../../backend/app')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return name.endsWith('.py') ? [full] : []
  })
}

/** 后端每个 code 实际塞进 detail 的键。detail 就是前端查文案时的命名参数 */
function detailKeys(): Record<string, Set<string>> {
  const out: Record<string, Set<string>> = {}
  const re =
    /\b(?:Ledger|Rule|Split|Bill|Backup|App)Error\(\s*\n?\s*"([a-z_]+)"([\s\S]*?)\)\s*(?:from|$|\n)/g
  for (const file of walk(BACKEND)) {
    for (const m of readFileSync(file, 'utf-8').matchAll(re)) {
      const set = (out[m[1]] ??= new Set())
      for (const kw of m[2].matchAll(/(\w+)\s*=/g)) if (kw[1] !== 'status') set.add(kw[1])
    }
  }
  ;(out['not_found'] ??= new Set()).add('what')
  return out
}

const holes = (msg: string) => [...msg.matchAll(/\{(\w+)\}/g)].map((m) => m[1])

describe('错误文案的占位符 ↔ 后端 detail', () => {
  const backend = detailKeys()

  it('扫到了 detail（正则写错会空跑成假绿）', () => {
    expect(Object.keys(backend).length).toBeGreaterThan(15)
    expect([...(backend['sum_mismatch'] ?? [])]).toContain('diff')
  })

  for (const [lang, dict] of [['zh', zh], ['ja', ja]] as const) {
    it(`${lang}：每个占位符后端都传得出来`, () => {
      const bad: string[] = []
      for (const [code, msg] of Object.entries(dict.errors as Record<string, string>)) {
        const want = holes(msg)
        const got = backend[code]
        if (!got) continue // 后端不抛的 code：前端自己填参数的（network 这类）；「有文案没 code」由 error-codes.spec 管
        for (const h of want) if (!got.has(h)) bad.push(`${code} 要 {${h}}，后端只传 ${[...got]}`)
      }
      expect(bad, '界面上会留一个插不进去的空洞').toEqual([])
    })
  }

  it('中日两份的占位符集合必须一样', () => {
    const bad: string[] = []
    for (const code of Object.keys(zh.errors as Record<string, string>)) {
      const a = holes((zh.errors as Record<string, string>)[code]).sort().join(',')
      const b = holes((ja.errors as Record<string, string>)[code] ?? '').sort().join(',')
      if (a !== b) bad.push(`${code}: zh={${a}} ja={${b}}`)
    }
    expect(bad).toEqual([])
  })
})
