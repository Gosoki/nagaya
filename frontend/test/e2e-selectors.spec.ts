/**
 * E2E 里用到的 class 选择器必须在源码里真的存在。
 *
 * 界面改版会把类名换掉，而 Playwright 对着一个不存在的选择器只会**超时**，
 * 报的是「等不到元素」，看上去像页面坏了，没人会想到是选择器过期。
 * 已经栽过三次：.share（应担那列改成 .share-col）、.text-h6（转账卡片改版）、
 * .exact-input（固定金额那列并进了 .num-input）。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = new URL('../src', import.meta.url).pathname
const E2E = new URL('../e2e', import.meta.url).pathname

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
    d.isDirectory() ? walk(join(dir, d.name)) : [join(dir, d.name)],
  )
}

const source = walk(SRC)
  .filter((f) => f.endsWith('.vue') || f.endsWith('.ts'))
  .map((f) => readFileSync(f, 'utf8'))
  .join('\n')

describe('E2E 选择器', () => {
  for (const file of walk(E2E).filter((f) => f.endsWith('.spec.ts'))) {
    it(`${file.split('/').pop()} 里的 class 在源码里都找得到`, () => {
      const spec = readFileSync(file, 'utf8')
      const missing = new Set<string>()
      for (const m of spec.matchAll(/locator\(\s*'([^']+)'/g)) {
        for (const [, cls] of m[1]!.matchAll(/\.([a-zA-Z][\w-]*)/g)) {
          // q-* 是 Quasar 自带的，不在我们源码里
          if (cls!.startsWith('q-') || cls!.startsWith('text-') || cls!.startsWith('bg-')) continue
          if (!new RegExp(`["'\\s]${cls}["'\\s]`).test(source)) missing.add(cls!)
        }
      }
      expect([...missing], '这些 class 在 src 里不存在，用例只会超时不会报错').toEqual([])
    })
  }
})
