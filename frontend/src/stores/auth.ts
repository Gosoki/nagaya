import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, setToken } from 'src/api/client'
import type { Member } from 'src/api/types'
import { setLang } from 'src/i18n'

export const useAuth = defineStore('auth', () => {
  const me = ref<Member | null>(null)
  const ready = ref(false)

  async function login(name: string, password: string) {
    const r = await api.post<{ token: string; member: Member }>('/api/auth/login', { name, password })
    setToken(r.token)
    me.value = r.member
    setLang(r.member.lang)          // 语言跟人走
  }

  async function restore() {
    try {
      me.value = await api.get<Member>('/api/auth/me')
      setLang(me.value.lang)
    } catch {
      me.value = null
    } finally {
      ready.value = true
    }
  }

  /** 改自己的资料。密码要连旧的一起发，后端会验 */
  async function updateMe(patch: Record<string, unknown>): Promise<Member> {
    const saved = await api.patch<Member>(`/api/members/${me.value!.id}`, patch)
    me.value = saved
    if (patch.lang) setLang(saved.lang)   // 语言跟人走，改完当场换
    return saved
  }

  function logout() {
    setToken(null)
    me.value = null
  }

  return { me, ready, login, restore, updateMe, logout }
})
