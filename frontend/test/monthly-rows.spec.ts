/**
 * 固定费面板一行的状态机（src/core/monthlyRows.ts）。
 *
 * 这一屏是前端唯一会替人写钱的地方，出过事的全是时序：保存还在路上时又改了被吞掉（审计 #7）、
 * 「已照上期」拿框里的字说了假话（#62）、重建时把没存上的输入悄悄变成 PATCH 室友那一笔（#22）。
 * E2E 卡不准这些毫秒，所以把判定抽出来在这儿逐个时序钉住。
 */
import { describe, expect, it } from 'vitest'

import {
  amountOf,
  carryShown,
  eachLive,
  isAtLast,
  isCarryBlocked,
  isCarryReady,
  jumpFactor,
  lastAction,
  mergeHeld,
  payerOf,
  saveSig,
  settleSaved,
} from '../src/core/monthlyRows'

/** 面板上的一行，只带判定用得到的那几样 */
function row(over: Record<string, unknown> = {}) {
  return {
    text: '',
    dirty: false,
    rule_override: null as Record<string, unknown> | null,
    entry_id: null as number | null,
    version: null as number | null,
    amount: null as number | null,
    entry_count: 0,
    carry_amount: null as number | null,
    carry_blocked: null as string | null,
    last_amount: null as number | null,
    conflict: null as unknown,
    ...over,
  }
}

describe('存完清不清「没存上」（#7）', () => {
  it('对照：请求在路上时这一行没动过 → 正常清掉', () => {
    const r = row({ text: '9,000', dirty: true, entry_id: 5 })
    const sent = saveSig(r)
    expect(settleSaved(r, sent)).toBe(true)
    expect(r.dirty).toBe(false)
  })

  it('T1：PATCH 9,000 还在路上，又改成 9,100 → 留着 dirty，排着的那次接着存', () => {
    const r = row({ text: '9,000', dirty: true, entry_id: 5 })
    const sent = saveSig(r)
    r.text = '9,100'
    expect(settleSaved(r, sent)).toBe(false)
    expect(r.dirty, '新值被静默丢掉：屏幕 9,100、库里 9,000，框还不红').toBe(true)
  })

  it('T2：打了 4,000 直接点「照上期」—— 失焦的 POST 先出门，点击再把框改成上期的数', () => {
    const r = row({ text: '4,000', dirty: true, carry_amount: 3200, last_amount: 3200 })
    const sent = saveSig(r)                         // 失焦：POST 4,000 出门
    // 点击走「替人敲进框里」那条路，不是 carry —— 框里有字，而且这一行正在存
    expect(lastAction(r, false, true)).toBe('type')
    r.text = '3,200'
    r.dirty = true
    expect(settleSaved(r, sent)).toBe(false)        // POST 回来
    expect(r.dirty).toBe(true)
    expect(isAtLast({ ...r, amount: 4000 }), '库里是 4,000，不许写「已照上期」').toBe(false)
  })

  it('T3：打完金额马上去改分摊（排除一个人）→ 改的分摊不许被 POST 的回应清掉', () => {
    const r = row({ text: '4,000', dirty: true })
    const sent = saveSig(r)
    r.rule_override = { mode: 'ratio', weights: { 1: 1, 2: 0, 3: 1 } }
    expect(settleSaved(r, sent)).toBe(false)
    expect(r.rule_override, '屏幕上 Kan 不参与，库里是均分').not.toBeNull()
  })

  it('清空（DELETE）还在路上时重打了 9,100 → 留着，下一次带着它去 POST', () => {
    const r = row({ text: '', dirty: true, entry_id: 5 })
    const sent = saveSig(r)
    r.text = '9,100'
    expect(settleSaved(r, sent)).toBe(false)
    expect(r.dirty).toBe(true)
  })

  it('比内容不比引用：分摊编辑器重新 emit 了一个内容一样的新对象，照常清掉', () => {
    const r = row({ text: '4,000', dirty: true, rule_override: { mode: 'ratio', weights: { 1: 1 } } })
    const sent = saveSig(r)
    r.rule_override = { mode: 'ratio', weights: { 1: 1 } }
    expect(settleSaved(r, sent)).toBe(true)
    expect(r.rule_override).toBeNull()
  })
})

