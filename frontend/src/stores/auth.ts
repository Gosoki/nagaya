import { defineStore } from 'pinia'
import { ref } from 'vue'

import { ApiError, api, setToken } from 'src/api/client'
import type { Member } from 'src/api/types'
import { setLang } from 'src/i18n'
import { resetPrefs, syncPrefs } from 'src/prefs'

// 自己是谁，也在本地留一份 —— 和 meta 那份缓存同一个道理。
//  它只用来做**界面门卫**（谁能点「确认已完成」、显不显示个人设置、默认付款人），
//  真正的权限判定在后端拿 token 说话，所以用一份本地缓存的身份不放大任何权限。
const ME_KEY = 'nagaya.me'

function cachedMe(): Member | null {
  try {
    const raw = localStorage.getItem(ME_KEY)
    return raw ? (JSON.parse(raw) as Member) : null
  } catch {
    return null              // 隐私模式下读不了就算了
  }
}

function cacheMe(m: Member | null) {
  try {
    if (m) localStorage.setItem(ME_KEY, JSON.stringify(m))
    else localStorage.removeItem(ME_KEY)
  } catch {
    /* 存不了不影响用 */
  }
}

export const useAuth = defineStore('auth', () => {
  const me = ref<Member | null>(null)
  const ready = ref(false)

  async function login(name: string, password: string) {
    const r = await api.post<{ token: string; member: Member }>('/api/auth/login', { name, password })
    setToken(r.token)
    me.value = r.member
    cacheMe(r.member)
    setLang(r.member.lang)          // 语言跟人走
    // 深浅色、主题色也跟人走。等它换好再进门，免得先闪一下上一位的颜色。
    // 取不到就退回默认：留着上一位的话，开机那次对表会把它当成「这个人本机挑的」传进他的账号
    await syncPrefs(false).catch(resetPrefs)
  }

  /**
   * 冷启动时认一下自己是谁。
   *
   * **「没连上」和「token 失效」要分开。** 原来两种都 `me.value = null`：
   * 断网冷启动时 meta 有本地缓存、布局照常渲染、连重试按钮都不出现，
   * 唯独 auth.me 是空的 —— 于是「确认已完成」按钮和整块个人设置凭空消失，
   * 而 boot() 只在 onMounted 跑一次、MainLayout 切 Tab 又不卸载，
   * 这个半残状态一直维持到整页刷新。
   */
  /** 本机改过几次自己的资料。restore 的 GET 在路上时改了语言，回来的是改之前的 */
  let edits = 0

  async function restore() {
    const mine = edits
    try {
      const fresh = await api.get<Member>('/api/auth/me')
      if (mine !== edits) return
      me.value = fresh
      cacheMe(fresh)
      setLang(fresh.lang)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        // 401：client.ts 已经清了 token 并把人踢回登录页，这里跟着清干净
        me.value = null
        cacheMe(null)
      } else {
        // 没连上、或者服务器那边 5xx（重启中、反代 502）—— token 没说不行，
        // 先用上次认识的那个人。原来除了断网一律当 token 失效，身份被清掉，
        // 「确认已完成」和个人设置凭空消失，要整页刷新才回来
        me.value = cachedMe()
        if (me.value) setLang(me.value.lang)
      }
    } finally {
      ready.value = true
    }
  }

  /** 冷启动先认本机记着的那个人（不等网络），认得出就返回 true。真正的核对交给 restore() */
  function useCached(): boolean {
    if (!me.value) {
      me.value = cachedMe()
      if (me.value) setLang(me.value.lang)
    }
    return me.value !== null
  }

  /** 改自己的资料。密码要连旧的一起发，后端会验 */
  async function updateMe(patch: Record<string, unknown>): Promise<Member> {
    edits += 1
    const saved = await api.patch<Member>(`/api/members/${me.value!.id}`, patch)
    me.value = saved
    cacheMe(saved)
    if (patch.lang) setLang(saved.lang)   // 语言跟人走，改完当场换
    return saved
  }

  async function uploadAvatar(file: File): Promise<Member> {
    edits += 1
    const saved = await api.upload<Member>(`/api/members/${me.value!.id}/avatar`, file)
    me.value = saved
    cacheMe(saved)
    return saved
  }

  async function removeAvatar(): Promise<Member> {
    edits += 1
    const saved = await api.del<Member>(`/api/members/${me.value!.id}/avatar`)
    me.value = saved
    cacheMe(saved)
    return saved
  }

  function logout() {
    setToken(null)
    me.value = null
    cacheMe(null)          // 和 token 同步清掉，别留下「人还在、token 没了」
  }

  return { me, ready, login, restore, useCached, updateMe, uploadAvatar, removeAvatar, logout }
})
