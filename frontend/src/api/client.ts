/**
 * REST 客户端。
 *
 * 后端只返 {code, message, detail}，界面文案由前端按 code 查 i18n 决定 ——
 * 所以这里把 code 原样抛出去，页面上用 t(`errors.${code}`) 显示。
 */
import { i18n } from 'src/i18n'

const TOKEN_KEY = 'nagaya.token'

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public detail: Record<string, any> = {},
    public status = 0,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /**
   * 翻成给人看的话。认不出的 code 退回后端那句 message，总比空白强。
   *
   * `unknown` 要**显式排除在查表之外**：errors.unknown 这个键本身是存在的，
   * 不排除的话它会走进查表那一支，拿 detail 当命名参数 —— 而 FastAPI 的
   * HTTPException 返的是 `{detail: "一句话"}`，detail 是个**字符串**，
   * `{message}` 什么都插不进去，于是所有 404 / 409 / 400 都显示成一句
   * 空的「出错了：」。
   */
  get text(): string {
    const key = `errors.${this.code}`
    const t = i18n.global.t
    if (this.code !== 'unknown' && i18n.global.te(key)) {
      return t(key, this.params())
    }
    return t('errors.unknown', { message: this.message })
  }

  /**
   * 插进文案里的那几个值。
   *
   * `detail.key` 要特殊照顾一下：它是**设置项的内部键名**（backup_keep、
   * backup_every_hours 这种英文），而 setting_invalid / setting_out_of_range
   * 两句文案会把它原样插进去 —— 于是日文界面上冒出一句
   * 「設定「backup_keep」の値が不正です」。界面别处显示这些设置时走的是
   * `settings.label.*`，这里跟着走同一张表
   */
  private params(): Record<string, unknown> {
    const detail = { ...this.detail }
    if (typeof detail.key === 'string') {
      const path = `settings.label.${detail.key}`
      if (i18n.global.te(path)) detail.key = i18n.global.t(path)
    }
    return detail as Record<string, unknown>
  }
}

/**
 * 报错时给人看的那句话。非 ApiError 的异常（代码里抛出来的 TypeError 之类）显示成什么，
 * 只在这里定 —— 原来这个三元表达式在十几个组件里各抄一份
 */
export const errorText = (e: unknown): string => (e instanceof ApiError ? e.text : String(e))

// 路由守卫每次切页都要读它。存储被禁用时读写都会抛 —— 别让它把整个 app 带崩，
// 当成「没登录」就行（登录页照样能用，只是记不住）
let memoryToken: string | null = null

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return memoryToken
  }
}

export function setToken(token: string | null) {
  memoryToken = token
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 存不了：这一次打开用内存里那份 */
  }
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

/** 还在路上的写请求有几个。新版换页之前要等它们落地（见 src/update.ts） */
let writing = 0
export const pendingWrites = (): number => writing

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (method === 'GET') return send<T>(method, path, body)
  writing += 1
  try {
    return await send<T>(method, path, body)
  } finally {
    writing -= 1
  }
}

/**
 * 读请求等多久算「连不上」。网络是通的、服务器却够不着时（手机流量下连家里的局域网地址），
 * fetch 要等系统放弃连接才报错，界面一直转圈。**写请求不设**：超时了它可能已经落库，
 * 那时候报「没记上」会让人再记一遍
 */
const GET_TIMEOUT_MS = 10_000
const readSignal = (): AbortSignal | undefined =>
  typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal ? AbortSignal.timeout(GET_TIMEOUT_MS) : undefined

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  // FormData 的 Content-Type 必须让浏览器自己写 —— 里面带着 multipart 的分隔串，
  // 手写一个 'multipart/form-data' 会漏掉它，后端解不出任何字段
  const form = body instanceof FormData
  if (body !== undefined && !form) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : form ? (body as FormData) : JSON.stringify(body),
      signal: method === 'GET' ? readSignal() : undefined,
    })
  } catch {
    throw new ApiError('network', 'fetch failed')
  }

  if (res.status === 401) {
    setToken(null)
    onUnauthorized?.()
    throw new ApiError('unauthorized', 'unauthorized', {}, 401)
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    // FastAPI 自己的请求校验（422）不走 {code, message, detail} 那套：
    // detail 是一个**数组**，里面每项是 {type, loc, msg, input}。
    // 不单独接的话 message 取到的就是这个数组，界面上显示成「出错了：[object Object]」。
    // 到这一步说明前端发出去的形状后端不认 —— 多半是装在桌面上的那份 PWA 旧了
    if (res.status === 422 && Array.isArray(data?.detail)) {
      const why = data.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg ?? ''}`)
        .join('; ')
      throw new ApiError('bad_request', why, {}, 422)
    }
    const code = data?.code ?? 'unknown'
    // detail 只有是对象时才是「命名参数」。HTTPException 返的 detail 是一句话，
    // 当参数用会把文案插成空的
    const detail = typeof data?.detail === 'object' && data.detail !== null ? data.detail : {}
    throw new ApiError(code, data?.message ?? data?.detail ?? res.statusText, detail, res.status)
  }
  return data as T
}

/** 取一张图（头像）。和 send 同一个登录头；回来的不是 JSON，不走那边的解析 */
async function blob(path: string): Promise<Blob> {
  const token = getToken()
  let res: Response
  try {
    res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: readSignal() })
  } catch {
    throw new ApiError('network', 'fetch failed')
  }
  if (!res.ok) throw new ApiError('unknown', res.statusText, {}, res.status)
  return res.blob()
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  blob,
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>('POST', path, form)
  },
}
