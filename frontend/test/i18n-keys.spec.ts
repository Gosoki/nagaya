/**
 * 代码里用到的每个 t('…') 词条都必须真的存在。
 *
 * 起因：我用正则删一个 `monthly.save` 词条时，`^\s*save:` 先匹配到了 common 段里
 * 那一行，把整行删掉了 —— cancel / delete / edit / confirm / undo 一起没了。
 * 界面上的表现是按钮直接显示成 `common.confirm` 这种原始 key，
 * 而这种伤害只有在你恰好点开那个对话框时才看得见。
 *
 * 顺带也挡住反向的问题：中日两份词条对不齐。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import ja from '../src/i18n/ja'
import zh from '../src/i18n/zh'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '../src')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.(vue|ts)$/.test(name) && !full.includes('/i18n/') ? [full] : []
  })
}

function flatten(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === 'object' && v !== null
      ? flatten(v as Record<string, unknown>, `${prefix}${k}.`)
      : [`${prefix}${k}`],
  )
}

const zhKeys = new Set(flatten(zh as Record<string, unknown>))
const jaKeys = new Set(flatten(ja as Record<string, unknown>))

/** 代码里出现的 t('a.b') —— 只收静态字面量，模板拼出来的键管不了 */
function usedKeys(): { key: string; where: string }[] {
  const out: { key: string; where: string }[] = []
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf-8')
    for (const m of text.matchAll(/\bt\(\s*'([a-zA-Z][\w.]*)'/g)) {
      out.push({ key: m[1], where: `${file.replace(SRC, 'src')}` })
    }
  }
  return out
}

describe('i18n 词条完整性', () => {
  const used = usedKeys()

  it('扫到了词条引用（别因为正则写错而空跑变成假绿）', () => {
    expect(used.length).toBeGreaterThan(30)
  })

  it('代码里用到的键，中文词条里必须都有', () => {
    const missing = used.filter((u) => !zhKeys.has(u.key))
    expect(missing.map((m) => `${m.key} (${m.where})`), '缺词条，界面会直接显示原始 key').toEqual([])
  })

  it('没有谁也不用的词条', () => {
    // 死词条不会让界面出错，但它会骗人：改文案时以为改到了、其实那一条早就没人读。
    // 实测清出 25 条 —— 包括整个 balance.* 段（余额页并进账单页之后忘了删）
    // 和 bill.cutEmpty（本来是给 nothing_to_cut 准备的，结果一直没接上）。
    //
    // 这三个前缀是**按 code 现查**的，静态扫不到，不能算死：
    //   errors.*          client.ts 用 t(`errors.${code}`)
    //   settings.label.*  SettingsPanel 用 t(`settings.label.${key}`)
    //   settings.option.* 同上
    const DYNAMIC = ['errors.', 'settings.label.', 'settings.option.']
    const used = new Set(usedKeys().map((u) => u.key))
    const dead = [...zhKeys].filter(
      (k) => !used.has(k) && !DYNAMIC.some((p) => k.startsWith(p)),
    )
    expect(dead, '这些词条没有任何地方引用').toEqual([])
  })

  it('中日两份词条的键必须一一对应', () => {
    const onlyZh = [...zhKeys].filter((k) => !jaKeys.has(k))
    const onlyJa = [...jaKeys].filter((k) => !zhKeys.has(k))
    expect({ onlyZh, onlyJa }).toEqual({ onlyZh: [], onlyJa: [] })
  })
})
