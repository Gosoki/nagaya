/**
 * 所有列表行的头像圆圈必须一样大。
 *
 * 之前是 26 / 28 / 30 / 32 / 34 五种尺寸散在四个文件里，同一屏上下相邻的
 * 两段列表圆圈就明显不一样大。改一处很容易忘了另外六处，所以钉住它。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { expect, it } from 'vitest'

const SRC = new URL('../src', import.meta.url).pathname

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
    d.isDirectory() ? walk(join(dir, d.name)) : [join(dir, d.name)],
  )
}

it('q-avatar 只有一种尺寸', () => {
  const sizes = new Map<string, string[]>()
  for (const f of walk(SRC).filter((x) => x.endsWith('.vue'))) {
    for (const m of readFileSync(f, 'utf8').matchAll(/<q-avatar\s+size="(\d+px)"/g)) {
      sizes.set(m[1]!, [...(sizes.get(m[1]!) ?? []), f.split('/').pop()!])
    }
  }
  expect([...sizes.keys()], `头像尺寸不统一：${JSON.stringify([...sizes])}`).toHaveLength(1)
})
