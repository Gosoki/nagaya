/**
 * 发版之后换页撞上旧 chunk：整页重载之前，等写请求落地、**也等固定费面板**（src/unsaved，审计 R9）。
 *
 * 面板失焦存一行撞上 409（量级闸、版本冲突）时，写请求已经落地、计数归零，询问框这才弹出来、
 * 那一行还 dirty。只等写请求的话，正好在框底下整页重载 —— 框和填的数一起没了，
 * 整页卸载也不跑「这几项没存上」那条提示。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let onError: ((err: unknown, to: { fullPath: string }) => void) | null = null
let writes = 0
const notify = vi.fn()

vi.mock('vue-router', () => ({
  createWebHistory: () => ({}),
  createRouter: () => ({
    beforeEach: () => {},
    afterEach: () => {},
    onError: (fn: typeof onError) => {
      onError = fn
    },
    currentRoute: { value: { name: 'bill', fullPath: '/bill' } },
  }),
}))
vi.mock('quasar', () => ({ Notify: { create: (o: unknown) => notify(o) } }))
vi.mock('src/i18n', () => ({ i18n: { global: { t: (k: string) => k } } }))
vi.mock('src/update', () => ({ entryChanged: async () => true, applyUpdateIfReady: () => {} }))
vi.mock('src/api/client', () => ({
  getToken: () => 'token',
  setUnauthorizedHandler: () => {},
  pendingWrites: () => writes,
}))

const { holdReload } = await import('../src/unsaved')
await import('../src/router/index')

const replace = vi.fn()
const CHUNK = new Error('Failed to fetch dynamically imported module: /assets/BillPage-old.js')

describe('换 chunk 的整页重载：固定费面板没存上就别刷（R9）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('location', { replace })
    replace.mockClear()
    notify.mockClear()
    sessionStorage.clear()
    writes = 0
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('写请求都落地了、面板上还有没存上的行（询问框开着）：一直不刷，到点说一句', async () => {
    const release = holdReload(() => true)
    try {
      onError!(CHUNK, { fullPath: '/entries' })
      await vi.advanceTimersByTimeAsync(11_000)
      expect(replace, '在询问框底下整页重载了').not.toHaveBeenCalled()
      expect(notify).toHaveBeenCalledWith(expect.objectContaining({ message: 'common.waitingWrite' }))
    } finally {
      release()
    }
  })

  it('人答完、那一行存上了：照常按点的那一页整页打开', async () => {
    let dirty = true
    const release = holdReload(() => dirty)
    try {
      onError!(CHUNK, { fullPath: '/entries' })
      await vi.advanceTimersByTimeAsync(300)
      expect(replace).not.toHaveBeenCalled()
      dirty = false
      await vi.advanceTimersByTimeAsync(200)
      expect(replace).toHaveBeenCalledWith('/entries')
    } finally {
      release()
    }
  })

  it('摘掉之后（面板卸载了）不再挡着', async () => {
    holdReload(() => true)()
    onError!(CHUNK, { fullPath: '/entries' })
    await vi.advanceTimersByTimeAsync(50)
    expect(replace).toHaveBeenCalledWith('/entries')
  })
})
