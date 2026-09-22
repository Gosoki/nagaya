/**
 * 报错要说得出话。
 *
 * 后端有两种错：
 *   * 业务错 —— `{code, message, detail}`，界面按 code 查自己的文案
 *   * 路由错 —— FastAPI 的 HTTPException，`{detail: "一句话"}`，没有 code
 *
 * 第二种原来会显示成一句空的「出错了：」：code 落成 'unknown'，而
 * errors.unknown 这个键**本身存在**，于是走进查表那一支，拿字符串 detail
 * 当命名参数，`{message}` 什么都插不进去。404 / 409 / 400 全是这个下场。
 */
import { describe, expect, it } from 'vitest'

Object.assign(globalThis, {
  localStorage: { getItem: () => null, setItem: () => {} },
  sessionStorage: { getItem: () => null, setItem: () => {} },
})

const { ApiError } = await import('../src/api/client')

describe('报错文案', () => {
  it('路由错（只有一句 detail）也要把那句话说出来', () => {
    const e = new ApiError('unknown', 'monthly_gap_days 要在 0〜90 之间', {}, 400)
    expect(e.text).toContain('monthly_gap_days 要在 0〜90 之间')
    expect(e.text).not.toBe('出错了：')
  })

  it('业务错按 code 查自己的文案，参数照填', () => {
    expect(new ApiError('self_transfer', 'x').text).toBe('不能转给自己')
    expect(new ApiError('sum_mismatch', 'x', { diff: 3 }).text).toContain('3')
  })

  it('认不出的 code 退回后端那句话', () => {
    expect(new ApiError('never_seen_this', '后端说了点什么').text).toContain('后端说了点什么')
  })

  it('设置项的键名要说人话，不许把 backup_keep 摆到界面上', () => {
    const e = new ApiError('setting_out_of_range', 'x', { key: 'backup_keep', min: 1, max: 30 })
    expect(e.text).toContain('备份留几份')
    expect(e.text).not.toContain('backup_keep')
  })

  it('FastAPI 的 422 不能显示成「[object Object]」', () => {
    const e = new ApiError('bad_request', 'amount_jpy: Input should be a valid integer', {}, 422)
    expect(e.text).not.toContain('[object Object]')
    expect(e.text.length).toBeGreaterThan(4)
  })
})
