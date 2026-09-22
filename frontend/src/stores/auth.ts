import { defineStore } from 'pinia'
import { ref } from 'vue'

import { ApiError, api, setToken } from 'src/api/client'
import type { Member } from 'src/api/types'
import { setLang } from 'src/i18n'

//: 自己是谁，也在本地留一份 —— 和 meta 那份缓存同一个道理。
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
  async function restore() {
    try {
      me.value = await api.get<Member>('/api/auth/me')
      cacheMe(me.value)
      setLang(me.value.lang)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'network') {
        me.value = cachedMe()          // 只是没连上 —— 先用上次认识的那个人
        if (me.value) setLang(me.value.lang)
      } else {
        // 401：client.ts 已经清了 token 并把人踢回登录页，这里跟着清干净
        me.value = null
        cacheMe(null)
      }
    } finally {
      ready.value = true
    }
  }

  /** 改自己的资料。密码要连旧的一起发，后端会验 */
  async function updateMe(patch: Record<string, unknown>): Promise<Member> {
    const saved = await api.patch<Member>(`/api/members/${me.value!.id}`, patch)
    me.value = saved
    cacheMe(saved)
    if (patch.lang) setLang(saved.lang)   // 语言跟人走，改完当场换
    return saved
  }

  async function uploadAvatar(file: File): Promise<Member> {
    const saved = await api.upload<Member>(`/api/members/${me.value!.id}/avatar`, file)
    me.value = saved
    cacheMe(saved)
    return saved
  }

  async function removeAvatar(): Promise<Member> {
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

  return { me, ready, login, restore, updateMe, uploadAvatar, removeAvatar, logout }
})
