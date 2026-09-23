/**
 * 前后端两份色板必须逐项、按顺序一致。
 *
 * 后端 `app/models.py` 建默认分类用 CATEGORY_COLORS、给新人发头像色按顺序从
 * MEMBER_COLORS 里挑；前端 `src/palette.ts` 让人在同一组颜色里挑。只改了一边的话，
 * 建人时发的颜色在挑色板里找不到，选中态也对不上 —— 而界面上不会报任何错。
 * 分摊有共享 fixture、错误码有 error-codes 守卫，这组是原来唯一没人守的前后端孪生常量。
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { CATEGORY_COLORS, MEMBER_COLORS } from '../src/palette'

const MODELS = resolve(dirname(fileURLToPath(import.meta.url)), '../../backend/app/models.py')

function listAfter(src: string, head: RegExp): string[] {
  const m = src.match(new RegExp(head.source + String.raw`\s*\[([^\]]*)\]`, head.flags))
  if (!m) throw new Error(`models.py 里色板的写法变了（找不到 ${head.source}），这条守卫要跟着改`)
  return [...m[1]!.matchAll(/"(#[0-9a-fA-F]{6})"/g)].map((x) => x[1]!.toLowerCase())
}

describe('色板：前后端同一组', () => {
  const src = readFileSync(MODELS, 'utf-8')
  const category = listAfter(src, /^CATEGORY_COLORS = /m)
  const extra = listAfter(src, /^MEMBER_COLORS = CATEGORY_COLORS \+ /m)

  it('确实从 models.py 读到了色板（正则写错会空跑成假绿）', () => {
    expect(category.length).toBeGreaterThanOrEqual(10)
    expect(extra.length).toBeGreaterThan(0)
  })

  it('分类那一组逐项、按顺序一致', () => {
    expect(CATEGORY_COLORS.map((c) => c.toLowerCase())).toEqual(category)
  })

  it('头像那一组逐项、按顺序一致（后端按顺序发色）', () => {
    expect(MEMBER_COLORS.map((c) => c.toLowerCase())).toEqual([...category, ...extra])
  })
})
