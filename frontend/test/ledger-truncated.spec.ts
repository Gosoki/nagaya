/**
 * 账目一次只拉最近 N 笔，而筛选和合计都在前端算 —— 拉少了就筛不全。
 *
 * 所以「拿满了」必须能被看见：界面上要在合计旁边写明只算了最近多少笔。
 * 悄悄少算一个金额，比不给这个金额糟得多。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const store = () => {
  const m = new Map<string, string>([['nagaya.lang', 'zh']])
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }
}
Object.assign(globalThis, { localStorage: store(), sessionStorage: store() })

let entryCount = 0
vi.mock('src/api/client', () => ({
  api: {
    get: (url: string) => {
      if (url.startsWith('/api/entries')) return Promise.resolve(Array.from({ length: entryCount }, () => ({})))
      return Promise.resolve({ prev_cut_at: null, prev_label: null })
    },
  },
}))

const { useLedger } = await import('../src/stores/ledger')

beforeEach(() => setActivePinia(createPinia()))

describe('账目拉满了要说出来', () => {
  it('拿满 500 笔 ＝ 还有更早的没拉到', async () => {
    entryCount = 500
    const ledger = useLedger()
    await ledger.refresh()
    expect(ledger.truncated).toBe(true)
  })

  it('没拿满就是全部', async () => {
    entryCount = 499
    const ledger = useLedger()
    await ledger.refresh()
    expect(ledger.truncated).toBe(false)
  })
})
