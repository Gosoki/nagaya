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
      return t(key, this.detail as Record<string, unknown>)
    }
    return t('errors.unknown', { message: this.message })
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
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
    const code = data?.code ?? 'unknown'
    // detail 只有是对象时才是「命名参数」。HTTPException 返的 detail 是一句话，
    // 当参数用会把文案插成空的
    const detail = typeof data?.detail === 'object' && data.detail !== null ? data.detail : {}
    throw new ApiError(code, data?.message ?? data?.detail ?? res.statusText, detail, res.status)
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}