describe('「已照上期」只认库里的数（#62）', () => {
  const at = { dirty: false, entry_count: 1, amount: 120_000, last_amount: 120_000 }

  it('存好了、只有这一笔、和上期一样 → 已照上期', () => {
    expect(isAtLast(at)).toBe(true)
  })

  it('框里打的是上期的数但没存上（红框）→ 不是', () => {
    expect(isAtLast({ ...at, dirty: true })).toBe(false)
  })

  it('本期这一项有两笔 → 不是（和合计对不上）', () => {
    expect(isAtLast({ ...at, entry_count: 2 })).toBe(false)
  })

  it('还没录 → 不是；上期没给数（没开开关）→ 不是', () => {
    expect(isAtLast({ ...at, amount: null })).toBe(false)
    expect(isAtLast({ ...at, last_amount: null })).toBe(false)
    expect(isAtLast({ ...at, amount: null, last_amount: null }), 'null === null 不算').toBe(false)
  })
})

describe('「照上期」按钮', () => {
  it('还空着、没在填、没在存 → 走 carry；正在存 → 只敲进框里', () => {
    const r = row({ carry_amount: 3200, last_amount: 3200 })
    expect(isCarryReady(r, false)).toBe(true)
    expect(lastAction(r, false, false)).toBe('carry')
    expect(lastAction(r, false, true), '在存的时候再 carry 就是同一项两笔').toBe('type')
    expect(lastAction(r, true, false), '翻旧账单不 carry').toBe('type')
  })

  it('抄不了（上期有好几笔，last_amount 不给）→ 还空着时行头说为什么，按钮不露', () => {
    const r = row({ carry_blocked: 'last_multi', last_amount: null })
    expect(isCarryBlocked(r, false)).toBe(true)
    expect(carryShown(r, false)).toBe(false)
  })

  it('抄不了但上期有数（人变了）：还空着时不露按钮，打了字提示消失、按钮出来（有意的）', () => {
    const r = row({ carry_blocked: 'rule_stale', last_amount: 3200 })
    expect(carryShown(r, false)).toBe(false)
    r.text = '1'
    r.dirty = true
    expect(isCarryBlocked(r, false)).toBe(false)
    expect(carryShown(r, false)).toBe(true)
  })
})

describe('谁垫的（#23）', () => {
  const ctx = { historic: false, active: [1, 2, 3], fallback: 1 }
  const base = { entry_id: null as number | null, default_payer_id: null as number | null, last_payer_id: null as number | null, payer_id: null as number | null }

  it('已录那一笔：就是后端给的那个人，不往下猜', () => {
    expect(payerOf({ ...base, entry_id: 7, payer_id: 2, default_payer_id: 3 }, ctx)).toBe(2)
  })

  it('翻旧账单、已录却不知道是谁 → 宁可空着也不猜', () => {
    expect(payerOf({ ...base, entry_id: 7 }, { ...ctx, historic: true })).toBeNull()
  })

  it('没录：分类默认（还住着）→ 上期那一笔 → 兜底；默认那位搬走了就跳过他', () => {
    expect(payerOf({ ...base, default_payer_id: 3, last_payer_id: 2 }, ctx)).toBe(3)
    expect(payerOf({ ...base, default_payer_id: 9, last_payer_id: 2 }, ctx)).toBe(2)
    expect(payerOf({ ...base, default_payer_id: 9 }, ctx)).toBe(1)
  })
})

