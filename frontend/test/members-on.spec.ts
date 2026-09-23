/**
 * 分摊预览要按**这笔账的日期**挑参与人，不是按「今天在籍」。
 *
 * 后端就是这么挑的（ledger.active_members(on)），而记一笔允许把日期往回调。
 * 两边口径一旦不同，日期跨过谁的入住日/退出日时，预览和落库就分到不同的人
 * 头上 —— 差的是整整一份钱，界面上一声不吭。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useMeta } from '../src/stores/meta'

vi.mock('src/api/client', () => ({ api: { get: () => Promise.resolve([]) } }))
vi.mock('src/stores/auth', () => ({ useAuth: () => ({ me: { id: 2 } }) }))

const mk = (id: number, joined: string, left: string | null = null) => ({
  id, name: `m${id}`, display_name: `M${id}`, color: '#000', display_order: id,
  joined_on: joined, left_on: left, lang: 'zh', is_active: true,
})

beforeEach(() => setActivePinia(createPinia()))

describe('按账目日期挑参与人', () => {
  it('还没搬进来的人不参与那天的账', () => {
    const meta = useMeta()
    meta.members = [mk(1, '2026-01-01'), mk(2, '2026-01-01'), mk(3, '2026-04-01')] as never
    expect(meta.membersOn('2026-03-20').map((m) => m.id).sort()).toEqual([1, 2])
    expect(meta.membersOn('2026-04-05').map((m) => m.id).sort()).toEqual([1, 2, 3])
  })

  it('搬走之后的账不算他，搬走当天还算', () => {
    const meta = useMeta()
    meta.members = [mk(1, '2026-01-01'), mk(2, '2026-01-01', '2026-08-31')] as never
    expect(meta.membersOn('2026-08-31').map((m) => m.id).sort()).toEqual([1, 2])
    expect(meta.membersOn('2026-09-01').map((m) => m.id)).toEqual([1])
  })

  it('自己仍然排第一 —— 展示顺序不受影响', () => {
    const meta = useMeta()
    meta.members = [mk(1, '2026-01-01'), mk(2, '2026-01-01'), mk(3, '2026-01-01')] as never
    expect(meta.membersOn('2026-05-01')[0]!.id, '登录的是 2').toBe(2)
  })
})
