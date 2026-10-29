/**
 * 记一笔转账 / 记在一个不在籍的人名下之前「多问一句」的判据（core/entryChecks）。
 * 都只决定问不问，问了默认按钮也是「照记」—— 所以这里钉的是「该问的问、不该问的别吵」。
 */
import { describe, expect, it } from 'vitest'

import type { Entry } from '../src/api/types'
import { payerAbsence, recentTwin, transferDoubt } from '../src/core/entryChecks'

describe('转账：方向和量级（审计 #3）', () => {
  // 正 ＝ 别人欠他，负 ＝ 他欠别人。Go 被欠 20,000，Kan、Zen 各欠 10,000
  const bal = { '1': 20_000, '2': -10_000, '3': -10_000 }

  it('照着欠款还钱：不问', () => {
    expect(transferDoubt(bal, 2, 1, 10_000, 1000)).toBeNull()
    // 容差之内多一点（凑整）也不问
    expect(transferDoubt(bal, 2, 1, 10_900, 1000)).toBeNull()
  })

  it('被欠钱的人转给欠钱的人：问方向（记反了多半就长这样）', () => {
    expect(transferDoubt(bal, 1, 2, 10_000, 1000)).toEqual({ kind: 'direction', payerOwed: 20_000, toOwes: 10_000 })
  })

  it('比此刻欠的多出容差以上：问金额（多打一个 0，或者是预付）', () => {
    expect(transferDoubt(bal, 2, 1, 100_000, 1000)).toEqual({ kind: 'over', owe: 10_000, over: 90_000 })
  })

  it('容差填 0 ＝ 不核金额；方向那条照问', () => {
    expect(transferDoubt(bal, 2, 1, 100_000, 0)).toBeNull()
    expect(transferDoubt(bal, 1, 2, 10_000, 0)?.kind).toBe('direction')
  })

  it('容差的门槛：多出恰好等于容差不问，多 1 円就问', () => {
    // Kan 欠 10,000、容差 1,000。只测 90,000 和 900 两个点的话，门槛放大十倍也照样绿
    expect(transferDoubt(bal, 2, 1, 11_000, 1000)).toBeNull()
    expect(transferDoubt(bal, 2, 1, 11_001, 1000)).toEqual({ kind: 'over', owe: 10_000, over: 1_001 })
  })

  it('两个都是被欠钱的人之间转账：不问方向（收款人不欠钱，不会「再多欠一截」）', () => {
    // Go、Kan 都是被欠钱的，Zen 欠 20,000。方向判据要两头都对上，只看付款人那半句会误问
    const two = { '1': 15_000, '2': 5_000, '3': -20_000 }
    expect(transferDoubt(two, 1, 2, 500, 1000)).toBeNull()
  })
})

describe('转账：关掉「算最少转账」时照方案付（审计 R4 / R7）', () => {
  // 逐对方案里一对的额可以比付款人的净欠还大，净被欠钱的人也可能在方案里欠某一个人。
  // planLeft 是此刻方案（草稿账单的 transfers）里 payer → to 这一对的额

  it('一对的额大于净欠：照方案付不问金额', () => {
    // Go 垫 150,000、Kan 垫 9,000，三人均摊：Kan 净欠 44,000，方案却要他给 Go 47,000（Zen 还欠 Kan 3,000）
    const bal = { '1': 97_000, '2': -44_000, '3': -53_000 }
    expect(transferDoubt(bal, 2, 1, 47_000, 1000), '没方案时只看净欠：会问').toEqual({
      kind: 'over', owe: 44_000, over: 3_000,
    })
    expect(transferDoubt(bal, 2, 1, 47_000, 1000, 47_000)).toBeNull()
    // 比这一对的额还多出容差以上：照样问，「多出」只按超过这一对的部分算
    expect(transferDoubt(bal, 2, 1, 50_000, 1000, 47_000)).toEqual({ kind: 'over', owe: 47_000, over: 3_000 })
  })

  it('三笔都只涉及两个人：方案上每一笔照付都不问', () => {
    const bal = { '1': 15_000, '2': 42_000, '3': -57_000 }
    expect(transferDoubt(bal, 3, 1, 60_000, 1000, 60_000)).toBeNull()
    expect(transferDoubt(bal, 1, 2, 45_000, 1000, 45_000)).toBeNull()
    // Kan 净是被欠钱的、Zen 净欠钱，可方案里 Kan 就是要给 Zen 3,000
    expect(transferDoubt(bal, 2, 3, 3_000, 1000), '没方案时：问方向').toMatchObject({ kind: 'direction' })
    expect(transferDoubt(bal, 2, 3, 3_000, 1000, 3_000)).toBeNull()
  })

  it('方案里没有这一对（取不到方案也是 0）：和原来一样问', () => {
    const bal = { '1': 20_000, '2': -10_000, '3': -10_000 }
    expect(transferDoubt(bal, 1, 2, 10_000, 1000, 0)?.kind).toBe('direction')
    expect(transferDoubt(bal, 2, 1, 100_000, 1000, 0)).toEqual({ kind: 'over', owe: 10_000, over: 90_000 })
  })
})

