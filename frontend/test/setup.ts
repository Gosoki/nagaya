/**
 * 所有 vitest 用例共用的浏览器存储替身（vitest.config.ts 的 setupFiles，每个测试文件跑之前各来一份新的）。
 *
 * 测试跑在 node 里，没有 localStorage / sessionStorage，而 store 的 import 链最后都会碰到
 * i18n 和存储。原来六个文件各写各的替身，长了四种样子，还得靠顶层 `await import()`
 * 保证替身先于 i18n 加载；其中五份的 sessionStorage 没有 removeItem。眼下这些用例
 * 都没走到它，但以后有用例碰到（比如账单 store 把翻到的旧账单清回 null），
 * 抛出来的 TypeError 会被 try/catch 吞掉、悄悄走成「存储不可用」那条支路 ——
 * 所以这里给的是完整的 Storage 接口。
 *
 * 用 vi.stubGlobal 挂：新版 Node 自带只读的 localStorage 访问器，Object.assign 会抛错。
 * 语言先定成中文，i18n 读到了就不再看 navigator。
 */
import { vi } from 'vitest'

function memoryStorage(init: [string, string][] = []): Storage {
  const m = new Map<string, string>(init)
  return {
    get length() {
      return m.size
    },
    key: (i: number) => [...m.keys()][i] ?? null,
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, String(v)),
    removeItem: (k: string) => void m.delete(k),
    clear: () => m.clear(),
  }
}

vi.stubGlobal('localStorage', memoryStorage([['nagaya.lang', 'zh']]))
vi.stubGlobal('sessionStorage', memoryStorage())
