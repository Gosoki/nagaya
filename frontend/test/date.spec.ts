/**
 * 业务日期按日本时间算。
 *
 * 原来前端用 `new Date().toISOString().slice(0, 10)` —— 那是 UTC。
 * JST 比 UTC 早 9 小时，所以**日本时间 0 点到 9 点之间 UTC 还停在前一天**，
 * 这段时间记的账全会落到昨天。而半夜记账正是高频场景（聚餐散场）。
 *
 * 真踩过：0 点过几分跑 E2E，新记那笔的日期是昨天，于是按「日期倒序」排
 * 排到了当天出账那一批后面，测试红在一个跟日期毫无关系的断言上。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { todayJst } from '../src/date'

afterEach(() => vi.useRealTimers())

describe('业务日期按日本时间算', () => {
  it('日本时间刚过零点：UTC 还在前一天，取的必须是日本那天', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-21T15:10:00Z')) // JST 2026-09-22 00:10
    expect(new Date().toISOString().slice(0, 10), '前提：UTC 确实还在前一天').toBe('2026-09-21')
    expect(todayJst()).toBe('2026-09-22')
  })

  it('日本时间白天，两者本来就一致', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-22T09:00:00Z')) // JST 18:00
    expect(todayJst()).toBe('2026-09-22')
  })

  it('跨年那一夜也不许错', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-12-31T15:00:00Z')) // JST 2027-01-01 00:00
    expect(todayJst()).toBe('2027-01-01')
  })
})
