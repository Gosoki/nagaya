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

  /** 日常记账那屏的分类：不含每月一次的固定项，也不含归档的 */
  const dailyCategories = computed(() =>
    categories.value.filter((c) => !c.monthly && !c.archived),
  )
  /** 出账单时顺手填的固定项 */
  const monthlyCategories = computed(() =>
    categories.value.filter((c) => c.monthly && !c.archived),
  )
  /**
   * 按 id 反查分类，**含归档的**。
   * 历史账目要靠它显示名字和图标 —— 只拿未归档列表去反查的话，
   * 归档掉一个分类，它名下所有历史账目当场掉成「支出」两个字加默认图标。
   */
  const categoryById = computed(() =>
    Object.fromEntries(categories.value.map((c) => [c.id, c])),
  )

  function setting<T>(key: string, fallback: T): T {
    const row = settings.value.find((s) => s.key === key)
    return row === undefined || row.value === null ? fallback : (row.value as T)
  }

  async function load() {
    const [m, c, s] = await Promise.all([
      api.get<Member[]>('/api/members'),
      // 拉全量（含归档）：展示用的列表自己过滤，反查名字要用全量，
      // 否则归档一个分类会让它名下的历史账目失名
      api.get<Category[]>('/api/categories?include_archived=true'),
      api.get<Setting[]>('/api/settings'),
    ])
    members.value = m
    categories.value = c
    settings.value = s
  }

  return {
    members, categories, settings,
    activeMembers, byId,
    dailyCategories, monthlyCategories, categoryById,
    setting, load,
  }
})
