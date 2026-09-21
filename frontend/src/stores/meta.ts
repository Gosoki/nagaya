import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from 'src/api/client'
import type { Category, Member, Setting } from 'src/api/types'

/** 成员、分类、配置 —— 变得少，登录后拉一次就够。 */
export const useMeta = defineStore('meta', () => {
  const members = ref<Member[]>([])
  const categories = ref<Category[]>([])
  const settings = ref<Setting[]>([])

  const activeMembers = computed(() => members.value.filter((m) => m.is_active))
  const byId = computed(() => Object.fromEntries(members.value.map((m) => [m.id, m])))

  function setting<T>(key: string, fallback: T): T {
    const row = settings.value.find((s) => s.key === key)
    return row === undefined || row.value === null ? fallback : (row.value as T)
  }

  async function load() {
    const [m, c, s] = await Promise.all([
      api.get<Member[]>('/api/members'),
      api.get<Category[]>('/api/categories'),
      api.get<Setting[]>('/api/settings'),
    ])
    members.value = m
    categories.value = c
    settings.value = s
  }

  return { members, categories, settings, activeMembers, byId, setting, load }
})
