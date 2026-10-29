/**
 * 备忘列表：打开时发出去的那发 GET 晚回来，不许把刚加的那一条盖掉（审计 #66）。
 *
 * 那发 GET 读的是加之前的库，照写的话新加的「房东电话」从界面上消失，人会再加一遍 ——
 * 和 ledger.refresh 同一个办法：出发之后本地写过，就再取一次。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'

import { useMemos } from '../src/stores/memos'

type M = { id: number; title: string; body: string; display_order: number; updated_at: string }
let server: M[] = []
let hold = false
let release: (() => void) | null = null

vi.mock('src/api/client', () => ({
  api: {
    get: () => {
      const snapshot = server.map((m) => ({ ...m }))   // 出发那一刻库里的样子
      if (!hold) return Promise.resolve(snapshot)
      hold = false
      return new Promise((r) => (release = () => r(snapshot)))
    },
    post: (_: string, b: { title: string }) => {
      const m = { id: server.length + 1, title: b.title, body: '', display_order: 0, updated_at: '' }
      server.push(m)
      return Promise.resolve({ ...m })
    },
  },
}))

beforeEach(() => {
  setActivePinia(createPinia())
  server = [{ id: 1, title: '备用钥匙', body: '', display_order: 0, updated_at: '' }]
  hold = false
  release = null
})

it('加之前发出去的 GET 晚回来，刚加的那条还在', async () => {
  const memos = useMemos()
  hold = true
  const loading = memos.load()              // ① 打开备忘：GET 卡在半路
  await memos.create('房东电话')             // ② 这期间加了一条
  release!()                                // ③ 那发旧的现在才回来
  await loading
  expect(memos.items.map((m) => m.title)).toEqual(['备用钥匙', '房东电话'])
  expect(memos.loaded).toBe(true)
})
