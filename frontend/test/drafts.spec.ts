/**
 * 离线草稿写不进本机时，不许假装存上了（审计 #64）。
 *
 * 站点存储被整个禁用（iOS「阻止所有 Cookie」）时 setItem 会抛。原来 add() 把异常吞掉、
 * 草稿照样挂进内存里的列表：记一笔那屏提示「没网，先存在本地了」并清空表单，横幅也挂着 ——
 * 可那一笔只活在内存里，PWA 被系统杀掉、或者整页重载换新版之后就没了。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { EntryPayload } from '../src/api/types'
import { useDrafts } from '../src/stores/drafts'

vi.mock('src/api/client', () => ({ ApiError: class extends Error {} }))
vi.mock('src/stores/auth', () => ({ useAuth: () => ({ me: { id: 1 } }) }))
vi.mock('src/stores/ledger', () => ({
  useLedger: () => ({ create: (p: EntryPayload) => Promise.resolve({ id: 9, ...p, statement_id: null }) }),
}))

const body: EntryPayload = { kind: 'expense', date: '2026-10-29', amount_jpy: 777, payer_id: 1, client_key: 'k1' }

describe('离线草稿', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.removeItem('nagaya.drafts')
    vi.restoreAllMocks()
  })

  it('本机存不进去：add 返回 false，也不留一份只活在内存里的', () => {
    const drafts = useDrafts()
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    expect(drafts.add(body, 1)).toBe(false)
    expect(drafts.count, '横幅不该挂着一笔重载就没了的草稿').toBe(0)
    expect(localStorage.getItem('nagaya.drafts')).toBeNull()
  })

  it('存得进去：add 返回 true；单条丢得掉，别的留着', () => {
    const drafts = useDrafts()
    expect(drafts.add(body, 1)).toBe(true)
    expect(drafts.add({ ...body, amount_jpy: 888, client_key: 'k2' }, 1)).toBe(true)
    expect(drafts.count).toBe(2)
    drafts.remove(drafts.mine[0]!.id)
    expect(drafts.mine.map((d) => d.payload.amount_jpy)).toEqual([888])
    expect(JSON.parse(localStorage.getItem('nagaya.drafts')!)).toHaveLength(1)
  })

  it('补交把交上去的那几笔原样还回来（横幅逐笔报「已记下」、给撤销）', async () => {
    const drafts = useDrafts()
    drafts.add(body, 1)
    const { ok, saved } = await drafts.submitAll()
    expect(ok).toBe(1)
    expect(saved.map((e) => e.amount_jpy)).toEqual([777])
    expect(drafts.count).toBe(0)
  })
})