describe('重建时手里那一行怎么办（#22）', () => {
  const server = (over: Record<string, unknown> = {}) => ({ entry_id: null as number | null, version: null as number | null, amount: null as number | null, ...over })

  it('手里没东西 / 没 dirty → 照服务器的来', () => {
    expect(mergeHeld(undefined, server())).toBe('server')
    expect(mergeHeld(row({ text: '3,000', entry_id: 45, version: 1 }), server({ entry_id: 45, version: 2, amount: 3500 }))).toBe('server')
  })

  it('新填的还没存上、服务器这一项也还空着 → 留着输入', () => {
    expect(mergeHeld(row({ text: '3,500', dirty: true }), server())).toBe('keep')
  })

  it('T8：断网填了车位 3,500，室友记了 3,000 → 冲突，不许变成 PATCH 他那一笔', () => {
    const held = row({ text: '3,500', dirty: true })
    expect(mergeHeld(held, server({ entry_id: 45, version: 1, amount: 3000 }))).toBe('conflict')
  })

  it('两边一样（室友记的同一个数，或者自己的 POST 其实成功了）→ 采用服务器的，不再写', () => {
    expect(mergeHeld(row({ text: '3,000', dirty: true }), server({ entry_id: 45, version: 1, amount: 3000 }))).toBe('same')
  })

  it('一样的数但我还改了分摊 → 照样算冲突（分摊不能被悄悄丢掉）', () => {
    const held = row({ text: '3,000', dirty: true, rule_override: { mode: 'ratio' } })
    expect(mergeHeld(held, server({ entry_id: 45, version: 1, amount: 3000 }))).toBe('conflict')
  })

  it('同一笔被人改过（version 被推高）→ 冲突：不许吸收新 version 再 PATCH 过去', () => {
    const held = row({ text: '6,000', dirty: true, entry_id: 40, version: 1 })
    expect(mergeHeld(held, server({ entry_id: 40, version: 2, amount: 5800 }))).toBe('conflict')
  })

  it('自己存成功过（version 已经写回手里）→ 不算被人改过', () => {
    const held = row({ text: '6,100', dirty: true, entry_id: 40, version: 2 })
    expect(mergeHeld(held, server({ entry_id: 40, version: 2, amount: 6000 }))).toBe('keep')
  })

  it('手里那一笔被出账带走了 → taken（输入丢掉、说一声）', () => {
    const held = row({ text: '6,100', dirty: true, entry_id: 40, version: 2 })
    expect(mergeHeld(held, server())).toBe('taken')
    expect(mergeHeld(held, server({ entry_id: 51, version: 1, amount: 6000 }))).toBe('taken')
  })

  it('我这边是个空着的新行 → 没什么可冲突的', () => {
    expect(mergeHeld(row({ text: '', dirty: true }), server({ entry_id: 45, version: 1, amount: 3000 }))).toBe('server')
  })

  it('还没选的冲突，服务器没再变 → 接着挂着', () => {
    // 冲突的行已经换上了服务器那一笔的 entry_id/version，所以「没变」
    const held = row({ text: '3,500', dirty: true, entry_id: 45, version: 1, conflict: { amount: 3000 } })
    expect(mergeHeld(held, server({ entry_id: 45, version: 1, amount: 3000 }))).toBe('conflict')
  })
})

describe('量级闸的倍数（#4）', () => {
  it('往上、往下都换成 ≥1 的倍数；10 倍以上取整', () => {
    expect(jumpFactor(10)).toBe(10)
    expect(jumpFactor(0.1)).toBe(10)
    expect(jumpFactor(4.26)).toBe(4.3)
    expect(jumpFactor(0.25)).toBe(4)
    expect(jumpFactor(12.6)).toBe(13)
  })

  it('认不出的给 null（调用方退回不带数字的那句）', () => {
    expect(jumpFactor(0)).toBeNull()
    expect(jumpFactor(undefined)).toBeNull()
    expect(jumpFactor('x')).toBeNull()
  })
})

it('框里的字 → 金额：全角、逗号都认，空的是 0', () => {
  expect(amountOf('１２,０００')).toBe(12_000)
  expect(amountOf('')).toBe(0)
})

describe('出账前兜底存 / 离屏兜底存：每一步现取那一行（R8）', () => {
  type R = { category_id: number; name: string; dirty: boolean }
  const clone = (r: R): R => ({ ...r })

  it('前一行撞 409 触发重建：后面的行存的是屏幕上那份新对象，存完不再挂「没存上」', async () => {
    let rows: R[] = [
      { category_id: 1, name: '房租', dirty: true },
      { category_id: 2, name: '电费', dirty: true },
    ]
    const saved: R[] = []
    await eachLive(
      () => rows,
      async (row) => {
        saved.push(row)
        row.dirty = false
        // 房租撞 version_conflict → 面板 load() → build() 把每一行换成新对象（输入、dirty 原样拷过去）
        if (row.category_id === 1) rows = rows.map(clone)
      },
    )
    expect(saved[1], '存的是重建前那份旧对象').toBe(rows[1])
    expect(rows.filter((r) => r.dirty).map((r) => r.name), '出账会被误拦成「1 项没存上」').toEqual([])
  })

  it('重建之后不见了的行（项被删掉了）：跳过', async () => {
    let rows: R[] = [
      { category_id: 1, name: '房租', dirty: true },
      { category_id: 2, name: '电费', dirty: true },
    ]
    const names: string[] = []
    await eachLive(
      () => rows,
      async (row) => {
        names.push(row.name)
        if (row.category_id === 1) rows = [clone(rows[0]!)]
      },
    )
    expect(names).toEqual(['房租'])
  })
})