describe('转账：刚才是不是有人记过一模一样的（审计 #21）', () => {
  const now = Date.parse('2026-10-29T12:00:00Z')
  const tx = (over: Partial<Entry>): Entry =>
    ({
      id: 1, kind: 'settlement', payer_id: 2, to_member_id: 1, amount_jpy: 10_000,
      date: '2026-10-29', created_at: '2026-10-29T11:00:00', created_by: 1,
      ...over,
    }) as Entry
  const body = { payer_id: 2, to_member_id: 1, amount_jpy: 10_000 }

  it('一小时前同一对人、同金额：找出来（created_at 是 naive UTC）', () => {
    expect(recentTwin([tx({})], body, 48, now)?.id).toBe(1)
  })

  it('naive UTC 的边界：47.5 小时前算、48.5 小时前不算（按本地时区解析会差出时差）', () => {
    // 按 UTC 读：12:30 是 47.5 小时前；按 JST 本地读成 03:30Z，是 56.5 小时前 —— 漏掉。
    // 西半球的时区由下面「窗口之外」那条（11:00 按本地读会落进窗口）抓
    expect(recentTwin([tx({ created_at: '2026-10-27T12:30:00' })], body, 48, now)?.id).toBe(1)
    expect(recentTwin([tx({ created_at: '2026-10-27T11:30:00' })], body, 48, now)).toBeNull()
  })

  it('窗口之外、方向反了、金额不同、不是转账：都不算', () => {
    expect(recentTwin([tx({ created_at: '2026-10-27T11:00:00' })], body, 48, now)).toBeNull()
    expect(recentTwin([tx({ payer_id: 1, to_member_id: 2 })], body, 48, now)).toBeNull()
    expect(recentTwin([tx({ amount_jpy: 5_000 })], body, 48, now)).toBeNull()
    expect(recentTwin([tx({ kind: 'expense' })], body, 48, now)).toBeNull()
  })

  it('设置填 0 ＝ 不问', () => {
    expect(recentTwin([tx({})], body, 0, now)).toBeNull()
    // 客户端时钟比服务器慢：刚记的那笔 created_at 晚于 now。没有「0 ＝ 不问」那道守卫的话，
    // 窗口 [now, …) 照样把它框进来
    expect(recentTwin([tx({ created_at: '2026-10-29T12:01:00' })], body, 0, now)).toBeNull()
  })
})

describe('付款人那天在不在籍（审计 #19）', () => {
  it('入住当天、搬走当天都算在籍（和 meta.membersOn 同一个口径）', () => {
    const m = { joined_on: '2026-04-01', left_on: '2026-08-31' }
    expect(payerAbsence(m, '2026-04-01')).toBeNull()
    expect(payerAbsence(m, '2026-08-31')).toBeNull()
    expect(payerAbsence(m, '2026-09-01')).toBe('left')
    expect(payerAbsence(m, '2026-03-31')).toBe('notYet')
    expect(payerAbsence({ joined_on: '2026-04-01', left_on: null }, '2030-01-01')).toBeNull()
  })
})
